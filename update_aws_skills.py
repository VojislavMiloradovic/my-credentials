"""
update_aws_skills.py
--------------------
Pipeline for updating AWS Skill Builder credentials from CSV exports, local JSON data, or API/HTML responses.
Includes CSV/JSON parsing, Pydantic schema validation, date coercion,
data loss / anomaly guards, and integration with the repository archiver.
"""

import csv
import glob
import hashlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

# Layer Manifest Integration
try:
    from layer_manifest import get_layer_def, get_platform_layers, load_manifest
except ImportError:
    get_platform_layers = None
    get_layer_def = None
    load_manifest = None

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


def generate_layer_metadata(platform_key: str) -> dict[str, Any]:
    """Generate layer metadata from manifest for a platform."""
    if not load_manifest:
        return {}
    try:
        manifest = load_manifest()
        if platform_key not in manifest.platforms:
            return {}

        platform = manifest.platforms[platform_key]

        # Build layer metadata
        layer_metadata = {}
        for layer_name in ("L0_raw", "L1_normalized", "L2_published", "L3_display"):
            layer_def = getattr(platform, layer_name, None)
            if not layer_def:
                continue

            layer_info = {
                "source": layer_def.source,
                "source_layer": layer_def.source_layer,
                "description": layer_def.description,
                "retired_handling": layer_def.retired_handling,
            }

            if layer_def.transform:
                layer_info["transform"] = layer_def.transform.type
                if layer_def.transform.params:
                    layer_info["transform_params"] = layer_def.transform.params

            if layer_def.transforms:
                layer_info["transforms"] = {
                    k: v.type for k, v in layer_def.transforms.items()
                }

            if layer_def.output_records:
                layer_info["output_records"] = layer_def.output_records

            if layer_def.output_streams:
                layer_info["output_streams"] = layer_def.output_streams

            if layer_def.artifacts:
                layer_info["artifacts"] = layer_def.artifacts

            if layer_def.metrics:
                layer_info["metrics"] = layer_def.metrics

            layer_metadata[layer_name] = layer_info

        return layer_metadata
    except Exception as e:
        logger.warning(f"Could not generate layer metadata for {platform_key}: {e}")
        return {}


# Retired credentials registry mapping
RETIRED_URLS_FILE = "retired_urls.json"


def load_retired_rules(platform: str) -> list[dict[str, Any]]:
    """Load retired credential rules for a platform from the mapping file."""
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
    url_field: str = "verify_url",
    id_fields: list[str] | None = None,
    retired_field: str = "retired",
) -> tuple[int, int]:
    """Mark items as retired if their ID or URL matches known retired rules."""
    if not retired_rules:
        return len(items), 0
    search_id_fields = id_fields or ["id", "title", "verify_url", "url"]
    marked = 0
    for item in items:
        if item.get(retired_field, False):
            continue

        item_url = str(item.get(url_field, "")).strip() if item.get(url_field) else None
        item_ids = {str(item.get(f)).strip() for f in search_id_fields if item.get(f)}

        is_retired = False
        matched_rule = None
        for rule in retired_rules:
            rule_id = str(rule.get("id", "")).strip()
            rule_url = str(rule.get("url", "")).strip() if rule.get("url") else None

            if rule_id in item_ids or (
                item_url and (rule_id == item_url or rule_url == item_url)
            ):
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
            logger.info(
                f"🏷️  Marked as retired: {item.get('title') or item.get('id') or 'unknown'}"
            )

    logger.info(
        f"Retired check: {len(items)} items checked, {marked} marked as retired"
    )
    return len(items), marked


# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aws_skills_updater")

# Configuration Constants & Canonical Paths
AWS_PROFILE_USER = os.getenv("AWS_PROFILE_USER", "vojislavmiloradovic")
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "aws_skill_badges.json"
OUTPUT_FILE = os.getenv("OUTPUT_FILE", os.path.join(VALIDATION_DIR, OUTPUT_FILENAME))
ARCHIVE_DIR = "archives"
README_PATH = "README.md"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, "aws-skills-complete.md")

MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

