"""
update_aws_skills.py
--------------------
Pipeline for updating AWS Skill Builder credentials from CSV exports, local JSON data, or API/HTML responses.
Refactored to use PipelineBase (Option 2 Migration).
"""

import csv
import glob
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, ClassVar

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Provenance Integration
from models.provenance import ProvenanceBase, RetrievalMethod, VerificationStatus

# PipelineBase Integration
from pipeline_base import PipelineBase

# ==============================================================================
# MODULE-LEVEL CONSTANTS (for backward compatibility with tests)
# ==============================================================================

AWS_PROFILE_USER = os.getenv("AWS_PROFILE_USER", "vojislavmiloradovic")
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "aws_skill_badges.json"
OUTPUT_FILE = os.path.join(VALIDATION_DIR, OUTPUT_FILENAME)
ARCHIVE_DIR = "archives"
README_PATH = "README.md"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, "aws-skills-complete.md")
MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

RETIRED_URLS_FILE = "retired_urls.json"

CLOUD_QUEST_STATS = {
    "Role": "Cloud Practitioner / Generative AI Practitioner",
    "Builder Level": 12,
    "Reputation Level": 95,
    "Total Solutions Built": 20,
    "Pets Unlocked": 17,
    "Vehicles Unlocked": 2,
}

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


def generate_badge_id(title: str, date_str: str | None) -> str:
    """Generates a stable identifier for badges lacking explicit IDs."""
    raw = f"aws-skills-{title.strip().lower()}-{date_str or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class AwsBadgeItemModel(ProvenanceBase):
    """Normalized schema for processed AWS Skill Builder badge entity validated before archive output."""

    # Platform-specific fields
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

    # Provenance fields with platform-specific defaults
    source_platform: str = Field(
        default="aws-skills", description="Platform identifier"
    )
    source_record_id: str | None = Field(
        None, description="Stable ID from source platform"
    )
    source_url: str | None = Field(None, description="Canonical URL on source platform")
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this record was retrieved",
    )
    last_verified_at: datetime | None = Field(
        None, description="When independently verified"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNKNOWN, description="Verification status"
    )
    source_hash: str | None = Field(
        None, description="Content hash for deduplication/integrity"
    )
    retrieval_method: RetrievalMethod = Field(
        default=RetrievalMethod.EXPORT, description="How retrieved"
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

    @field_validator("verification_status", mode="before")
    @classmethod
    def compute_verification_status(cls, val: Any, info) -> VerificationStatus:
        """Auto-compute verification status from record state."""
        if isinstance(val, VerificationStatus):
            return val
        retired_val = info.data.get("retired", False)
        url_val = info.data.get("verify_url") or info.data.get("url")
        if retired_val:
            return VerificationStatus.RETIRED
        if url_val:
            return VerificationStatus.VERIFIED
        return VerificationStatus.UNKNOWN

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None,
        }
    )


class AwsSkillsArchivePayloadModel(BaseModel):
    """Root model for AWS persistence JSON validation."""

    profile_user: str
    total_count: int = Field(ge=0)
    badges: list[AwsBadgeItemModel]


# ==============================================================================
# CSV & JSON PARSERS / FETCHERS (module-level for backward compat)
# ==============================================================================


