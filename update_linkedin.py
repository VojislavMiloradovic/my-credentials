"""
update_linkedin.py
---------------------------------
Pipeline for updating LinkedIn / manual external certifications from CSV exports.
Includes CSV parsing, Pydantic schema validation, date normalization,
data loss / anomaly guards, and integration with the repository archiver.
"""

import csv
import glob
import logging
import os
import re
import sys
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

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("linkedin_updater")

# Configuration Constants
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "linkedin-certifications"
PLATFORM_NAME = "LinkedIn Certifications"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")
LINKEDIN_PROFILE_ID = os.getenv("LINKEDIN_PROFILE_ID") or "vojislavmiloradovic"
LINKEDIN_PROFILE_URL = f"https://www.linkedin.com/in/{LINKEDIN_PROFILE_ID}/"

MARKER_START = "<!-- LINKEDIN_START -->"
MARKER_END = "<!-- LINKEDIN_END -->"

MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Fail if incoming cert count drops >15% below stored baseline

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
}


# ==============================================================================
# DATE NORMALIZATION & SCHEMAS
# ==============================================================================

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


class LinkedInCertModel(BaseModel):
    """Normalized schema for LinkedIn / external certification entity."""
    name: str = Field(..., min_length=1, description="Certification or course title")
    authority: str = Field("Unknown Issuer", description="Issuing organization")
    issued: str = Field("N/A", description="Issued date in YYYY-MM or YYYY-MM-DD format")
    url: str = Field("", description="Verification URL")
    license: str = Field("", description="License or Credential ID")
    original_order: int = Field(0, description="Original index in CSV for tie-breaking")

    @field_validator("issued", mode="before")
    @classmethod
    def validate_issued_date(cls, val: Any) -> str:
        return parse_linkedin_date(val)


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
                l for l in lines
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

    logger.info(f"🛡️ Loss Guard Check: Stored Archive Baseline = {old_count} certs | Incoming Dataset = {new_count} certs.")

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

    logger.info("✅ Loss Guard Assertion Passed: Incoming payload verified against archive baseline.")


# ==============================================================================
# CSV PARSER
# ==============================================================================

def locate_certifications_csv() -> str | None:
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


