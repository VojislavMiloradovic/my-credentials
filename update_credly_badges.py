"""
update_credly_badges.py
-----------------------
Pipeline for updating Credly profile badges and credentials via Credly public API.
Includes Credly API pagination, JSON parsing, Pydantic schema validation,
date coercion, data loss / anomaly guards, safe directory handling, archiver integration,
and additive dataset merging to prevent API page truncation data loss.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

# Archive Integration Helper
try:
    from archiver import RAW_BASE_DEFAULT, generate_platform_archive
except ImportError:
    RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
    generate_platform_archive = None

# Content-Aware Loss Guard
try:
    from loss_guard import PipelineDataLossAnomaly, execute_content_loss_guard
except ImportError:
    # Fallback if loss_guard not available
    execute_content_loss_guard = None
    PipelineDataLossAnomaly = Exception

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("credly_updater")

# Configuration Constants & Canonical Paths
CREDLY_USER = os.getenv("CREDLY_USER", "vojislavmiloradovic")
CREDLY_USER_ID = os.getenv("CREDLY_USER_ID", "752aee40-7358-4ade-9a49-81e8b6f49225")
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "credly_badges.json"
OUTPUT_FILE = os.getenv("OUTPUT_FILE", os.path.join(VALIDATION_DIR, OUTPUT_FILENAME))
ARCHIVE_MONOLITH = os.path.join("archives", "credly-complete.md")

# Anomaly Guard Tolerance
MAX_ALLOWED_DATA_LOSS_PCT = 0.15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


# ==============================================================================
# PYDANTIC SCHEMAS & VALIDATION PIPELINE
# ==============================================================================

def normalize_date_string(raw_date: Any) -> str | None:
    """Coerces timestamps, ISO strings, and standard text dates to YYYY-MM-DD."""
    if raw_date is None or raw_date in ("", "N/A", "None", "null"):
        return None

    if isinstance(raw_date, (int, float)):
        try:
            ts = float(raw_date)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    s_date = str(raw_date).strip()
    if not s_date or s_date.lower() in ("none", "null", "n/a"):
        return None

    if s_date.isdigit():
        try:
            ts = float(s_date)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    parts = s_date.split("T")[0].split(" ")[0]
    if len(parts) == 10 and parts[4] == "-" and parts[7] == "-":
        return parts

    for fmt in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(s_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(s_date)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return None


class CredlyBadgeItemModel(BaseModel):
    """Normalized schema for Credly badge entities."""
    id: str = Field(..., min_length=1, description="Credly unique badge ID")
    title: str = Field(..., min_length=1, description="Badge title")
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field(..., min_length=1, description="Organization issuing the badge")
    issuer_name: str = Field(..., min_length=1, description="Issuer alias for compatibility")
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Badge image asset URL")
    verify_url: str | None = Field(None, description="Public verification link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("Credly Verified Badge", description="Classification type")
    verification_type: str = Field("Credly Verified Badge", description="Verification category")
    skills: list[str] = Field(default_factory=list, description="Associated skills")

    @field_validator("issued_at", "issued_at_date", "date", mode="before")
    @classmethod
    def validate_and_coerce_dates(cls, val: Any) -> str | None:
        return normalize_date_string(val)

    @field_validator("skills", mode="before")
    @classmethod
    def sanitize_skills_list(cls, val: Any) -> list[str]:
        if isinstance(val, list):
            clean = []
            for item in val:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("title")
                    if name and str(name).strip():
                        clean.append(str(name).strip())
                elif isinstance(item, str) and item.strip():
                    clean.append(item.strip())
            return list(dict.fromkeys(clean))
        elif isinstance(val, str) and val.strip():
            return [val.strip()]
        return []


class CredlyArchivePayloadModel(BaseModel):
    """Root model for Credly persistence JSON validation."""
    credly_user: str
    total_count: int = Field(ge=0)
    badges: list[CredlyBadgeItemModel]


# ==============================================================================
# ANOMALY & LOSS GUARD ASSERTIONS
# ==============================================================================

class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous archive baseline."""


