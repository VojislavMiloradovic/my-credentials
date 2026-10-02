"""
update_linkedin.py
------------------
Pipeline for updating LinkedIn / manual external certifications from CSV exports.
Includes CSV parsing, Pydantic schema validation, date normalization,
data loss / anomaly guards, and integration with the repository archiver.

Refactored to inherit from PipelineBase for standardized orchestration.
"""

import csv
import glob
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import ConfigDict, Field, ValidationError, field_validator

from models.provenance import ProvenanceBase, RetrievalMethod, VerificationStatus
from pipeline_base import PipelineBase

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
    execute_content_loss_guard = None
    PipelineDataLossAnomaly = Exception

# Layer Manifest Integration
try:
    from layer_manifest import get_layer_def, get_platform_layers, load_manifest
except ImportError:
    get_platform_layers = None
    get_layer_def = None
    load_manifest = None

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
        logger.warning(f"[WARN] Could not load retired rules for {platform}: {e}")
        return []


def mark_retired(
    items: list[dict],
    retired_rules: list[dict[str, Any]],
    url_field: str = "url",
    id_fields: list[str] | None = None,
    retired_field: str = "retired",
) -> tuple[int, int]:
    """Mark items as retired if their ID, License, or URL matches known retired rules."""
    if not retired_rules:
        return len(items), 0
    search_id_fields = id_fields or ["id", "license", "url"]
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
                f"[LABEL]  Marked as retired: {item.get('name') or item.get('id') or 'unknown'}"
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
logger = logging.getLogger("linkedin_updater")


# Configuration Constants
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "linkedin-certifications"
PLATFORM_NAME = "linkedin-certifications"
PLATFORM_DISPLAY_NAME = "LinkedIn Certifications"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")
LINKEDIN_PROFILE_ID = os.getenv("LINKEDIN_PROFILE_ID") or "vojislavmiloradovic"
LINKEDIN_PROFILE_URL = f"https://www.linkedin.com/in/{LINKEDIN_PROFILE_ID}/"

MARKER_START = "<!-- LINKEDIN_START -->"
MARKER_END = "<!-- LINKEDIN_END -->"

MAX_ALLOWED_DATA_LOSS_PCT = (
    0.15  # Fail if incoming cert count drops >15% below stored baseline
)

# Minimum expected record counts for contamination detection (Fix 3)
MIN_EXPECTED = {
    "credly": 100,
    "google-skills": 50,
    "microsoft-learn": 1000,
    "linkedin-certifications": 200,
    "aws-skills": 100,
    "google-developer": 200,
}

MONTH_MAP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


# ==============================================================================
# DATE NORMALIZATION & SCHEMAS
# ==============================================================================


class LinkedInCertModel(ProvenanceBase):
    """Normalized schema for LinkedIn / external certification entity."""

    # Platform-specific fields
    name: str = Field(..., min_length=1, description="Certification or course title")
    authority: str = Field("Unknown Issuer", description="Issuing organization")
    issued: str = Field(
        "N/A", description="Issued date in YYYY-MM or YYYY-MM-DD format"
    )
    url: str = Field("", description="Verification URL")
    license: str = Field("", description="License or Credential ID")
    original_order: int = Field(0, description="Original index in CSV for tie-breaking")
    retired: bool = Field(
        False, description="Whether the content has been retired by the platform"
    )

    # Provenance fields with platform-specific defaults
    source_platform: str = Field(
        default="linkedin-certifications", description="Platform identifier"
    )
    source_record_id: str | None = Field(
        None, description="Stable ID from source platform"
    )
    source_url: str | None = Field(None, description="Canonical URL on source platform")
    verify_url: str | None = Field(None, description="Independent verification link")
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

    @field_validator("issued", mode="before")
    @classmethod
    def validate_issued_date(cls, val: Any) -> str:
        return parse_linkedin_date(val)

    @field_validator("verification_status", mode="before")
    @classmethod
    def compute_verification_status(cls, val: Any, info) -> VerificationStatus:
        """Auto-compute verification status from record state."""
        if isinstance(val, VerificationStatus):
            return val
        retired_val = info.data.get("retired", False)
        url_val = info.data.get("url") or info.data.get("verify_url")
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


# ==============================================================================
# ANOMALY & LOSS GUARD
# ==============================================================================


