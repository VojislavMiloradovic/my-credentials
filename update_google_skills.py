"""
update_google_skills.py
-----------------------
Pipeline for updating Google Skills / Developer credentials from public profile APIs,
local JSON fallbacks, or exported badge data.
Includes JSON parsing, Pydantic schema validation, date coercion,
data loss / anomaly guards, safe directory handling, and archiver integration.
"""

import hashlib
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
    from archiver import RAW_BASE_DEFAULT, generate_platform_archive, safe_write_file
except ImportError:
    RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
    generate_platform_archive = None
    def safe_write_file(filepath: str, new_content: str) -> bool:
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    if f.read() == new_content:
                        return False
            except Exception:
                pass
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)
        return True

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
logger = logging.getLogger("google_skills_updater")

# Configuration Constants & Canonical Paths
GOOGLE_PROFILE_ID = os.getenv("GOOGLE_PROFILE_ID") or "2011cb91-6066-4d7f-bbec-644b1530829b"
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "google_skills_badges.json"
OUTPUT_FILE = os.getenv("OUTPUT_FILE", os.path.join(VALIDATION_DIR, OUTPUT_FILENAME))
ARCHIVE_MONOLITH = os.path.join("archives", "google-skills-complete.md")

# Anomaly Guard Tolerance
MAX_ALLOWED_DATA_LOSS_PCT = 0.15

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


