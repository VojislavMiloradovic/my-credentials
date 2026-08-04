#!/usr/bin/env python3
"""
update_credly_badges.py
-----------------------
API pipeline updating Credly native credentials and external Open Badges.
Includes Pydantic schema validation models, API response parsing, and
data loss/anomaly guards to prevent archive corruption or silent record drops.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

# Archive Integration Helper
try:
    from archiver import RAW_BASE_DEFAULT, generate_platform_archive
except ImportError:
    RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
    generate_platform_archive = None

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("credly_updater")

# Configuration Constants
CREDLY_USERNAME = os.getenv("CREDLY_USERNAME", "vojislavmiloradovic")
CREDLY_USER_ID = os.getenv("CREDLY_USER_ID", "752aee40-7358-4ade-9a49-81e8b6f49225")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "credly_badges.json")

# Data Loss / Anomaly Guard Tolerances
MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Fail if new badge count drops >15% below stored archive

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
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
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
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
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    parts = s_date.split("T")[0].split(" ")[0]
    if len(parts) == 10 and parts[4] == "-" and parts[7] == "-":
        return parts

    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(s_date.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return None


class BadgeItemModel(BaseModel):
    """Normalized schema for processed badge entity validated before archive output."""
    id: str = Field(..., min_length=1, description="Unique badge ID or hash fallback")
    title: str = Field(..., min_length=1, description="Verified credential or badge title")
    name: str = Field(..., min_length=1, description="Standard title duplicate for compatibility")
    issuer: str = Field(..., min_length=1, description="Issuing organization or authority")
    issuer_name: str = Field(..., min_length=1, description="Issuer alias for schema compatibility")
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    expires_at: str | None = Field(None, description="ISO YYYY-MM-DD expiration date or None")
    image_url: str | None = Field(None, description="Hosted badge image asset URL")
    verify_url: str | None = Field(None, description="Public verification link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("Credly Verified", description="Credly Verified or External/Imported")
    verification_type: str = Field("Credly Verified", description="Alias for verification category")
    skills: list[str] = Field(default_factory=list, description="Array of extracted skill strings")

    @field_validator("issued_at", "issued_at_date", "date", "expires_at", mode="before")
    @classmethod
    def validate_and_coerce_dates(cls, val: Any) -> str | None:
        return normalize_date_string(val)

    @field_validator("skills", mode="before")
    @classmethod
    def sanitize_skills_list(cls, val: Any) -> list[str]:
        if isinstance(val, list):
            clean = []
            for item in val:
                if isinstance(item, str) and item.strip():
                    clean.append(item.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("title")
                    if isinstance(name, str) and name.strip():
                        clean.append(name.strip())
            return list(dict.fromkeys(clean))
        elif isinstance(val, str) and val.strip():
            return [val.strip()]
        return []


class CredlyArchivePayloadModel(BaseModel):
    """Root model for JSON persistence validation."""
    user_username: str
    user_id: str
    total_count: int = Field(ge=0)
    native_count: int = Field(ge=0)
    external_count: int = Field(ge=0)
    badges: list[BadgeItemModel]


# ==============================================================================
# ANOMALY & LOSS GUARD ASSERTIONS
# ==============================================================================

class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous archive baseline."""


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    """
    Loss Guard: Compares new incoming parsed badge count against existing local JSON.
    Prevents corrupt API payloads or truncated server responses from silently clearing archive data.
    """
    if not os.path.exists(output_file):
        logger.info(f"🛡️ Loss Guard: Initial creation mode (no existing '{output_file}').")
        return

    try:
        with open(output_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)

        old_badges = old_data.get("badges", [])
        old_count = old_data.get("total_count", len(old_badges))
        new_count = len(new_badges)

        logger.info(f"🛡️ Loss Guard Check: Stored Archive = {old_count} badges | Incoming API = {new_count} badges.")

        if old_count > 0 and new_count == 0:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming API payload returned 0 badges, but stored archive contains {old_count}. Aborting sync."
            )

        if old_count > 0:
            drop_ratio = (old_count - new_count) / float(old_count)
            if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
                raise PipelineDataLossAnomaly(
                    f"CRITICAL ANOMALY: Incoming badge count ({new_count}) dropped by {drop_ratio:.1%} "
                    f"from baseline ({old_count}). Maximum allowed drop threshold is {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting write."
                )

        logger.info("✅ Loss Guard Assertion Passed: Incoming payload verified against archive baseline.")

    except json.JSONDecodeError:
        logger.warning(f"⚠️ Loss Guard Notice: '{output_file}' exists but contains invalid JSON. Overwriting safely.")


# ==============================================================================
# DEEP EXTRACTION & API FETCHERS
# ==============================================================================

