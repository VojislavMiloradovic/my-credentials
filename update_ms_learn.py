"""
update_ms_learn.py
-------------------------
Pipeline for updating Microsoft Learn credentials, verifiable skills, and completed achievements.
Reads manually exported JSON dumps from `data/microsoft-learn.json`, applies Pydantic models,
enforces Data Loss Guards, and delegates markdown archiving to the archiver module.
"""

import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

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
logger = logging.getLogger("ms_learn_updater")

# Configuration Constants
JSON_PATH = os.getenv("JSON_PATH", os.path.join("data", "microsoft-learn.json"))
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "microsoft-learn"
PLATFORM_NAME = "Microsoft Learn"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")

MARKER_START = "<!-- MS_LEARN_START -->"
MARKER_END = "<!-- MS_LEARN_END -->"

MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Guard threshold for dataset drop protection


# ==============================================================================
# HELPER FUNCTIONS & FORMATTERS
# ==============================================================================

def format_num(val: Any) -> str:
    """Formats numbers with comma separators."""
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "0"


def format_verify_url(raw_url: str | None) -> str:
    """Ensures verification links use complete, localized Microsoft Learn URLs."""
    if not raw_url or not isinstance(raw_url, str):
        return ""
    clean = raw_url.strip()
    if not clean:
        return ""
    if not clean.startswith("http"):
        if clean.startswith("/"):
            clean = f"https://learn.microsoft.com/en-us{clean}"
        else:
            clean = f"https://learn.microsoft.com/en-us/{clean}"
    elif "learn.microsoft.com/training/" in clean:
        clean = clean.replace("learn.microsoft.com/training/", "learn.microsoft.com/en-us/training/")
    return clean


def clean_uid(uid: str | None) -> str:
    """Cleans up internal source UIDs into readable titles."""
    if not uid:
        return ""
    parts = uid.replace("applied-skill.", "").replace("learn.wwl.", "").split("-")
    return " ".join(parts).title()


def clean_iso_date(raw_date_str: Any) -> str:
    """Normalizes ISO timestamps to YYYY-MM-DD."""
    if not raw_date_str or not isinstance(raw_date_str, str):
        return "N/A"
    clean = raw_date_str.split("T")[0].strip()
    match = re.search(r"^\d{4}-\d{2}(-\d{2})?", clean)
    if match:
        return match.group(0)
    return clean if clean else "N/A"


def parse_date(x: dict) -> datetime:
    """Parses date string into a timezone-aware datetime for accurate sorting."""
    min_date = datetime.min.replace(tzinfo=UTC)
    if not x or not isinstance(x, dict):
        return min_date
    date_str = x.get("grantedOn") or x.get("date", "")
    if not date_str:
        return min_date
    try:
        clean_str = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", str(date_str))
        if "." in clean_str:
            base, frac = clean_str.split(".")
            clean_str = f"{base}.{frac[:6].ljust(6, '0')}"
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return min_date


def resolve_level(xp_profile: dict, xp_data: dict, total_xp: Any) -> str:
    """Resolves student learning level from user XP metrics."""
    for source in [xp_profile, xp_data]:
        if not isinstance(source, dict):
            continue
        level_val = source.get("level") or source.get("currentLevel")
        if isinstance(level_val, dict):
            num = level_val.get("levelNumber") or level_val.get("number")
            if num is not None:
                return str(num)
        elif level_val is not None and str(level_val).isdigit() and int(level_val) > 0:
            return str(level_val)

    try:
        xp_int = int(total_xp)
        if xp_int >= 5000000:
            return "20"
    except (ValueError, TypeError):
        pass

    return "20"


# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================

class MSAchievementModel(BaseModel):
    """Schema validating individual Microsoft Learn badges/trophies."""
    id: str = Field(min_length=1)
    title: str = Field("Completed Module", min_length=1)
    category: str = Field("module")
    grantedOn: str = Field("N/A")
    url: str | None = Field(None)

    @field_validator("grantedOn", mode="before")
    @classmethod
    def validate_granted_on(cls, val: Any) -> str:
        return clean_iso_date(val)

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, val: Any) -> str:
        if not val or not isinstance(val, str):
            return "module"
        return val.strip()