class GoogleBadgeItemModel(BaseModel):
    """Normalized schema for Google Skills credential entities."""
    id: str = Field(..., min_length=1, description="Unique badge ID or hash")
    title: str = Field(..., min_length=1, description="Google achievement or skill title")
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field("Google", description="Issuing body")
    issuer_name: str = Field("Google", description="Issuer alias for compatibility")
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Badge image URL")
    verify_url: str | None = Field(None, description="Public verification or detail link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("Google Skill Badge", description="Credential classification type")
    verification_type: str = Field("Google Skill Badge", description="Alias for verification category")
    skills: list[str] = Field(default_factory=list, description="Associated skills")

    @field_validator("issued_at", "issued_at_date", "date", mode="before")
    @classmethod
    def validate_and_coerce_dates(cls, val: Any) -> str | None:
        return normalize_date_string(val)

    @field_validator("skills", mode="before")
    @classmethod
    def sanitize_skills_list(cls, val: Any) -> list[str]:
        if isinstance(val, list):
            clean = [str(item).strip() for item in val if isinstance(item, str) and item.strip()]
            return list(dict.fromkeys(clean))
        elif isinstance(val, str) and val.strip():
            return [val.strip()]
        return []


class GoogleSkillsArchivePayloadModel(BaseModel):
    """Root model for Google Skills JSON validation."""
    profile_id: str
    total_count: int = Field(ge=0)
    badges: list[GoogleBadgeItemModel]


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
# DATA INGESTION & PARSERS
# ==============================================================================

def generate_badge_id(title: str, date_str: str | None) -> str:
    """Generates a stable identifier for badges lacking explicit IDs."""
    raw = f"google-skills-{title.strip().lower()}-{date_str or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_google_badges_from_json(json_path: str) -> list[dict]:
    """Reads existing Google badge entries directly from local JSON storage."""
    if not os.path.exists(json_path):
        return []

    logger.info(f"📄 Reading existing Google badges from JSON: '{json_path}'")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_list = data.get("badges", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        badges = []
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    validated = GoogleBadgeItemModel(**item)
                    badges.append(validated.model_dump())
                except ValidationError as ve:
                    logger.warning(f"⚠️ Skipping invalid JSON badge entry: {ve}")

        logger.info(f"✅ Loaded {len(badges)} valid Google badges from JSON file.")
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"⚠️ Error reading JSON file '{json_path}': {e}")
        return []


def fetch_google_skills_badges(profile_id: str) -> list[dict]:
    """Orchestrates fetching Google Skills badges via API endpoints or local fallbacks."""
    # 1. Primary Strategy: API / Public Profile JSON
    urls = [
        f"https://www.skills.google/public_profiles/{profile_id}.json",
        f"https://api.skills.google/v1/public_profiles/{profile_id}/badges",
    ]

    for url in urls:
        logger.info(f"🔄 Attempting fetch from Google Skills endpoint: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code == 200:
                data = response.json()
                raw_list = data.get("badges", data.get("items", data if isinstance(data, list) else []))
                parsed = []
                for item in raw_list:
                    if isinstance(item, dict):
                        title = item.get("title") or item.get("name") or item.get("badge_title")
                        dt = item.get("earned_at") or item.get("issued_at") or item.get("date")
                        b_id = item.get("id") or generate_badge_id(str(title), str(dt))
                        verify = item.get("verify_url") or item.get("url") or f"https://www.skills.google/public_profiles/{profile_id}"

                        raw_entry = {
                            "id": str(b_id),
                            "title": str(title),
                            "name": str(title),
                            "issuer": "Google",
                            "issuer_name": "Google",
                            "issued_at": dt,
                            "issued_at_date": dt,
                            "date": dt,
                            "image_url": item.get("image_url") or item.get("icon"),
                            "verify_url": verify,
                            "url": verify,
                            "type": item.get("type", "Google Skill Badge"),
                            "verification_type": item.get("type", "Google Skill Badge"),
                            "skills": item.get("skills", [title] if title else ["Google Cloud"]),
                        }
                        try:
                            parsed.append(GoogleBadgeItemModel(**raw_entry).model_dump())
                        except ValidationError:
                            pass
                if parsed:
                    logger.info(f"✅ Successfully retrieved {len(parsed)} badges via API.")
                    return parsed
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Request failed for {url}: {e}")

    # 2. Secondary Strategy: Fallback to local files
    json_candidates = [
        OUTPUT_FILE,
        os.path.join(VALIDATION_DIR, OUTPUT_FILENAME),
        OUTPUT_FILENAME,
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for cand in json_candidates:
        if os.path.exists(cand):
            local_badges = parse_google_badges_from_json(cand)
            if local_badges:
                return local_badges

    logger.error("❌ Failed to acquire Google Skills badges from network or local files.")
    return []


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
        issuer = str(b.get("issuer") or "Google").strip()
        v_type = str(b.get("type") or "Google Skill Badge").strip()

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

    index_raw = f"{RAW_BASE_DEFAULT}/google-skills-index.md"
    latest_slice_raw = ""

    marker_start = "<!-- GOOGLE_SKILLS_START -->"
    marker_end = "<!-- GOOGLE_SKILLS_END -->"

    profile_url = f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}"

    readme_lines = [
        "### Google Skills Credentials",
        "",
        f"**Public Profile:** [Verify Google Skills Profile]({profile_url})",
        "",
        f"**Total Portfolio Credentials:** {total_count}",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/google-skills-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({{latest_slice_raw}}), or [Monolithic File](./archives/google-skills-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    latest_slice = generate_platform_archive(
        platform_prefix="google-skills",
        platform_name="Google Skills Credentials",
        table_headers=["Date Earned", "Credential Name", "Issuer", "Verification Type"],
        table_alignments=[":---:", ":---", ":---", ":---:"],
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=marker_start,
        marker_end=marker_end,
    )

    if latest_slice:
        latest_slice_raw = f"{RAW_BASE_DEFAULT}/{latest_slice}"
        # Update the readme_lines with the actual latest slice URL
        for i, line in enumerate(readme_lines):
            if "{latest_slice_raw}" in line:
                readme_lines[i] = line.replace("{latest_slice_raw}", latest_slice_raw)
                break
        # Re-write README with the updated link
        if os.path.exists("README.md"):
            with open("README.md", "r", encoding="utf-8") as f:
                content = f.read()
            if marker_start in content and marker_end in content:
                before = content.split(marker_start)[0]
                after = content.split(marker_end)[1]
                new_block = "\n".join(readme_lines) + "\n"
                new_content = f"{before}{marker_start}\n{new_block}{marker_end}{after}"
                safe_write_file("README.md", new_content)


# ==============================================================================
# PIPELINE ORCHESTRATOR
# ==============================================================================

def main():
    logger.info("Starting Google Skills API/Scraping Pipeline with Pydantic & Loss Guards...")

    if os.path.exists(VALIDATION_DIR) and not os.path.isdir(VALIDATION_DIR):
        logger.warning(f"⚠️ '{VALIDATION_DIR}' exists as a regular file. Removing it to convert into a directory.")
        os.remove(VALIDATION_DIR)

    os.makedirs(VALIDATION_DIR, exist_ok=True)

    raw_badges = fetch_google_skills_badges(GOOGLE_PROFILE_ID)

    unique_badges = []
    seen = set()

    for badge in raw_badges:
        dedup_key = badge.get("id") or f"{badge.get('title')}-{badge.get('issued_at')}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_badges.append(badge)

    # 1. Anomaly & Loss Guard Assertion - Content-Aware
    #    Uses stable badge IDs and content hashes to detect replacement/modification
    #    even when total badge count remains stable.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=unique_badges,
                platform="google-skills",
                id_field="id",  # Google Skills badges have stable 'id' field
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

    # 2. Pydantic Payload Validation & File Dump strictly inside for_validation/
    payload_dict = {
        "profile_id": GOOGLE_PROFILE_ID,
        "total_count": len(unique_badges),
        "badges": unique_badges,
    }

    try:
        validated_payload = GoogleSkillsArchivePayloadModel(**payload_dict)

        # Save output JSON file inside for_validation directory ONLY
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(validated_payload.model_dump_json(indent=2))

        logger.info(f"🎉 Persistence complete: '{OUTPUT_FILE}' updated ({len(unique_badges)} badges).")
    except ValidationError as ve:
        logger.error(f"❌ Root Payload Validation Error: {ve}")
        sys.exit(1)

    # 3. Build Markdown Archives
    build_archives_and_readme(unique_badges)
    logger.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