# Data Loss / Anomaly Guard Tolerances
MAX_ALLOWED_DATA_LOSS_PCT = (
    0.15  # Fail if new badge count drops >15% below stored baseline
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


class AwsBadgeItemModel(BaseModel):
    """Normalized schema for processed AWS Skill Builder badge entity validated before archive output."""

    id: str = Field(..., min_length=1, description="Unique badge ID or hash")
    title: str = Field(
        ..., min_length=1, description="AWS achievement or credential title"
    )
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field("Amazon Web Services", description="Issuing body")
    issuer_name: str = Field(
        "Amazon Web Services", description="Issuer alias for compatibility"
    )
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Badge image URL")
    verify_url: str | None = Field(
        None, description="Public verification or detail link"
    )
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field(
        "AWS Skill Builder Badge", description="Credential classification type"
    )
    verification_type: str = Field(
        "AWS Skill Builder Badge", description="Alias for verification category"
    )
    skills: list[str] = Field(default_factory=list, description="Associated skills")
    retired: bool = Field(
        False, description="Whether the content has been retired by the platform"
    )

    @field_validator("issued_at", "issued_at_date", "date", mode="before")
    @classmethod
    def validate_and_coerce_dates(cls, val: Any) -> str | None:
        return normalize_date_string(val)

    @field_validator("skills", mode="before")
    @classmethod
    def sanitize_skills_list(cls, val: Any) -> list[str]:
        if isinstance(val, list):
            clean = [
                str(item).strip()
                for item in val
                if isinstance(item, str) and item.strip()
            ]
            return list(dict.fromkeys(clean))
        elif isinstance(val, str) and val.strip():
            return [val.strip()]
        return []


class AwsSkillsArchivePayloadModel(BaseModel):
    """Root model for AWS persistence JSON validation."""

    profile_user: str
    total_count: int = Field(ge=0)
    badges: list[AwsBadgeItemModel]


# ==============================================================================
# ANOMALY & LOSS GUARD ASSERTIONS
# ==============================================================================


class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous archive baseline."""


def get_stored_archive_baseline_count(json_path: str, monolith_path: str) -> int:
    """Evaluates baseline record count from existing JSON or monolith archive markdown."""
    candidate_json_paths = [
        json_path,
        OUTPUT_FILENAME,
        "aws_skills_badges.json",
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for path in candidate_json_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    count = (
                        data.get("total_count", len(data.get("badges", [])))
                        if isinstance(data, dict)
                        else len(data)
                    )
                    if count > 0:
                        return count
            except (json.JSONDecodeError, OSError):
                pass

    if os.path.exists(monolith_path):
        try:
            with open(monolith_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            rows = [
                l
                for l in lines
                if l.strip().startswith("|")
                and not l.strip().startswith("| Date")
                and ":---" not in l
            ]
            if len(rows) > 0:
                return len(rows)
        except OSError:
            pass

    return 0


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    """
    Loss Guard: Compares incoming badge count against stored baseline (JSON or Markdown Monolith).
    Prevents empty or broken fetches from wiping out stored credential records.
    """
    old_count = get_stored_archive_baseline_count(output_file, ARCHIVE_MONOLITH)
    new_count = len(new_badges)

    logger.info(
        f"🛡️ Loss Guard Check: Stored Archive Baseline = {old_count} badges | Incoming Dataset = {new_count} badges."
    )

    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming fetch returned 0 badges, but stored archive baseline contains {old_count}. Aborting sync."
        )

    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming badge count ({new_count}) dropped by {drop_ratio:.1%} "
                f"from baseline ({old_count}). Maximum allowed drop threshold is {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting write."
            )

    logger.info(
        "✅ Loss Guard Assertion Passed: Incoming payload verified against archive baseline."
    )


# ==============================================================================
# CSV & JSON PARSERS / FETCHERS
# ==============================================================================


def generate_badge_id(title: str, date_str: str | None) -> str:
    """Generates a stable identifier for badges lacking explicit IDs."""
    raw = f"aws-skills-{title.strip().lower()}-{date_str or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_aws_badges_from_json(json_path: str) -> list[dict]:
    """Reads and validates existing AWS badge entries directly from local JSON file."""
    if not os.path.exists(json_path):
        return []

    logger.info(f"📄 Reading existing AWS badges from local JSON file: '{json_path}'")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_list = (
            data.get("badges", [])
            if isinstance(data, dict)
            else (data if isinstance(data, list) else [])
        )
        badges = []
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    validated = AwsBadgeItemModel(**item)
                    badges.append(validated.model_dump())
                except ValidationError as ve:
                    logger.warning(f"⚠️ Skipping invalid JSON badge entry: {ve}")

        logger.info(
            f"✅ Loaded {len(badges)} valid AWS badges from JSON file '{json_path}'."
        )
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"⚠️ Error reading JSON file '{json_path}': {e}")
        return []


def locate_aws_csv_file() -> str | None:
    """Locates candidate CSV transcript export files in current directory or data subfolder."""
    env_path = os.getenv("AWS_CSV_FILE") or os.getenv("AWS_CSV_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = [
        os.path.join("data", "aws-training-activity.csv"),
        os.path.join("data", "aws_skills.csv"),
        os.path.join("data", "aws_transcript.csv"),
        "aws-training-activity.csv",
        "aws_skills.csv",
        "aws_transcript.csv",
        "aws_badges.csv",
        "aws.csv",
    ]

    for cand in candidates:
        if os.path.exists(cand):
            return cand

    glob_matches = glob.glob("*aws*.csv") + glob.glob("data/*aws*.csv")
    if glob_matches:
        return glob_matches[0]

    return None


def parse_aws_badges_from_csv(csv_path: str, profile_user: str) -> list[dict]:
    """Parses AWS transcript / badge export CSV files into validated models."""
    logger.info(f"📄 Parsing AWS credentials from CSV file: '{csv_path}'")
    badges = []
    profile_url = f"https://skillsprofile.skillbuilder.aws/user/{profile_user}"

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_idx = -1
    for idx, line in enumerate(lines):
        if line.strip().startswith("Title,") or "Title,Type" in line:
            header_idx = idx
            break

    if header_idx == -1:
        logger.error(
            "❌ Could not locate CSV header row starting with 'Title,Type,...'"
        )
        return []

    reader = csv.DictReader(lines[header_idx:])
    for row in reader:
        row_lower = {
            str(k).strip().lower(): str(v).strip() for k, v in row.items() if k
        }

        title = (
            row_lower.get("title")
            or row_lower.get("course title")
            or row_lower.get("badge title")
            or row_lower.get("name")
            or row_lower.get("achievement")
            or row_lower.get("learning object title")
        )

        if not title:
            continue

        raw_date = (
            row_lower.get("completed on")
            or row_lower.get("date")
            or row_lower.get("completed date")
            or row_lower.get("completion date")
            or row_lower.get("date earned")
            or row_lower.get("earned date")
            or row_lower.get("issued at")
            or row_lower.get("date completed")
        )

        if not raw_date or raw_date == "-":
            raw_date = row_lower.get("started on") or row_lower.get("enrolled on")

        if raw_date == "-":
            raw_date = None

        c_type = (
            row_lower.get("type")
            or row_lower.get("achievement type")
            or row_lower.get("training type")
            or "AWS Skill Builder Badge"
        )

        verify_url = (
            row_lower.get("url")
            or row_lower.get("badge url")
            or row_lower.get("verification url")
            or row_lower.get("link")
            or profile_url
        )

        image_url = (
            row_lower.get("image url")
            or row_lower.get("image")
            or row_lower.get("icon")
        )
        badge_id = row_lower.get("id") or generate_badge_id(title, raw_date)

        raw_entry = {
            "id": str(badge_id),
            "title": title,
            "name": title,
            "issuer": "Amazon Web Services",
            "issuer_name": "Amazon Web Services",
            "issued_at": raw_date,
            "issued_at_date": raw_date,
            "date": raw_date,
            "image_url": image_url,
            "verify_url": verify_url,
            "url": verify_url,
            "type": c_type,
            "verification_type": c_type,
            "skills": [title],
        }

        try:
            validated_model = AwsBadgeItemModel(**raw_entry)
            badges.append(validated_model.model_dump())
        except ValidationError as ve:
            logger.warning(
                f"⚠️ Anomaly Guard: Skipping malformed CSV row entry '{title}': {ve}"
            )

    logger.info(f"✅ Extracted {len(badges)} valid AWS badge records from CSV.")
    return badges


def fetch_aws_skills_badges(profile_user: str) -> list[dict]:
    """Orchestrates ingestion prioritizing CSV exports, local JSON files, then API endpoints."""
    # 1. Primary Strategy: Local CSV File Export
    csv_file = locate_aws_csv_file()
    if csv_file:
        parsed_csv_badges = parse_aws_badges_from_csv(csv_file, profile_user)
        if parsed_csv_badges:
            return parsed_csv_badges

    # 2. Secondary Strategy: Validation or Local JSON File
    json_candidates = [
        OUTPUT_FILE,
        os.path.join(VALIDATION_DIR, OUTPUT_FILENAME),
        OUTPUT_FILENAME,
        "aws_skills_badges.json",
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for json_file in json_candidates:
        if os.path.exists(json_file):
            json_badges = parse_aws_badges_from_json(json_file)
            if json_badges:
                return json_badges

    # 3. Tertiary Strategy: Network API / Web Endpoints
    urls = [
        f"https://skillsprofile.skillbuilder.aws/user/{profile_user}",
        f"https://skillsprofile.skillbuilder.aws/api/user/{profile_user}/badges",
    ]

    for url in urls:
        logger.info(f"🔄 Attempting fetch from endpoint: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code == 200:
                ct = response.headers.get("Content-Type", "")
                if "application/json" in ct:
                    data = response.json()
                    raw_list = (
                        data
                        if isinstance(data, list)
                        else data.get("badges", data.get("items", []))
                    )
                    parsed = []
                    for item in raw_list:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("name")
                            dt = item.get("issued_at") or item.get("earnedDate")
                            b_id = item.get("id") or generate_badge_id(
                                str(title), str(dt)
                            )
                            entry = {
                                "id": b_id,
                                "title": title or "AWS Badge",
                                "name": title or "AWS Badge",
                                "issuer": "Amazon Web Services",
                                "issuer_name": "Amazon Web Services",
                                "issued_at": dt,
                                "issued_at_date": dt,
                                "date": dt,
                                "image_url": item.get("image_url"),
                                "verify_url": item.get("verify_url")
                                or f"https://skillsprofile.skillbuilder.aws/user/{profile_user}",
                                "url": item.get("verify_url"),
                                "type": "AWS Skill Builder Badge",
                                "verification_type": "AWS Skill Builder Badge",
                                "skills": [title] if title else ["AWS"],
                            }
                            try:
                                parsed.append(AwsBadgeItemModel(**entry).model_dump())
                            except ValidationError:
                                pass
                    if parsed:
                        logger.info(
                            f"✅ Successfully fetched {len(parsed)} badges via JSON API endpoint."
                        )
                        return parsed
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Request failed for {url}: {e}")

    logger.error(
        "❌ Failed to acquire AWS Skill Builder badges from CSV, local JSON, or network endpoints."
    )
    return []


# ==============================================================================
# ARCHIVE BUILDER & README GENERATION
# ==============================================================================

CLOUD_QUEST_STATS = {
    "Role": "Cloud Practitioner / Generative AI Practitioner",
    "Builder Level": 12,
    "Reputation Level": 95,
    "Total Solutions Built": 20,
    "Pets Unlocked": 17,
    "Vehicles Unlocked": 2,
}


def build_archives_and_readme(badges: list[dict]) -> None:
    """Invokes archiver helper to generate markdown chunk files and update README.md."""
    if not generate_platform_archive:
        logger.error(
            "❌ Archiver module helper not available. Skipping markdown generation."
        )
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
        issuer = str(b.get("issuer") or "Amazon Web Services").strip()
        v_type = str(b.get("type") or "AWS Skill Builder Badge").strip()
        retired = b.get("retired", False)

        for skill in b.get("skills", []):
            if isinstance(skill, str) and skill.strip():
                all_skills.add(skill.strip())

        title_clean = (
            title.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        )
        issuer_clean = (
            issuer.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        )
        v_type_clean = (
            v_type.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
        )

        name_cell = f"[{title_clean}]({verify_url})" if verify_url else title_clean
        if retired:
            name_cell += " ⚠️ *Content retired*"
        row_text = f"| {date_str} | {name_cell} | {issuer_clean} | {v_type_clean} |"
        formatted_rows.append((row_text, date_str))

    total_count = len(sorted_badges)
    total_skills = len(all_skills)

    index_raw = f"{RAW_BASE_DEFAULT}/aws-skills-index.md"
    LATEST_SLICE_NORMAL = ""
    LATEST_SLICE_RAW = ""

    marker_start = "<!-- AWS_SKILLS_START -->"
    marker_end = "<!-- AWS_SKILLS_END -->"

    profile_url = f"https://skillsprofile.skillbuilder.aws/user/{AWS_PROFILE_USER}"

    cq_lines = [
        "#### AWS Cloud Quest Summary",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
    ]
    for key, value in CLOUD_QUEST_STATS.items():
        cq_lines.append(f"| **{key}** | {value} |")
    cq_lines.append("")

    readme_lines = [
        "### AWS Skill Builder Credentials",
        "",
        f"**Public Profile:** [Verify AWS Skill Builder Profile]({profile_url})",
        "",
        f"**Total Portfolio Credentials:** {total_count}",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
    ]

    readme_lines.extend(cq_lines)

    readme_lines.extend(
        [
            "#### Latest Earned Credentials",
            "",
            f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/aws-skills-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic File](./archives/aws-skills-complete.md).",
            "",
            "| Date Earned | Credential Name | Issuer | Verification Type |",
            "| :---: | :--- | :--- | :---: |",
        ]
    )

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    latest_slice = generate_platform_archive(
        platform_prefix="aws-skills",
        platform_name="AWS Skill Builder Credentials",
        table_headers=["Date Earned", "Credential Name", "Issuer", "Verification Type"],
        table_alignments=[":---:", ":---", ":---", ":---:"],
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=marker_start,
        marker_end=marker_end,
    )

    if latest_slice:
        LATEST_SLICE_NORMAL = f"./archives/{latest_slice}"
        LATEST_SLICE_RAW = f"{RAW_BASE_DEFAULT}/{latest_slice}"
        for i, line in enumerate(readme_lines):
            if "{LATEST_SLICE_NORMAL}" in line:
                readme_lines[i] = line.replace(
                    "{LATEST_SLICE_NORMAL}", LATEST_SLICE_NORMAL
                )
                readme_lines[i] = readme_lines[i].replace(
                    "{LATEST_SLICE_RAW}", LATEST_SLICE_RAW
                )
                break
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
    logger.info("Starting AWS Skill Builder Pipeline with Pydantic & Loss Guards...")

    # Safe directory initialization
    if os.path.exists(VALIDATION_DIR) and not os.path.isdir(VALIDATION_DIR):
        logger.warning(
            f"⚠️ '{VALIDATION_DIR}' exists as a file. Removing it to create a directory."
        )
        os.remove(VALIDATION_DIR)

    os.makedirs(VALIDATION_DIR, exist_ok=True)

    raw_badges = fetch_aws_skills_badges(AWS_PROFILE_USER)

    unique_badges = []
    seen = set()

    for badge in raw_badges:
        dedup_key = badge.get("id") or f"{badge.get('title')}-{badge.get('issued_at')}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_badges.append(badge)

    # 1. Execute Content-Aware Loss Guard check against previous baseline
    #    Uses stable badge IDs and content hashes to detect replacement/modification
    #    even when total badge count remains stable.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=unique_badges,
                platform="aws-skills",
                id_field="id",  # AWS badges have stable 'id' field
                fail_on_warn=True,  # SET TO False TO DISABLE FAILURES (comment out raise in loss_guard.py)
            )
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)
    else:
        logger.warning(
            "⚠️ Content-aware loss guard unavailable, falling back to count-only check"
        )
        try:
            execute_data_loss_guard(unique_badges, OUTPUT_FILE)
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)

    # 2. Retired URL / Identity detection
    retired_rules = load_retired_rules("aws-skills")
    if retired_rules:
        _, marked = mark_retired(unique_badges, retired_rules, url_field="verify_url")
        if marked > 0:
            logger.info(f"📝 Updated {marked} badge(s) with retired status")

        # 3. Validate Root Payload with Pydantic Schema & Save strictly inside for_validation/
        layer_metadata = generate_layer_metadata("aws-skills")
        payload_dict = {
            "profile_user": AWS_PROFILE_USER,
            "total_count": len(unique_badges),
            "badges": unique_badges,
            "_layer_metadata": layer_metadata,
        }

        try:
            validated_payload = AwsSkillsArchivePayloadModel(**payload_dict)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write(validated_payload.model_dump_json(indent=2))
            logger.info(
                f"🎉 Persistence complete: '{OUTPUT_FILE}' updated safely ({len(unique_badges)} badges)."
            )
        except ValidationError as ve:
            logger.error(f"❌ Root Payload Validation Error: {ve}")
            sys.exit(1)

        # Generate and save baseline fingerprints for L1_normalized (badges)
        if execute_content_loss_guard:
            try:
                execute_content_loss_guard(
                    unique_badges,
                    platform="aws-skills",
                    id_field="id",
                    fail_on_warn=False,
                )
                logger.info("📋 Baseline fingerprints updated for aws-skills")
            except Exception as e:
                logger.warning(f"⚠️ Could not update baseline: {e}")

        # 4. Build markdown archives and update README
        build_archives_and_readme(unique_badges)
    logger.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