def parse_aws_badges_from_json(json_path: str) -> list[dict]:
    """Reads and validates existing AWS badge entries directly from local JSON file."""
    if not os.path.exists(json_path):
        return []

    logging.getLogger("aws_skills").info(
        f"[FILE] Reading existing AWS badges from local JSON file: '{json_path}'"
    )
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
                    badges.append(validated.model_dump(mode="json"))
                except ValidationError as ve:
                    logging.getLogger("aws_skills").warning(
                        f"[WARN] Skipping invalid JSON badge entry: {ve}"
                    )

        logging.getLogger("aws_skills").info(
            f"[OK] Loaded {len(badges)} valid AWS badges from JSON file '{json_path}'."
        )
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logging.getLogger("aws_skills").warning(
            f"[WARN] Error reading JSON file '{json_path}': {e}"
        )
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
    logging.getLogger("aws_skills").info(
        f"[FILE] Parsing AWS credentials from CSV file: '{csv_path}'"
    )
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
        logging.getLogger("aws_skills").error(
            "[FAIL] Could not locate CSV header row starting with 'Title,Type,...'"
        )
        return []

    reader = csv.DictReader(lines[header_idx:])
    skipped = 0

    for row in reader:
        if not row.get("Title") or not row["Title"].strip():
            skipped += 1
            continue

        title = row["Title"].strip()
        badge_type = row.get("Type", "").strip()
        # Try multiple possible date column names from AWS CSV exports
        # Actual column in aws-training-activity.csv is "Completed on"
        earned_date = (
            row.get("Completed on", "")
            or row.get("Earned Date", "")
            or row.get("Date Earned", "")
            or row.get("Completion Date", "")
            or row.get("Completed Date", "")
            or row.get("Earned", "")
            or ""
        ).strip()
        credential_url = row.get("Credential URL", "").strip()
        credential_id = row.get("Credential ID", "") or row.get("ID", "")
        credential_id = credential_id.strip()

        # Normalize the date, with fallback to "2026-01-01" for missing/unparseable dates
        # This maintains backward compatibility and ensures proper sorting
        normalized_date = normalize_date_string(earned_date)
        if not normalized_date:
            normalized_date = "2026-01-01"

        b_id = credential_id or generate_badge_id(title, normalized_date)

        entry = {
            "id": b_id,
            "title": title,
            "name": title,
            "issuer": "Amazon Web Services",
            "issuer_name": "Amazon Web Services",
            "issued_at": normalized_date,
            "issued_at_date": normalized_date,
            "date": normalized_date,
            "image_url": None,
            "verify_url": credential_url or profile_url,
            "url": credential_url,
            "type": badge_type or "AWS Skill Builder Badge",
            "verification_type": badge_type or "AWS Skill Builder Badge",
            "skills": [title] if title else ["AWS"],
        }
        try:
            badges.append(AwsBadgeItemModel(**entry).model_dump(mode="json"))
        except ValidationError as ve:
            logging.getLogger("aws_skills").warning(
                f"[WARN] Anomaly Guard: Skipping malformed CSV row entry '{title}': {ve}"
            )
            skipped += 1

    logging.getLogger("aws_skills").info(
        f"[OK] Extracted {len(badges)} valid AWS badge records from CSV."
    )
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
        logging.getLogger("aws_skills").info(
            f"[SYNC] Attempting fetch from endpoint: {url}"
        )
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
                                parsed.append(
                                    AwsBadgeItemModel(**entry).model_dump(mode="json")
                                )
                            except ValidationError:
                                pass
                    if parsed:
                        logging.getLogger("aws_skills").info(
                            f"[OK] Successfully fetched {len(parsed)} badges via JSON API endpoint."
                        )
                        return parsed
        except requests.exceptions.RequestException as e:
            logging.getLogger("aws_skills").warning(
                f"[WARN] Request failed for {url}: {e}"
            )

    logging.getLogger("aws_skills").error(
        "[FAIL] Failed to acquire AWS Skill Builder badges from CSV, local JSON, or network endpoints."
    )
    return []


# ==============================================================================
# MODULE-LEVEL UTILITIES (for backward compatibility with tests)
# ==============================================================================

from loss_guard import (
    load_retired_rules as _load_retired_rules,
)
from loss_guard import (
    mark_retired as _mark_retired,
)


def load_retired_rules(platform: str) -> list[dict[str, Any]]:
    """Wrapper that uses module-level RETIRED_URLS_FILE for test compatibility."""
    return _load_retired_rules(platform, retired_urls_file=RETIRED_URLS_FILE)


def mark_retired(
    items: list[dict], retired_rules: list[dict[str, Any]], **kwargs
) -> tuple[int, int]:
    """Wrapper that uses module-level mark_retired."""
    return _mark_retired(items, retired_rules, **kwargs)


# ==============================================================================
# PIPELINE CLASS
# ==============================================================================


# Module-level constant for test compatibility (patched by tests)
RETIRED_URLS_FILE = "retired_urls.json"


