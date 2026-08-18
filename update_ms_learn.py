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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

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

# Retired credentials registry mapping
RETIRED_URLS_FILE = "retired_urls.json"

def load_retired_rules(platform: str) -> list[dict[str, Any]]:
    """Load retired credential rules for a platform from the mapping file.
    Supports both legacy string list format and structured rule objects.
    """
    if not os.path.exists(RETIRED_URLS_FILE):
        logger.debug(f"Retired URLs file not found: {RETIRED_URLS_FILE}")
        return []
    try:
        with open(RETIRED_URLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get(platform, [])
        rules = []
        for entry in entries:
            if isinstance(entry, str):
                rules.append({"id": entry, "match_type": "url", "url": entry})
            elif isinstance(entry, dict) and entry.get("id"):
                rules.append(entry)
        logger.info(f"Loaded {len(rules)} retired rule(s) for {platform}")
        return rules
    except Exception as e:
        logger.warning(f"⚠️ Could not load retired rules for {platform}: {e}")
        return []

def mark_retired(
    items: list[dict],
    retired_rules: list[dict[str, Any]],
    url_field: str | list[str] = "url",
    id_fields: list[str] | None = None,
    retired_field: str = "retired",
    normalize_url: Callable[[str], str] | None = None,
) -> tuple[int, int]:
    """Mark items as retired if their ID, UID, or URL matches known retired rules.
    Returns (total_checked, total_marked).
    """
    if not retired_rules:
        return len(items), 0
    url_fields = [url_field] if isinstance(url_field, str) else url_field
    search_id_fields = id_fields or ["id", "uid", "sourceUid", "credentialId", "learningPathUid", "learning_path_uid", "license"]
    marked = 0

    for item in items:
        if item.get(retired_field, False):
            continue

        # Extract values for item
        item_url = None
        for field in url_fields:
            raw_url = item.get(field)
            if raw_url:
                item_url = normalize_url(raw_url) if normalize_url else str(raw_url).strip()
                break

        item_ids = set()
        for field in search_id_fields:
            val = item.get(field)
            if val:
                s_val = str(val).strip()
                item_ids.add(s_val)
                if normalize_url:
                    item_ids.add(normalize_url(s_val))

        # Check against rules
        is_retired = False
        matched_rule = None
        for rule in retired_rules:
            rule_id = str(rule.get("id", "")).strip()
            rule_url = rule.get("url")
            rule_norm_url = normalize_url(rule_url) if (rule_url and normalize_url) else rule_url

            # 1. Match by ID / UID / License
            if rule_id in item_ids:
                is_retired = True
                matched_rule = rule
                break

            # 2. Match by normalized URL
            if item_url and (rule_id == item_url or (rule_norm_url and item_url == rule_norm_url)):
                is_retired = True
                matched_rule = rule
                break

        if is_retired:
            item[retired_field] = True
            if matched_rule:
                if matched_rule.get("reason"):
                    item["retirement_reason"] = matched_rule["reason"]
                if matched_rule.get("retired_at"):
                    item["retired_at"] = matched_rule["retired_at"]
            marked += 1
            logger.info(f"🏷️  Marked as retired: {item.get('title') or item.get('name') or item.get('id') or 'unknown'}")

    logger.info(f"Retired check: {len(items)} items checked, {marked} marked as retired")
    return len(items), marked

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ms_learn_updater")

# Configuration Constants
JSON_PATH = os.getenv("JSON_PATH", os.path.join("data", "microsoft-learn.json"))
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "microsoft-learn"
PLATFORM_NAME = "Microsoft Learn"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")
MS_LEARN_PROFILE_ID = os.getenv("MS_LEARN_PROFILE_ID") or "vojislavmiloradovic"
MS_LEARN_PROFILE_URL = f"https://learn.microsoft.com/en-us/users/{MS_LEARN_PROFILE_ID}/"

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
    # Remove trailing " program/" and any spaces that break URLs
    clean = re.sub(r'\s+program/?$', '', clean)
    clean = clean.replace(' ', '')
    if not clean:
        return ""
    # Handle learning path UID format: learn.viva-glint-360-feedback -> https://learn.microsoft.com/en-us/training/paths/viva-glint-360-feedback
    if clean.startswith("learn."):
        path_part = clean[6:]  # Remove "learn." prefix
        clean = f"https://learn.microsoft.com/en-us/training/paths/{path_part}"
    elif not clean.startswith("http"):
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
    retired: bool = Field(False)

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
    retired: bool = Field(False)

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

    # 2. Retired URL / Identity detection (Microsoft Learn)
    retired_rules = load_retired_rules("microsoft-learn")
    if retired_rules:
        _, marked = mark_retired(validated_achievements, retired_rules, url_field="url")
        if marked > 0:
            logger.info(f"📝 Updated {marked} achievement(s) with retired status")

    # 3. Execute Content-Aware Loss Guard against stored baseline
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
            status = cred_model.credentialStatus
            if cred_model.retired:
                status += " ⚠️ *Content retired*"
            verifiable_list.append(
                f"- **{name}** (Credential ID: `{cred_model.credentialId}` | Earned: {cred_model.awardedOn} | Status: {status})"
            )
        except ValidationError as ve:
            logger.warning(f"⚠️ Skipping invalid verifiable credential: {ve}")

    # Also check verifiable credentials against retired rules
    if retired_rules:
        _, marked = mark_retired(user_creds, retired_rules, url_field="sourceUid", id_fields=["sourceUid", "credentialId"], retired_field="retired")
        # Note: verifiable credentials use sourceUid, not url field
        if marked > 0:
            logger.info(f"📝 Updated {marked} verifiable credential(s) with retired status")

    # Also check learning paths against retired rules
    if retired_rules:
        _, marked = mark_retired(learning_paths, retired_rules, url_field=["url", "learningPathUid", "learning_path_uid", "learningPathId"], id_fields=["learningPathUid", "learning_path_uid", "learningPathId"], retired_field="retired", normalize_url=format_verify_url)
        if marked > 0:
            logger.info(f"📝 Updated {marked} learning path(s) with retired status")

    # Propagate retired status from learning paths to matching achievements
    # Build set of retired URLs from learning paths (normalized)
    retired_lp_urls = set()
    for lp in learning_paths:
        if lp.get("retired"):
            for field in ["url", "learningPathUid", "learning_path_uid", "learningPathId"]:
                raw = lp.get(field)
                if raw:
                    retired_lp_urls.add(format_verify_url(raw))
                    break

    # Mark matching achievements as retired
    if retired_lp_urls:
        ach_marked = 0
        for ach in validated_achievements:
            ach_url = format_verify_url(ach.get("url"))
            if ach_url and ach_url in retired_lp_urls and not ach.get("retired", False):
                ach["retired"] = True
                ach_marked += 1
                logger.info(f"🏷️  Propagated retired to achievement: {ach.get('title') or ach.get('id')}")
        if ach_marked > 0:
            logger.info(f"📝 Propagated retired status to {ach_marked} achievement(s)")

    # Persist full data with retired flags to for_validation for link checker
    validation_dir = "for_validation"
    os.makedirs(validation_dir, exist_ok=True)
    validation_file = os.path.join(validation_dir, "microsoft-learn.json")
    payload = {
        "platform": "microsoft-learn",
        "total_achievements": len(validated_achievements),
        "total_learning_paths": len(learning_paths),
        "total_modules": len(modules),
        "total_completed_units": len(completed_units),
        "achievements": validated_achievements,
        "learning_paths": learning_paths,
        "modules": modules,
        "completed_units": completed_units,
        "verifiable_credentials": user_creds,
    }
    try:
        with open(validation_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Full data persisted: '{validation_file}'")
    except Exception as e:
        logger.warning(f"⚠️ Could not persist full data: {e}")

    # Format table rows for archiver
    formatted_rows = []
    for item in sorted_achievements:
        title = item.get("title", "Completed Module").replace("|", "\\|")
        cat = str(item.get("category", "module")).title()
        date = item.get("grantedOn", "N/A")
        verify_url = format_verify_url(item.get("url"))
        retired = item.get("retired", False)
        verify_cell = f"[Verify]({verify_url})" if verify_url else "N/A"
        if retired:
            verify_cell += " ⚠️ *Content retired*"
        row_text = f"| **{title}** | {cat} | {date} | {verify_cell} |"
        formatted_rows.append((row_text, date))

    # Construct README Summary Lines
    md = [
        "### Microsoft Learn Summary",
        "",
        f"**Public Profile:** [Verify Microsoft Learn Profile]({MS_LEARN_PROFILE_URL})",
        "",
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
    LATEST_SLICE_NORMAL = ""
    LATEST_SLICE_RAW = ""

    md.append("### Recent Achievements & Completed Badges")
    md.append(
        f"Showing latest 10 of {format_num(len(sorted_achievements))} achievements. View full dataset via [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic Complete File](./archives/{monolith_filename}).\n"
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
        latest_slice = generate_platform_archive(
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

        if latest_slice:
            LATEST_SLICE_NORMAL = "./archives/" + latest_slice
            LATEST_SLICE_RAW = RAW_BASE_DEFAULT + "/" + latest_slice
            for i, line in enumerate(md):
                if "{LATEST_SLICE_NORMAL}" in line:
                    md[i] = line.replace("{LATEST_SLICE_NORMAL}", LATEST_SLICE_NORMAL)
                    md[i] = md[i].replace("{LATEST_SLICE_RAW}", LATEST_SLICE_RAW)
                    break
            if os.path.exists("README.md"):
                with open("README.md", "r", encoding="utf-8") as f:
                    readme_content = f.read()
                if MARKER_START in readme_content and MARKER_END in readme_content:
                    before = readme_content.split(MARKER_START)[0]
                    after = readme_content.split(MARKER_END)[1]
                    new_block = "\n".join(md) + "\n"
                    new_content = before + MARKER_START + "\n" + new_block + MARKER_END + after
                    safe_write_file("README.md", new_content)
        logger.info(f"🎉 Microsoft Learn pipeline complete ({len(sorted_achievements)} items archived).")
    else:
        logger.error("❌ Archiver module helper not available. Skipping markdown generation.")


if __name__ == "__main__":
    main()