def get_stored_archive_baseline_count(json_path: str, monolith_path: str) -> int:
    """Evaluates baseline record count from existing JSON or monolith archive markdown."""
    candidate_json_paths = [
        json_path,
        os.path.join(VALIDATION_DIR, OUTPUT_FILENAME),
        OUTPUT_FILENAME,
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for path in candidate_json_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    count = data.get("total_count", len(data.get("badges", []))) if isinstance(data, dict) else len(data)
                    if count > 0:
                        return count
            except (json.JSONDecodeError, OSError):
                pass

    if os.path.exists(monolith_path):
        try:
            with open(monolith_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            rows = [l for l in lines if l.strip().startswith("|") and not l.strip().startswith("| Date") and ":---" not in l]
            if len(rows) > 0:
                return len(rows)
        except OSError:
            pass

    return 0


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    """Loss Guard: Compares incoming badge count against stored baseline."""
    old_count = get_stored_archive_baseline_count(output_file, ARCHIVE_MONOLITH)
    new_count = len(new_badges)

    logger.info(f"🛡️ Loss Guard Check: Stored Archive Baseline = {old_count} badges | Incoming Dataset = {new_count} badges.")

    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming fetch returned 0 badges, but stored archive baseline contains {old_count}. Aborting sync."
        )

    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming badge count ({new_count}) dropped by {drop_ratio:.1%} "
                f"from baseline ({old_count}). Maximum allowed threshold is {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting write."
            )

    logger.info("✅ Loss Guard Assertion Passed: Incoming payload verified against archive baseline.")


# ==============================================================================
# CREDLY API FETCHING & MERGING
# ==============================================================================

def parse_credly_badges_from_json(json_path: str) -> list[dict]:
    """Reads existing Credly badge entries directly from specified JSON file."""
    if not os.path.exists(json_path):
        return []

    logger.info(f"📄 Reading existing Credly badges from JSON: '{json_path}'")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_list = data.get("badges", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        badges = []
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    validated = CredlyBadgeItemModel(**item)
                    badges.append(validated.model_dump())
                except ValidationError as ve:
                    logger.warning(f"⚠️ Skipping invalid JSON badge entry: {ve}")

        logger.info(f"✅ Loaded {len(badges)} valid Credly badges from JSON file.")
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"⚠️ Error reading JSON file '{json_path}': {e}")
        return []