def extract_title(item: dict) -> str:
    candidates = []
    bc = item.get("badge_class")
    if isinstance(bc, dict):
        candidates.extend([bc.get("name"), bc.get("title")])

    for k in ("title", "name", "badge_name", "badge_template_name"):
        candidates.append(item.get(k))

    badge = item.get("badge")
    if isinstance(badge, dict):
        candidates.extend([badge.get("name"), badge.get("title")])
        badge_bc = badge.get("badge_class")
        if isinstance(badge_bc, dict):
            candidates.extend([badge_bc.get("name"), badge_bc.get("title")])

    bt = item.get("badge_template")
    if isinstance(bt, dict):
        candidates.extend([bt.get("name"), bt.get("title")])

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            clean = cand.strip()
            if clean.lower() not in {"external badge", "external credential", "badge", "credential"}:
                return clean

    return "External Credential"


def extract_issuer(item: dict) -> str:
    candidates = []
    bc = item.get("badge_class")
    if isinstance(bc, dict):
        bc_issuer = bc.get("issuer")
        if isinstance(bc_issuer, dict):
            candidates.extend([bc_issuer.get("name"), bc_issuer.get("title")])
        elif isinstance(bc_issuer, str):
            candidates.append(bc_issuer)

    for k in ("issuer_name", "issuer_organization_name"):
        candidates.append(item.get(k))

    raw_issuer = item.get("issuer")
    if isinstance(raw_issuer, str):
        candidates.append(raw_issuer)
    elif isinstance(raw_issuer, dict):
        candidates.append(raw_issuer.get("name"))
        entities = raw_issuer.get("entities", [])
        if isinstance(entities, list) and entities and isinstance(entities[0], dict):
            ent = entities[0].get("entity")
            if isinstance(ent, dict):
                candidates.append(ent.get("name"))

    for parent_key in ("badge", "badge_template"):
        parent = item.get(parent_key)
        if isinstance(parent, dict):
            p_issuer = parent.get("issuer")
            if isinstance(p_issuer, str):
                candidates.append(p_issuer)
            elif isinstance(p_issuer, dict):
                candidates.append(p_issuer.get("name"))

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            clean = cand.strip()
            if clean.lower() not in {"external issuer", "credly issuer", "credly", "issuer"}:
                return clean

    return "External Issuer"


def extract_verify_url(item: dict) -> str | None:
    candidates = [
        item.get("verify_url"),
        item.get("public_url"),
        item.get("url"),
        item.get("target_url"),
        item.get("badge_url"),
    ]
    badge_id = item.get("id") or item.get("uuid")

    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c.strip()

    if badge_id:
        return f"https://www.credly.com/badges/{badge_id}/public_url"

    return None


def fetch_native_badges(username: str) -> list[dict]:
    badges = []
    page = 1
    logger.info(f"🔄 Starting Credly Native API fetch for user '{username}'...")

    while True:
        url = f"https://www.credly.com/users/{username}/badges.json"
        params = {"page": page}

        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            raw_badges = data.get("data", [])
            if not raw_badges:
                break

            logger.info(f"  Page {page}: Fetched {len(raw_badges)} native badges.")

            for item in raw_badges:
                badge_id = item.get("id") or f"native-{len(badges)+1}"
                title = extract_title(item)
                issuer_name = extract_issuer(item)
                issued_at = item.get("issued_at_date") or item.get("issued_at") or item.get("created_at")
                verify_url = extract_verify_url(item)

                skills_raw = item.get("skills") or (item.get("badge_template", {}).get("skills") if isinstance(item.get("badge_template"), dict) else [])
                image_url = item.get("image_url") or (item.get("badge_template", {}).get("image_url") if isinstance(item.get("badge_template"), dict) else None)

                raw_entry = {
                    "id": str(badge_id),
                    "title": title,
                    "name": title,
                    "issuer": issuer_name,
                    "issuer_name": issuer_name,
                    "issued_at": issued_at,
                    "issued_at_date": issued_at,
                    "date": issued_at,
                    "expires_at": item.get("expires_at_date") or item.get("expires_at"),
                    "image_url": image_url,
                    "verify_url": verify_url,
                    "url": verify_url,
                    "type": "Credly Verified",
                    "verification_type": "Credly Verified",
                    "skills": skills_raw,
                }

                try:
                    validated_model = BadgeItemModel(**raw_entry)
                    badges.append(validated_model.model_dump())
                except ValidationError as ve:
                    logger.warning(f"⚠️ Anomaly Guard: Skipping malformed native badge payload: {ve}")

            metadata = data.get("metadata", {})
            total_pages = metadata.get("total_pages")
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed native badge request on page {page}: {e}")
            break

    return badges