class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous archive baseline."""


def get_stored_archive_baseline_count() -> int:
    """Evaluates baseline record count from existing monolith markdown archive."""
    if os.path.exists(ARCHIVE_MONOLITH):
        try:
            with open(ARCHIVE_MONOLITH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            rows = [
                l
                for l in lines
                if l.strip().startswith("|")
                and not l.strip().startswith("| Date")
                and ":---" not in l
            ]
            if rows:
                return len(rows)
        except OSError:
            pass
    return 0


def execute_data_loss_guard(new_certs: list[dict]) -> None:
    """Compares incoming certification count against stored monolith archive baseline."""
    old_count = get_stored_archive_baseline_count()
    new_count = len(new_certs)

    logger.info(
        f"[SHIELD] Loss Guard Check: Stored Archive Baseline = {old_count} certs | Incoming Dataset = {new_count} certs."
    )

    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming fetch returned 0 certs, but stored baseline contains {old_count}. Aborting sync."
        )

    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming certification count ({new_count}) dropped by {drop_ratio:.1%} "
                f"from baseline ({old_count}). Maximum allowed drop threshold is {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting write."
            )

    logger.info(
        "[OK] Loss Guard Assertion Passed: Incoming payload verified against archive baseline."
    )


# ==============================================================================
# CSV PARSER
# ==============================================================================


MONTH_MAP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


def parse_linkedin_date(date_str: Any) -> str:
    """Coerces timestamps, ISO strings, 'MMM YYYY', and text dates to YYYY-MM or YYYY-MM-DD."""
    if not date_str or str(date_str).strip().lower() in ["null", "none", "", "n/a"]:
        return "N/A"

    clean_str = str(date_str).strip()

    # Handle ISO YYYY-MM-DD
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", clean_str)
    if iso_match:
        return iso_match.group(1)

    # Handle YYYY-MM
    ym_match = re.search(r"(\d{4}-\d{2})", clean_str)
    if ym_match:
        return ym_match.group(1)

    # Handle Month Year (e.g., "Mar 2026", "March 2026")
    match = re.search(r"([a-zA-Z]{3,})\s+(\d{4})", clean_str)
    if match:
        month_part = match.group(1).lower()[:3]
        year_part = match.group(2)
        month_num = MONTH_MAP.get(month_part, "00")
        return f"{year_part}-{month_num}"

    return "N/A"


# ==============================================================================
# PIPELINE CLASS
# ==============================================================================


class LinkedInCertPipeline(PipelineBase):
    """LinkedIn Certifications Pipeline - inherits from PipelineBase."""

    # Use module-level constants for test patching compatibility
    PLATFORM_NAME = PLATFORM_NAME
    PLATFORM_PREFIX = PLATFORM_PREFIX
    PLATFORM_DISPLAY_NAME = PLATFORM_DISPLAY_NAME
    ARCHIVE_DIR = ARCHIVE_DIR
    README_PATH = README_PATH

    # Paths for count loss guard baseline lookup
    # Properties to read patched module-level constants at runtime
    @property
    def VALIDATION_DIR(self) -> str:
        import update_linkedin

        return update_linkedin.VALIDATION_DIR

    @property
    def ARCHIVE_MONOLITH(self) -> str:
        import update_linkedin

        return update_linkedin.ARCHIVE_MONOLITH

    @property
    def JSON_PATH(self) -> str:
        import update_linkedin

        return os.path.join(
            update_linkedin.VALIDATION_DIR, "linkedin-certifications.json"
        )

    @property
    def MONOLITH_PATH(self) -> str:
        import update_linkedin

        return update_linkedin.ARCHIVE_MONOLITH

    TABLE_HEADERS: ClassVar[list[str]] = [
        "Date Completed",
        "Certification Title",
        "Issuing Authority",
        "Verification Reference",
    ]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---", ":---"]

    LINKEDIN_PROFILE_ID = LINKEDIN_PROFILE_ID
    LINKEDIN_PROFILE_URL = LINKEDIN_PROFILE_URL

    RAW_BASE_DEFAULT = RAW_BASE_DEFAULT
    MARKER_START = MARKER_START
    MARKER_END = MARKER_END

    def _sort_key(self, record):
        """Sort by 'issued' field (LinkedIn uses 'issued' not 'date')."""
        date = record.get("issued", "0000-00")
        if date is None or date == "N/A":
            return "0000-00"
        return date

    def fetch_data(self) -> list[dict]:
        """Fetch and parse LinkedIn certifications from CSV."""
        # Use module-level function so test patching works
        csv_path = locate_certifications_csv()
        if not csv_path:
            self.logger.error(
                "[FAIL] Could not locate CSV certifications file in data/ or root directory."
            )
            sys.exit(1)

        retrieved_at = datetime.now(UTC)
        certs = parse_certifications_csv(csv_path)
        if not certs:
            self.logger.error("[FAIL] No certification records extracted. Aborting.")
            sys.exit(1)

        # Store retrieved_at for provenance
        for c in certs:
            c["retrieved_at"] = retrieved_at.isoformat()

        return certs

    def _locate_certifications_csv(self) -> str | None:
        """Locates candidate CSV certification export files in current directory or data subfolder."""
        candidates = [
            os.path.join("data", "Certifications.csv"),
            os.path.join("data", "Credentials.csv"),
            os.path.join("data", "linkedin_certifications.csv"),
            "Certifications.csv",
            "Credentials.csv",
            "linkedin_certifications.csv",
        ]

        for cand in candidates:
            if os.path.exists(cand):
                return cand

        glob_matches = glob.glob("data/*cert*.csv") + glob.glob("data/*cred*.csv")
        if glob_matches:
            return glob_matches[0]

        return None

    def _parse_certifications_csv(
        self, csv_path: str, retrieved_at: datetime
    ) -> list[dict]:
        """Parses CSV transcript/certification file into validated models."""
        self.logger.info(
            f"[FILE] Parsing LinkedIn certifications from CSV file: '{csv_path}'"
        )
        certs = []

        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            content = f.read()
            if not content.strip():
                self.logger.warning("[WARN] CSV file is empty.")
                return []

            lines = content.splitlines()
            delimiter = "\t" if "\t" in lines[0] else ","
            f.seek(0)

            reader = csv.DictReader(f, delimiter=delimiter)
            raw_rows = list(reader)

        total_raw = len(raw_rows)
        skipped = 0

        for idx, row in enumerate(raw_rows):
            name = (
                row.get("Name")
                or row.get("name")
                or row.get("Title")
                or row.get("title")
                or ""
            ).strip()
            if not name:
                skipped += 1
                continue

            authority = (
                row.get("Authority")
                or row.get("authority")
                or row.get("Issuer")
                or row.get("issuer")
                or "Unknown Issuer"
            ).strip()

            url = (row.get("Url") or row.get("url") or row.get("URL") or "").strip()
            license_num = (
                row.get("License Number")
                or row.get("license number")
                or row.get("License")
                or row.get("license")
                or ""
            ).strip()

            started = (
                row.get("Started On")
                or row.get("started on")
                or row.get("Issued On")
                or row.get("issued on")
            )
            finished = (
                row.get("Finished On")
                or row.get("finished on")
                or row.get("Expires On")
                or row.get("expires on")
            )

            issued_date = parse_linkedin_date(started)
            expiry_date = parse_linkedin_date(finished)

            # Heuristic swap if dates were inverted in CSV export
            if (
                issued_date != "N/A"
                and issued_date > datetime.now(UTC).strftime("%Y-%m")
                and expiry_date != "N/A"
                and expiry_date <= datetime.now(UTC).strftime("%Y-%m")
            ):
                issued_date, expiry_date = expiry_date, issued_date

            raw_entry = {
                "name": name,
                "authority": authority,
                "issued": issued_date,
                "url": url,
                "license": license_num,
                "original_order": idx,
                "retrieved_at": retrieved_at.isoformat(),
            }

            try:
                validated_model = LinkedInCertModel(**raw_entry)
                certs.append(validated_model.model_dump(mode="json"))
            except ValidationError as ve:
                self.logger.warning(f"[WARN] Skipping malformed CSV row '{name}': {ve}")

        if skipped:
            self.logger.warning(
                f"[WARN] Skipped {skipped} row(s) out of {total_raw} with missing name."
            )

        self.logger.info(
            f"[OK] Extracted {len(certs)} valid certification records from CSV."
        )
        return certs

    def parse_data(self, raw_data) -> list[dict]:
        """Parse/transform raw data - already validated via Pydantic in fetch_data."""
        return raw_data

    def pre_loss_guard(self, records: list[dict]) -> list[dict]:
        """No deduplication needed - original_order handles it."""
        return records

    def post_loss_guard(self, records: list[dict]) -> list[dict]:
        """Mark retired items after loss guard."""
        retired_rules = self.get_retired_rules()
        if retired_rules:
            _, marked = mark_retired(
                records, retired_rules, url_field="url", id_fields=["license", "url"]
            )
            if marked > 0:
                self.logger.info(
                    f"[NOTE] Updated {marked} certification(s) with retired status"
                )
        return records

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        """Format single record for markdown table: (row_text, date)."""
        clean_name = record["name"].replace("|", "\\|")
        clean_auth = record["authority"].replace("|", "\\|")
        ref = (
            f"[Verify Record]({record['url']})"
            if record["url"]
            else (record["license"] if record["license"] else "Verified Account Entry")
        )
        if record.get("retired", False):
            ref += " [WARN] *Content retired*"
        row_text = f"| {record['issued']} | **{clean_name}** | {clean_auth} | {ref} |"
        return row_text, record["issued"]

    def build_readme_lines(self, records: list[dict], latest_slice: str) -> list[str]:
        """Build README section lines."""
        total_certs = len(records)

        index_raw = f"{self.RAW_BASE_DEFAULT}/{self.PLATFORM_PREFIX}-index.md"

        readme_lines = [
            "### LinkedIn Professional Certifications Summary",
            "",
            f"**Public Profile:** [Verify LinkedIn Profile]({self.LINKEDIN_PROFILE_URL})",
            "",
            "#### Progress Metrics",
            "",
            "| Metric | Count |",
            "| :--- | :--- |",
            f"| **Total External Certifications Verified** | {total_certs:,} |",
            "",
            "#### Recent Certifications",
            "",
            f"Showing latest 10 items. View the full dataset via [Platform Archive Index](./archives/{self.PLATFORM_PREFIX}-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic Complete File](./archives/{self.PLATFORM_PREFIX}-complete.md).",
            "",
            "| Date Completed | Certification Title | Issuing Authority | Verification Reference |",
            "| :---: | :--- | :--- | :--- |",
        ]

        for c in records[:10]:
            clean_name = c["name"].replace("|", "\\|")
            clean_auth = c["authority"].replace("|", "\\|")
            ref = (
                f"[Verify Record]({c['url']})"
                if c["url"]
                else (c["license"] if c["license"] else "N/A")
            )
            readme_lines.append(
                f"| *{c['issued']}* | **{clean_name}** | {clean_auth} | {ref} |"
            )

        return readme_lines

    def get_validation_payload(self, records: list[dict]) -> dict:
        """Build validation payload with LinkedIn-specific fields."""
        payload = {
            "platform": self.PLATFORM_NAME,
            "total_count": len(records),
            "certifications": records,
        }
        return payload

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records to write to L2 archive JSON."""
        return records

    def persist_validation(self, records: list[dict]) -> None:
        """Persist validated data with LinkedIn-specific fields (ensure ASCII for test compatibility)."""
        # Fix 3: Contamination detection - fail if record count is suspiciously low
        # Only run in CI environment (not in local tests or pytest)
        in_ci = os.getenv("CI") == "true"
        in_pytest = (
            "pytest" in sys.modules
            or os.getenv("PYTEST_CURRENT_TEST") is not None
            or "PYTEST_VERSION" in os.environ
        )
        if in_ci and not in_pytest:
            min_expected = MIN_EXPECTED.get(self.PLATFORM_NAME, 0)
            if min_expected > 0 and len(records) < min_expected:
                self.logger.error(
                    f"[CONTAMINATION] Record count ({len(records)}) below minimum "
                    f"expected ({min_expected}) for {self.PLATFORM_NAME}. "
                    f"Possible test data contamination. Aborting persist."
                )
                raise RuntimeError(
                    f"Contamination detected: {len(records)} records < {min_expected} minimum "
                    f"for {self.PLATFORM_NAME}. Check for test data leakage."
                )

        os.makedirs(self.VALIDATION_DIR, exist_ok=True)
        validation_file = os.path.join(
            self.VALIDATION_DIR, "linkedin-certifications.json"
        )
        payload = {
            "platform": self.PLATFORM_NAME,
            "total_count": len(records),
            "certifications": records,
        }
        try:
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=True)
            self.logger.info(
                f"[SAVE] Full data persisted: '{validation_file}' ({len(records)} certifications)"
            )
        except Exception as e:
            self.logger.warning(f"[WARN] Could not persist full data: {e}")


# Module-level main function for backward compat
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    LinkedInCertPipeline().run()


# Module-level functions for backward compatibility with tests
def locate_certifications_csv() -> str | None:
    """Module-level wrapper for test compatibility."""
    return LinkedInCertPipeline()._locate_certifications_csv()


def parse_certifications_csv(csv_path: str) -> list[dict]:
    """Module-level wrapper for test compatibility."""
    pipeline = LinkedInCertPipeline()
    retrieved_at = datetime.now(UTC)
    return pipeline._parse_certifications_csv(csv_path, retrieved_at)


if __name__ == "__main__":
    main()