def load_existing_local_badges() -> list[dict]:
    """Loads existing local badges from for_validation directory prior to API fetch."""
    candidates = [
        OUTPUT_FILE,
        os.path.join(VALIDATION_DIR, OUTPUT_FILENAME),
        OUTPUT_FILENAME,
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for path in candidates:
        if os.path.exists(path):
            badges = parse_credly_badges_from_json(path)
            if badges:
                return badges
    return []


def fetch_credly_badges(username: str) -> list[dict] | None:
    """Fetches badges directly from Credly's public user API endpoint with pagination."""
    url = f"https://www.credly.com/users/{username}/badges.json"
    logger.info(f"🔄 Fetching Credly badges from API endpoint: {url}")

    badges = []
    seen_badge_ids: set[str] = set()
    page = 1

    while True:
        try:
            response = requests.get(f"{url}?page={page}", headers=HEADERS, timeout=20)
            if response.status_code != 200:
                logger.warning(f"⚠️ Credly API returned status code {response.status_code} on page {page}.")
                return None if not badges else badges

            payload = response.json()
            data_list = payload.get("data", []) if isinstance(payload, dict) else []

            if not data_list:
                break

            ids_before_page = len(seen_badge_ids)
            for item in data_list:
                badge_template = item.get("badge_template", {}) or {}
                issuer_info = badge_template.get("issuer", {}) or {}

                title = badge_template.get("name") or item.get("name") or "Credly Badge"
                issuer_name = (
                    issuer_info.get("summary")
                    or issuer_info.get("name")
                    or badge_template.get("issuer_name")
                    or "Credly Issuer"
                )

                dt = item.get("issued_at") or item.get("created_at")
                badge_id = str(item.get("id"))
                if badge_id in seen_badge_ids:
                    continue
                seen_badge_ids.add(badge_id)
                verify_url = f"https://www.credly.com/badges/{badge_id}/public_url"

                raw_skills = badge_template.get("skills", [])

                raw_entry = {
                    "id": badge_id,
                    "title": title,
                    "name": title,
                    "issuer": issuer_name,
                    "issuer_name": issuer_name,
                    "issued_at": dt,
                    "issued_at_date": dt,
                    "date": dt,
                    "image_url": badge_template.get("image_url") or item.get("image_url"),
                    "verify_url": verify_url,
                    "url": verify_url,
                    "type": "Credly Verified Badge",
                    "verification_type": "Credly Verified Badge",
                    "skills": raw_skills,
                }

                try:
                    validated = CredlyBadgeItemModel(**raw_entry)
                    badges.append(validated.model_dump())
                except ValidationError as ve:
                    logger.warning(f"⚠️ Skipping invalid Credly API entry '{title}': {ve}")

            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            next_page = metadata.get("next_page") or metadata.get("next_page_url")
            if next_page is None and len(data_list) < 48:
                break
            if len(seen_badge_ids) == ids_before_page and page > 1:
                logger.warning("⚠️ Credly API returned no new badge IDs; stopping pagination.")
                break
            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Exception occurred while requesting Credly API: {e}")
            return None if not badges else badges

    if badges:
        logger.info(f"✅ Successfully fetched {len(badges)} badges from Credly API.")

    return badges


def fetch_credly_external_badges(user_id: str) -> list[dict] | None:
    """Fetches Credly's public external/open-badge records."""
    url = f"https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public"
    logger.info(f"🔄 Fetching External Open Badges API endpoint: {url}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.error(f"❌ Exception occurred while requesting external Credly badges: {exc}")
        return None

    records = payload.get("data", []) if isinstance(payload, dict) else []
    badges = []
    for item in records:
        external = item.get("external_badge", {}) or {}
        badge_id = str(item.get("id") or external.get("credly_record_id") or "").strip()
        title = str(external.get("badge_name") or "Credly External Badge").strip()
        issuer = str(external.get("issuer_name") or "External Issuer").strip()
        verify_url = external.get("badge_url") or external.get("badge_id")
        issued_at = external.get("issued_at_date") or external.get("issued_at")

        raw_entry = {
            "id": badge_id,
            "title": title,
            "name": title,
            "issuer": issuer,
            "issuer_name": issuer,
            "issued_at": issued_at,
            "issued_at_date": issued_at,
            "date": issued_at,
            "image_url": external.get("image_url"),
            "verify_url": verify_url,
            "url": verify_url,
            "type": "Credly External Badge",
            "verification_type": "Credly External Badge",
            "skills": external.get("skills", []),
        }
        try:
            badges.append(CredlyBadgeItemModel(**raw_entry).model_dump())
        except ValidationError as exc:
            logger.warning(f"⚠️ Skipping invalid external Credly entry '{title}': {exc}")

    logger.info(f"✅ Successfully fetched {len(badges)} external open badges from Credly API.")
    return badges


def merge_badge_datasets(api_badges: list[dict], external_badges: list[dict]) -> list[dict]:
    """
    Unions the two live Credly datasets by stable record ID.
    """
    badge_map = {}

    for b in api_badges + external_badges:
        key = b.get("id") or f"{b.get('title')}-{b.get('issued_at')}"
        if key:
            badge_map[key] = b

    merged = list(badge_map.values())
    logger.info(
        f"🔗 Union Merge Complete: Total = {len(merged)} badges "
        f"(Native={len(api_badges)}, External={len(external_badges)})."
    )
    return merged


# ==============================================================================
# ARCHIVE BUILDER
# ==============================================================================

def build_archives_and_readme(badges: list[dict]) -> None:
    """Invokes archiver helper to generate markdown files and update README."""
    if not generate_platform_archive:
        logger.error("❌ Archiver module helper unavailable. Skipping markdown generation.")
        return

    sorted_badges = sorted(
        badges,
        key=lambda b: str(b.get("issued_at") or ""),
        reverse=True,
    )

    all_skills: set[str] = set()
    formatted_rows = []

    for b in sorted_badges:
        date_str = str(b.get("issued_at") or "2026-01-01").strip()
        title = str(b.get("title") or "Unknown Credential").strip()
        verify_url = b.get("verify_url")
        issuer = str(b.get("issuer") or "Credly").strip()
        v_type = str(b.get("type") or "Credly Verified Badge").strip()

        for skill in b.get("skills", []):
            if isinstance(skill, str) and skill.strip():
                all_skills.add(skill.strip())

        title_clean = title.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        issuer_clean = issuer.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        v_type_clean = v_type.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()

        name_cell = f"[{title_clean}]({verify_url})" if verify_url else title_clean
        row_text = f"| {date_str} | {name_cell} | {issuer_clean} | {v_type_clean} |"
        formatted_rows.append((row_text, date_str))

    total_count = len(sorted_badges)
    total_skills = len(all_skills)

    now_ym = datetime.now(UTC).strftime("%Y-%m")
    index_raw = f"{RAW_BASE_DEFAULT}/credly-index.md"
    part1_raw = f"{RAW_BASE_DEFAULT}/credly-{now_ym}-part-01.md"

    marker_start = "<!-- CREDLY_BADGES_START -->"
    marker_end = "<!-- CREDLY_BADGES_END -->"

    profile_url = f"https://www.credly.com/users/{CREDLY_USER}"

    readme_lines = [
        "### Credly Verified Credentials",
        "",
        f"[Credly Profile]({profile_url})",
        "",
        f"Public Profile: [Verify Credly Profile]({profile_url})",
        f"**Total Portfolio Credentials:** {total_count}",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/credly-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({part1_raw}), or [Monolithic File](./archives/credly-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    generate_platform_archive(
        platform_prefix="credly",
        platform_name="Credly Verified Credentials",
        table_headers=["Date Earned", "Credential Name", "Issuer", "Verification Type"],
        table_alignments=[":---:", ":---", ":---", ":---:"],
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=marker_start,
        marker_end=marker_end,
    )


# ==============================================================================
# PIPELINE ORCHESTRATOR
# ==============================================================================

def main():
    logger.info("Starting Credly API Pipeline with Pydantic & Loss Guards...")

    # Safe directory initialization
    if os.path.exists(VALIDATION_DIR) and not os.path.isdir(VALIDATION_DIR):
        logger.warning(f"⚠️ '{VALIDATION_DIR}' exists as a file. Removing it to create a directory.")
        os.remove(VALIDATION_DIR)

    os.makedirs(VALIDATION_DIR, exist_ok=True)

    # 1. Load existing local badges BEFORE calling API
    local_badges = load_existing_local_badges()

    # 2. Fetch both live Credly datasets
    native_badges = fetch_credly_badges(CREDLY_USER)
    external_badges = fetch_credly_external_badges(CREDLY_USER_ID)

    # Keep the last valid local dataset only when a live source is unavailable.
    # Do not merge it into a successful refresh: that would make stale records immortal.
    if native_badges is None or external_badges is None:
        logger.warning("⚠️ One or more Credly sources failed; retaining the previous local dataset.")
        unique_badges = local_badges
    else:
        unique_badges = merge_badge_datasets(native_badges, external_badges)

    # 3. Anomaly & Loss Guard Assertion - Content-Aware
    #    Uses stable Credly badge IDs (UUIDs) and content hashes to detect
    #    replacement/modification even when total badge count remains stable.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=unique_badges,
                platform="credly",
                id_field="id",  # Credly badges have stable UUID 'id' field
                fail_on_warn=True  # SET TO False TO DISABLE FAILURES (comment out raise in loss_guard.py)
            )
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)
    else:
        logger.warning("⚠️ Content-aware loss guard unavailable, falling back to count-only check")
        try:
            execute_data_loss_guard(unique_badges, OUTPUT_FILE)
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)

    # 4. Pydantic Payload Validation & File Dump strictly into for_validation/
    payload_dict = {
        "credly_user": CREDLY_USER,
        "total_count": len(unique_badges),
        "badges": unique_badges,
    }

    try:
        validated_payload = CredlyArchivePayloadModel(**payload_dict)

        # Save output JSON file inside for_validation directory ONLY
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(validated_payload.model_dump_json(indent=2))

        logger.info(f"🎉 Persistence complete: '{OUTPUT_FILE}' updated ({len(unique_badges)} badges).")
    except ValidationError as ve:
        logger.error(f"❌ Root Payload Validation Error: {ve}")
        sys.exit(1)

    # 5. Build Markdown Archives
    build_archives_and_readme(unique_badges)
    logger.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