def parse_certifications_csv(csv_path: str) -> list[dict]:
    """Parses CSV transcript/certification file into validated models."""
    logger.info(f"📄 Parsing LinkedIn certifications from CSV file: '{csv_path}'")
    certs = []
    current_year_month = datetime.now(UTC).strftime("%Y-%m")

    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        content = f.read()
        if not content.strip():
            logger.warning("⚠️ CSV file is empty.")
            return []

        lines = content.splitlines()
        delimiter = "\t" if "\t" in lines[0] else ","
        f.seek(0)

        reader = csv.DictReader(f, delimiter=delimiter)
        raw_rows = list(reader)

    total_raw = len(raw_rows)
    skipped = 0

    for idx, row in enumerate(raw_rows):
        name = (row.get("Name") or row.get("name") or row.get("Title") or row.get("title") or "").strip()
        if not name:
            skipped += 1
            continue

        authority = (
            row.get("Authority") or row.get("authority") or row.get("Issuer") or row.get("issuer") or "Unknown Issuer"
        ).strip()

        url = (row.get("Url") or row.get("url") or row.get("URL") or "").strip()
        license_num = (
            row.get("License Number") or row.get("license number") or row.get("License") or row.get("license") or ""
        ).strip()

        started = row.get("Started On") or row.get("started on") or row.get("Issued On") or row.get("issued on")
        finished = row.get("Finished On") or row.get("finished on") or row.get("Expires On") or row.get("expires on")

        issued_date = parse_linkedin_date(started)
        expiry_date = parse_linkedin_date(finished)

        # Heuristic swap if dates were inverted in CSV export
        if (
            issued_date != "N/A"
            and issued_date > current_year_month
            and expiry_date != "N/A"
            and expiry_date <= current_year_month
        ):
            issued_date, expiry_date = expiry_date, issued_date

        raw_entry = {
            "name": name,
            "authority": authority,
            "issued": issued_date,
            "url": url,
            "license": license_num,
            "original_order": idx,
        }

        try:
            validated_model = LinkedInCertModel(**raw_entry)
            certs.append(validated_model.model_dump())
        except ValidationError as ve:
            logger.warning(f"⚠️ Skipping malformed CSV row '{name}': {ve}")

        if skipped:
            logger.warning(f"⚠️ Skipped {skipped} row(s) out of {total_raw} with missing name.")

    logger.info(f"✅ Extracted {len(certs)} valid certification records from CSV.")
    return certs


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def main():
    logger.info("Starting LinkedIn Certifications Pipeline...")

    csv_path = locate_certifications_csv()
    if not csv_path:
        logger.error("❌ Could not locate CSV certifications file in data/ or root directory.")
        sys.exit(1)

    certs = parse_certifications_csv(csv_path)
    if not certs:
        logger.error("❌ No certification records extracted. Aborting.")
        sys.exit(1)

    # 1. Execute Content-Aware Loss Guard check against stored baseline
    #    Uses license number + name hash as stable ID for LinkedIn certs
    #    to detect replacement/modification even when total count remains stable.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=certs,
                platform="linkedin-certifications",
                id_field="license",  # LinkedIn uses license number as primary ID
                fail_on_warn=True  # SET TO False TO DISABLE FAILURES (comment out raise in loss_guard.py)
            )
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)
    else:
        logger.warning("⚠️ Content-aware loss guard unavailable, falling back to count-only check")
        try:
            execute_data_loss_guard(certs)
        except PipelineDataLossAnomaly as anomaly_err:
            logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
            sys.exit(1)

    total_certs = len(certs)

    # 2. Sort: reverse original order first, then reverse issued date (ties broken by position in CSV)
    certs.sort(key=lambda x: x["original_order"], reverse=True)
    certs.sort(key=lambda x: x.get("issued") if x.get("issued") != "N/A" else "0000-00", reverse=True)

    table_headers = ["Date Completed", "Certification Title", "Issuing Authority", "Verification Reference"]
    table_alignments = [":---:", ":---", ":---", ":---"]

    formatted_rows = []
    for c in certs:
        clean_name = c["name"].replace("|", "\\|")
        clean_auth = c["authority"].replace("|", "\\|")
        ref = (
            f"[Verify Record]({c['url']})"
            if c["url"]
            else (c["license"] if c["license"] else "Verified Account Entry")
        )
        row_text = f"| {c['issued']} | **{clean_name}** | {clean_auth} | {ref} |"
        formatted_rows.append((row_text, c["issued"]))

    index_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-index.md"
    LATEST_SLICE_RAW = ""

    readme_lines = [
        "### LinkedIn Professional Certifications Summary",
        "",
        f"**Public Profile:** [Verify LinkedIn Profile]({LINKEDIN_PROFILE_URL})",
        "",
        "#### Progress Metrics",
        "",
        "| Metric | Count |",
        "| :--- | :--- |",
        f"| **Total External Certifications Verified** | {total_certs:,} |",
        "",
        "#### Recent Certifications",
        "",
        f"Showing latest 10 items. View the full dataset via [Platform Archive Index](./archives/{PLATFORM_PREFIX}-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({{LATEST_SLICE_RAW}}), or [Monolithic Complete File](./archives/{PLATFORM_PREFIX}-complete.md).",
        "",
        "| Date Completed | Certification Title | Issuing Authority | Verification Reference |",
        "| :---: | :--- | :--- | :--- |",
    ]

    for c in certs[:10]:
        clean_name = c["name"].replace("|", "\\|")
        clean_auth = c["authority"].replace("|", "\\|")
        ref = (
            f"[Verify Record]({c['url']})"
            if c["url"]
            else (c["license"] if c["license"] else "N/A")
        )
        readme_lines.append(f"| *{c['issued']}* | **{clean_name}** | {clean_auth} | {ref} |")

    # 3. Trigger Archiver
    if generate_platform_archive:
        latest_slice = generate_platform_archive(
            platform_prefix=PLATFORM_PREFIX,
            platform_name=PLATFORM_NAME,
            table_headers=table_headers,
            table_alignments=table_alignments,
            formatted_rows=formatted_rows,
            readme_lines=readme_lines,
            marker_start=MARKER_START,
            marker_end=MARKER_END,
            archive_dir=ARCHIVE_DIR,
            readme_path=README_PATH,
        )

        if latest_slice:
            LATEST_SLICE_RAW = RAW_BASE_DEFAULT + "/" + latest_slice
            for i, line in enumerate(readme_lines):
                if "{LATEST_SLICE_RAW}" in line:
                    readme_lines[i] = line.replace("{LATEST_SLICE_RAW}", LATEST_SLICE_RAW)
                    break
            if os.path.exists("README.md"):
                with open("README.md", "r", encoding="utf-8") as f:
                    readme_content = f.read()
                if MARKER_START in readme_content and MARKER_END in readme_content:
                    before = readme_content.split(MARKER_START)[0]
                    after = readme_content.split(MARKER_END)[1]
                    new_block = "\n".join(readme_lines) + "\n"
                    new_content = before + MARKER_START + "\n" + new_block + MARKER_END + after
                    safe_write_file("README.md", new_content)
        logger.info("🎉 LinkedIn Certifications pipeline execution completed successfully.")
    else:
        logger.error("❌ Archiver module helper not available. Skipping markdown generation.")


if __name__ == "__main__":
    main()