def fetch_external_badges(user_id: str) -> list[dict]:
    url = f"https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public"
    logger.info("🔄 Fetching External Open Badges API endpoint...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        raw_external = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        logger.info(f"  Fetched {len(raw_external)} external open badges.")

        parsed_external = []
        for item in raw_external:
            if not isinstance(item, dict):
                continue

            ext_badge = item.get("external_badge") or {}
            badge_id = item.get("id") or ext_badge.get("credly_record_id") or f"ext-{len(parsed_external)+1}"
            title = ext_badge.get("badge_name") or ext_badge.get("name") or item.get("title") or "External Credential"
            issuer_name = ext_badge.get("issuer_name") or item.get("issuer_name") or "External Issuer"
            issued_at = ext_badge.get("issued_at_date") or ext_badge.get("issued_at") or item.get("issued_at")
            expires_at = ext_badge.get("expires_at_date") or ext_badge.get("expires_at")
            verify_url = ext_badge.get("badge_url") or ext_badge.get("badge_id") or item.get("verify_url")

            skills_raw = ext_badge.get("skills", []) or item.get("skills", [])

            raw_entry = {
                "id": str(badge_id),
                "title": title,
                "name": title,
                "issuer": issuer_name,
                "issuer_name": issuer_name,
                "issued_at": issued_at,
                "issued_at_date": issued_at,
                "date": issued_at,
                "expires_at": expires_at,
                "image_url": ext_badge.get("image_url") or item.get("image_url"),
                "verify_url": verify_url,
                "url": verify_url,
                "type": "External/Imported",
                "verification_type": "External/Imported",
                "skills": skills_raw,
            }

            try:
                validated_model = BadgeItemModel(**raw_entry)
                parsed_external.append(validated_model.model_dump())
            except ValidationError as ve:
                logger.warning(f"⚠️ Anomaly Guard: Skipping malformed external badge entry: {ve}")

        return parsed_external

    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Warning: Could not fetch external badges: {e}")
        return []


# ==============================================================================
# ARCHIVE BUILDER & README GENERATION
# ==============================================================================

def build_archives_and_readme(badges: list[dict]) -> None:
    """Invokes archiver to generate markdown chunk files and update README.md."""
    if not generate_platform_archive:
        logger.error("❌ Archiver module helper not available. Skipping markdown generation.")
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
        v_type = str(b.get("type") or "Credly Verified").strip()

        for skill in b.get("skills", []):
            if isinstance(skill, str) and skill.strip():
                all_skills.add(skill.strip())

        title_clean = title.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        issuer_clean = issuer.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        v_type_clean = v_type.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()

        name_cell = f"[{title_clean}]({verify_url})" if verify_url else title_clean
        row_text = f"| {date_str} | {name_cell} | {issuer_clean} | {v_type_clean} |"
        formatted_rows.append((row_text, date_str))

    native_count = sum(1 for b in sorted_badges if b.get("type") == "Credly Verified")
    external_count = sum(1 for b in sorted_badges if b.get("type") == "External/Imported")
    total_count = len(sorted_badges)
    total_skills = len(all_skills)

    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    index_raw = f"{RAW_BASE_DEFAULT}/credly-badges-index.md"
    part1_raw = f"{RAW_BASE_DEFAULT}/credly-badges-{now_ym}-part-01.md"

    marker_start = "<!-- CREDLY_START -->"
    marker_end = "<!-- CREDLY_END -->"
    if os.path.exists("README.md"):
        with open("README.md", "r", encoding="utf-8") as f:
            content = f.read()
        if "<!-- CREDLY_BADGES_START -->" in content:
            marker_start = "<!-- CREDLY_BADGES_START -->"
            marker_end = "<!-- CREDLY_BADGES_END -->"

    readme_lines = [
        "### Credly Credentials",
        "",
        "[Credly Verified Credentials](https://www.credly.com/users/vojislavmiloradovic/badges)",
        "",
        "Public Profile: [Verify Credly Profile](https://www.credly.com/users/vojislavmiloradovic/badges)",
        f"**Total Portfolio Credentials:** {total_count} ({native_count} Credly Verified, {external_count} External/Imported)",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/credly-badges-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({part1_raw}), or [Monolithic File](./archives/credly-badges-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    generate_platform_archive(
        platform_prefix="credly-badges",
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

    native_badges = fetch_native_badges(CREDLY_USERNAME)
    external_badges = fetch_external_badges(CREDLY_USER_ID)

    all_raw = native_badges + external_badges
    unique_badges = []
    seen = set()

    for badge in all_raw:
        dedup_key = badge.get("id") or f"{badge.get('title')}-{badge.get('issuer')}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_badges.append(badge)

    # 1. Execute Data Loss Guard prior to file modification
    try:
        execute_data_loss_guard(unique_badges, OUTPUT_FILE)
    except PipelineDataLossAnomaly as anomaly_err:
        logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
        sys.exit(1)

    # 2. Validate Root Payload with Pydantic Schema
    payload_dict = {
        "user_username": CREDLY_USERNAME,
        "user_id": CREDLY_USER_ID,
        "total_count": len(unique_badges),
        "native_count": len(native_badges),
        "external_count": len(external_badges),
        "badges": unique_badges,
    }

    try:
        validated_payload = CredlyArchivePayloadModel(**payload_dict)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(validated_payload.model_dump_json(indent=2))
        logger.info(f"🎉 Persistence complete: '{OUTPUT_FILE}' updated safely ({len(unique_badges)} badges).")
    except ValidationError as ve:
        logger.error(f"❌ Root Payload Validation Error: {ve}")
        sys.exit(1)

    # 3. Generate Archives and Update README
    build_archives_and_readme(unique_badges)
    logger.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