class AWSSkillsPipeline(PipelineBase):
    PLATFORM_NAME = "aws-skills"
    PLATFORM_PREFIX = "aws-skills"
    PLATFORM_DISPLAY_NAME = "AWS Skill Builder Credentials"
    # Use module-level constants but read dynamically in methods
    ARCHIVE_DIR = "archives"
    README_PATH = "README.md"
    ARCHIVE_MONOLITH = os.path.join("archives", "aws-skills-complete.md")
    MARKER_START = "<!-- AWS_SKILLS_START -->"
    MARKER_END = "<!-- AWS_SKILLS_END -->"

    TABLE_HEADERS: ClassVar[list[str]] = [
        "Date Earned",
        "Credential Name",
        "Issuer",
        "Verification Type",
    ]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---", ":---:"]

    AWS_PROFILE_USER = AWS_PROFILE_USER
    HEADERS = HEADERS

    @property
    def VALIDATION_DIR(self):
        return VALIDATION_DIR

    @property
    def OUTPUT_FILE(self):
        return OUTPUT_FILE

    @property
    def OUTPUT_FILENAME(self):
        return OUTPUT_FILENAME

    def fetch_data(self) -> list[dict]:
        """Orchestrates ingestion prioritizing CSV exports, local JSON files, then API endpoints."""
        return fetch_aws_skills_badges(self.AWS_PROFILE_USER)

    def parse_data(self, raw_data) -> list[dict]:
        """Parse/transform raw data - already validated via Pydantic in fetch_data."""
        return raw_data

    def pre_loss_guard(self, records: list[dict]) -> list[dict]:
        """Deduplicate records before loss guard."""
        unique_badges = []
        seen = set()
        for badge in records:
            dedup_key = (
                badge.get("id") or f"{badge.get('title')}-{badge.get('issued_at')}"
            )
            if dedup_key not in seen:
                seen.add(dedup_key)
                unique_badges.append(badge)
        return unique_badges

    def post_loss_guard(self, records: list[dict]) -> list[dict]:
        """Mark retired items after loss guard."""
        retired_rules = self.get_retired_rules()
        if retired_rules:
            _, marked = mark_retired(records, retired_rules, url_field="verify_url")
            if marked > 0:
                self.logger.info(
                    f"[NOTE] Updated {marked} badge(s) with retired status"
                )
        return records

    def persist_validation(self, records):
        """Persist validated data with AWS-specific filename."""
        os.makedirs(self.VALIDATION_DIR, exist_ok=True)
        validation_file = (
            self.OUTPUT_FILE
        )  # Use module-level OUTPUT_FILE for test compatibility

        payload = self.get_validation_payload(records)
        try:
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self.logger.info(f"[SAVE] Full data persisted: '{validation_file}'")
        except Exception as e:
            self.logger.warning(f"[WARN] Could not persist validation data: {e}")

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        """Format single record for markdown table: (row_text, date)."""
        # Date is now guaranteed to be set (with fallback in parser)
        date_str = str(record.get("issued_at") or "2026-01-01").strip()
        title = str(record.get("title") or "Unknown Credential").strip()
        verify_url = record.get("verify_url")
        issuer = str(record.get("issuer") or "Amazon Web Services").strip()
        v_type = str(record.get("type") or "AWS Skill Builder Badge").strip()
        retired = record.get("retired", False)

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
            name_cell += " [WARN] *Content retired*"
        row_text = f"| {date_str} | {name_cell} | {issuer_clean} | {v_type_clean} |"
        return row_text, date_str

    def build_readme_lines(self, records: list[dict], latest_slice: str) -> list[str]:
        """Build README section lines."""
        total_count = len(records)
        all_skills: set[str] = set()

        for b in records:
            for skill in b.get("skills", []):
                if isinstance(skill, str) and skill.strip():
                    all_skills.add(skill.strip())
        total_skills = len(all_skills)

        index_raw = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/aws-skills-index.md"
        profile_url = (
            f"https://skillsprofile.skillbuilder.aws/user/{self.AWS_PROFILE_USER}"
        )

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

        for record in records[:10]:
            row_text, _ = self.format_for_archive(record)
            readme_lines.append(row_text)

        return readme_lines

    def get_validation_payload(self, records: list[dict]) -> dict:
        """Build validation payload with AWS-specific fields."""
        layer_metadata = {}
        try:
            from layer_manifest import load_manifest

            manifest = load_manifest()
            if "aws-skills" in manifest.platforms:
                platform = manifest.platforms["aws-skills"]
                for layer_name in (
                    "L0_raw",
                    "L1_normalized",
                    "L2_published",
                    "L3_display",
                ):
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
        except Exception:
            pass

        return {
            "platform": self.PLATFORM_NAME,
            "profile_user": self.AWS_PROFILE_USER,
            "total_count": len(records),
            "badges": records,
            "_layer_metadata": layer_metadata,
        }

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records for L2 archive JSON."""
        return records


# ==============================================================================
# BACKWARD COMPATIBILITY WRAPPERS (for tests)
# ==============================================================================

from loss_guard import execute_content_loss_guard as _execute_content
from loss_guard import execute_data_loss_guard as _execute_guard
from loss_guard import get_stored_archive_baseline_count as _get_count


def get_stored_archive_baseline_count(json_path: str, monolith_path: str) -> int:
    return _get_count("aws-skills", json_path, monolith_path)


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    return _execute_guard(new_badges, "aws-skills", output_file, ARCHIVE_MONOLITH)


def execute_content_loss_guard(*args, **kwargs):
    return _execute_content(*args, **kwargs)


# Module-level main function for backward compat
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    AWSSkillsPipeline().run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