class MSVerifiableCredentialModel(BaseModel):
    """Schema validating Verifiable Applied Skills and Microsoft Credentials."""
    credentialId: str = Field("N/A")
    sourceUid: str = Field("")
    awardedOn: str = Field("N/A")
    credentialStatus: str = Field("Active")

    @field_validator("awardedOn", mode="before")
    @classmethod
    def validate_awarded_on(cls, val: Any) -> str:
        return clean_iso_date(val)


# ==============================================================================
# MAIN PIPELINE EXECUTION
# ==============================================================================

def get_stored_archive_baseline_count() -> int:
    """Evaluates baseline record count from existing monolith markdown archive."""
    if os.path.exists(ARCHIVE_MONOLITH):
        try:
            with open(ARCHIVE_MONOLITH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            rows = [
                l for l in lines
                if l.strip().startswith("|")
                and not l.strip().startswith("| Achievement Title")
                and ":---" not in l
            ]
            if rows:
                return len(rows)
        except OSError:
            pass
    return 0


def execute_data_loss_guard(new_achievements: list[dict]) -> None:
    """Loss Guard comparison against stored baseline count."""
    old_count = get_stored_archive_baseline_count()
    new_count = len(new_achievements)

    logger.info(f"���🛡��️ Loss Guard Check: Stored Archive Baseline = {old_count:,} items | Incoming Dataset = {new_count:,} items.")

    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming export returned 0 achievements, but baseline contains {old_count}. Aborting sync."
        )

    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming achievement count ({new_count}) dropped by {drop_ratio:.1%} "
                f"from baseline ({old_count}). Threshold: {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting."
            )

    logger.info("��✅ Loss Guard Assertion Passed: Incoming dataset verified.")


def main():
    logger.info("Starting Microsoft Learn Profile Pipeline...")

    if not os.path.exists(JSON_PATH):
        logger.error(f"❌ Error: Export file '{JSON_PATH}' not found!")
        sys.exit(1)

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error parsing JSON file '{JSON_PATH}': {e}")
            sys.exit(1)

    progress = data.get("Progress", {}) or {}
    xp_data = data.get("XP", {}) or {}
    creds = data.get("VerifiableCredentials", {}) or {}

    completed_units = progress.get("completedLearningItems", [])
    learning_paths = progress.get("learningPathPasses", [])
    modules = progress.get("moduleAssessments", [])
    raw_achievements = xp_data.get("achievements", []) or []

    # 1. Validate Achievements with Pydantic
    validated_achievements = []
    for ach in raw_achievements:
        try:
            model = MSAchievementModel(**ach)
            validated_achievements.append(model.model_dump())
        except ValidationError as ve:
            logger.warning(f"⚠️ Skipping invalid achievement entry: {ve}")

    # 2. Execute Content-Aware Loss Guard against stored baseline
    #    Uses stable record IDs (achievement 'id' field) and content hashes
    #    to detect replacement/modification even when total count is stable.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=validated_achievements,
                platform="microsoft-learn",
                id_field="id",  # MS Learn achievements have stable 'id' (e.g., EG94SBRP)
                fail_on_warn=True  # SET TO False TO DISABLE FAILURES (comment out raise in loss_guard.py)
            )
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)
    else:
        logger.warning("⚠️ Content-aware loss guard unavailable, falling back to count-only check")
        # Fallback to original count-based loss guard
        try:
            execute_data_loss_guard(validated_achievements)
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)

    xp_profile = xp_data.get("xp", {}) or {}
    total_xp = "0"
    if isinstance(xp_profile, dict):
        total_xp = xp_profile.get("totalXp", xp_profile.get("xp", "0"))

    current_level = resolve_level(xp_profile, xp_data, total_xp)

    # Count Badges vs Trophies
    badges_count = 0
    trophies_count = 0
    for item in validated_achievements:
        cat = str(item.get("category", "")).lower()
        if "trophy" in cat or "learningpath" in cat:
            trophies_count += 1
        else:
            badges_count += 1

    # Sort reverse-chronologically
    sorted_achievements = sorted(validated_achievements, key=parse_date, reverse=True)

    # 3. Validate Verifiable Credentials
    user_creds = creds.get("userCredentials", []) or []
    verifiable_list = []
    for cred in user_creds:
        try:
            cred_model = MSVerifiableCredentialModel(**cred)
            name = clean_uid(cred_model.sourceUid)
            verifiable_list.append(
                f"- **{name}** (Credential ID: `{cred_model.credentialId}` | Earned: {cred_model.awardedOn} | Status: {cred_model.credentialStatus})"
            )
        except ValidationError as ve:
            logger.warning(f"⚠️ Skipping invalid verifiable credential: {ve}")

    # Format table rows for archiver
    formatted_rows = []
    for item in sorted_achievements:
        title = item.get("title", "Completed Module").replace("|", "\\|")
        cat = str(item.get("category", "module")).title()
        date = item.get("grantedOn", "N/A")
        verify_url = format_verify_url(item.get("url"))
        verify_cell = f"[Verify]({verify_url})" if verify_url else "N/A"
        row_text = f"| **{title}** | {cat} | {date} | {verify_cell} |"
        formatted_rows.append((row_text, date))

    # Construct README Summary Lines
    md = [
        "### Microsoft Learn Summary",
        f"- **Total Experience Points (XP):** {format_num(total_xp)}",
        f"- **Current Learning Level:** Level {current_level}",
        f"- **Badges Earned (Profile):** {format_num(badges_count)}",
        f"- **Trophies Earned (Profile):** {format_num(trophies_count)}",
        f"- **Completed Learning Paths (Active Tracker):** {format_num(len(learning_paths))}",
        f"- **Completed Modules (Active Tracker):** {format_num(len(modules))}",
        f"- **Completed Individual Units:** {format_num(len(completed_units))}\n",
    ]

    if verifiable_list:
        md.append("### Verifiable Applied Skills & Credentials")
        md.extend(verifiable_list)
        md.append("")

    index_filename = f"{PLATFORM_PREFIX}-index.md"
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    index_raw = f"{RAW_BASE_DEFAULT}/{index_filename}"

    md.append("### Recent Achievements & Completed Badges")
    md.append(
        f"Showing latest 10 of {format_num(len(sorted_achievements))} achievements. View full dataset via [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})) or [Monolithic Complete File](./archives/{monolith_filename}).\n"
    )

    for item in sorted_achievements[:10]:
        title = item.get("title", "Completed Module")
        cat = str(item.get("category", "module")).title()
        date = item.get("grantedOn", "N/A")
        verify_url = format_verify_url(item.get("url"))
        verify_str = f" | [Verify Credential]({verify_url})" if verify_url else ""
        md.append(f"- **{title}** ({cat} | Earned: {date}{verify_str})")

    table_headers = ["Achievement Title", "Category", "Date Earned", "Verification Link"]
    table_alignments = [":---", ":---", ":---", ":---"]

    # 4. Trigger Archiver
    if generate_platform_archive:
        generate_platform_archive(
            platform_prefix=PLATFORM_PREFIX,
            platform_name=PLATFORM_NAME,
            table_headers=table_headers,
            table_alignments=table_alignments,
            formatted_rows=formatted_rows,
            readme_lines=md,
            marker_start=MARKER_START,
            marker_end=MARKER_END,
            archive_dir=ARCHIVE_DIR,
            readme_path=README_PATH,
        )
        logger.info(f"🎉 Microsoft Learn pipeline complete ({len(sorted_achievements)} items archived).")
    else:
        logger.error("❌ Archiver module helper not available. Skipping markdown generation.")


if __name__ == "__main__":
    main()
