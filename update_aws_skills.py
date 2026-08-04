"""
update_aws_skills.py
--------------------
API and scraping pipeline for updating AWS Skill Builder credentials.
Includes Pydantic schema validation, date coercion, data loss / anomaly guards,
and seamless integration with the repository archiver and README generator.
"""

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup
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
logger = logging.getLogger("aws_skills_updater")

# Configuration Constants
AWS_PROFILE_USER = os.getenv("AWS_PROFILE_USER", "vojislavmiloradovic")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "aws_skills_badges.json")

# Data Loss / Anomaly Guard Tolerances
MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Fail if new badge count drops >15% below stored archive

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

    for fmt in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
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


class AwsBadgeItemModel(BaseModel):
    """Normalized schema for processed AWS Skill Builder badge entity validated before archive output."""
    id: str = Field(..., min_length=1, description="Unique badge ID or hash")
    title: str = Field(..., min_length=1, description="AWS achievement or credential title")
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field("Amazon Web Services", description="Issuing body")
    issuer_name: str = Field("Amazon Web Services", description="Issuer alias for compatibility")
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Badge image URL")
    verify_url: str | None = Field(None, description="Public verification or detail link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("AWS Skill Builder Badge", description="Credential classification type")
    verification_type: str = Field("AWS Skill Builder Badge", description="Alias for verification category")
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
                if isinstance(item, str) and item.strip():
                    clean.append(item.strip())
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


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    """
    Loss Guard: Compares new incoming badge count against existing local JSON file.
    Prevents empty or broken fetches from wiping out stored credential records.
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
                f"CRITICAL ANOMALY: Incoming fetch returned 0 badges, but stored archive contains {old_count}. Aborting sync."
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
# FETCHERS & PARSERS
# ==============================================================================

def generate_badge_id(title: str, date_str: str | None) -> str:
    """Generates a stable identifier for badges lacking explicit IDs."""
    raw = f"aws-skills-{title.strip().lower()}-{date_str or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_aws_badges_from_data(raw_items: list[dict] | list[Any], profile_user: str) -> list[dict]:
    """Parses raw JSON payload items or cards into validated dictionary objects."""
    badges = []
    profile_url = f"https://skillsprofile.skillbuilder.aws/user/{profile_user}"

    for item in raw_items:
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or item.get("badgeTitle")
            raw_date = item.get("issued_at") or item.get("earnedDate") or item.get("completedAt") or item.get("date")
            image_url = item.get("image_url") or item.get("imageUrl") or item.get("badgeIcon")
            verify_url = item.get("verify_url") or item.get("badgeUrl") or profile_url
            badge_id = item.get("id") or generate_badge_id(str(title), str(raw_date))

            raw_entry = {
                "id": str(badge_id),
                "title": str(title) if title else "AWS Badge",
                "name": str(title) if title else "AWS Badge",
                "issuer": "Amazon Web Services",
                "issuer_name": "Amazon Web Services",
                "issued_at": raw_date,
                "issued_at_date": raw_date,
                "date": raw_date,
                "image_url": image_url,
                "verify_url": verify_url,
                "url": verify_url,
                "type": "AWS Skill Builder Badge",
                "verification_type": "AWS Skill Builder Badge",
                "skills": [str(title)] if title else ["AWS"],
            }

            try:
                validated_model = AwsBadgeItemModel(**raw_entry)
                badges.append(validated_model.model_dump())
            except ValidationError as ve:
                logger.warning(f"⚠️ Anomaly Guard: Skipping malformed AWS badge item: {ve}")

    return badges


def parse_aws_badges_from_html(html_content: str, profile_user: str) -> list[dict]:
    """Parses AWS Skill Builder public profile HTML for badge entries."""
    soup = BeautifulSoup(html_content, "html.parser")
    badges = []
    profile_url = f"https://skillsprofile.skillbuilder.aws/user/{profile_user}"

    # Try extracting embedded JSON payload in script tags first
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                # Search for arrays of badge objects
                for key in ["badges", "credentials", "achievements", "items"]:
                    if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                        parsed = parse_aws_badges_from_data(data[key], profile_user)
                        if parsed:
                            logger.info(f"  Extracted {len(parsed)} badges from embedded script tag JSON.")
                            return parsed
        except Exception:
            continue

    # DOM Fallback parsing
    badge_cards = (
        soup.select(".badge-card")
        or soup.select(".achievement-card")
        or soup.select(".aws-badge")
        or soup.find_all("div", class_=lambda c: c and "badge" in c.lower())
    )

    logger.info(f"  Extracted {len(badge_cards)} raw badge elements from AWS profile HTML.")

    for card in badge_cards:
        title = None
        raw_date = None

        title_elem = (
            card.select_one(".badge-title")
            or card.select_one("h3")
            or card.select_one("h4")
            or card.select_one(".title")
        )
        if title_elem:
            title = title_elem.get_text(strip=True)

        lines = [line.strip() for line in card.get_text(separator="\n").split("\n") if line.strip()]
        if not title and lines:
            title = lines[0]

        if not title:
            continue

        date_elem = card.select_one(".badge-date") or card.select_one(".date")
        if date_elem:
            raw_date = date_elem.get_text(strip=True)
        else:
            for line in lines:
                if any(k in line.lower() for k in ["earned", "completed", "202", "201"]):
                    raw_date = line
                    break

        img_elem = card.find("img")
        image_url = img_elem.get("src") if img_elem else None

        link_elem = card.find("a")
        verify_url = link_elem.get("href") if link_elem else profile_url

        badge_id = generate_badge_id(title, raw_date)

        raw_entry = {
            "id": badge_id,
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
            "type": "AWS Skill Builder Badge",
            "verification_type": "AWS Skill Builder Badge",
            "skills": [title],
        }

        try:
            validated_model = AwsBadgeItemModel(**raw_entry)
            badges.append(validated_model.model_dump())
        except ValidationError as ve:
            logger.warning(f"⚠️ Anomaly Guard: Skipping malformed AWS badge card: {ve}")

    return badges


def fetch_aws_skills_badges(profile_user: str) -> list[dict]:
    """Fetches public profile content from AWS Skill Builder."""
    urls = [
        f"https://skillsprofile.skillbuilder.aws/user/{profile_user}",
        f"https://skillsprofile.skillbuilder.aws/api/user/{profile_user}/badges",
    ]

    for url in urls:
        logger.info(f"🔄 Attempting fetch from: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code == 200:
                ct = response.headers.get("Content-Type", "")
                if "application/json" in ct:
                    try:
                        data = response.json()
                        raw_list = data if isinstance(data, list) else data.get("badges", data.get("items", []))
                        parsed = parse_aws_badges_from_data(raw_list, profile_user)
                        if parsed:
                            logger.info(f"✅ Successfully fetched {len(parsed)} badges via JSON API endpoint.")
                            return parsed
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to parse JSON response from {url}: {e}")
                else:
                    parsed = parse_aws_badges_from_html(response.text, profile_user)
                    if parsed:
                        logger.info(f"✅ Successfully fetched {len(parsed)} badges via HTML profile parser.")
                        return parsed
            else:
                logger.warning(f"⚠️ Endpoint returned status code {response.status_code}: {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Request failed for {url}: {e}")

    logger.error("❌ Failed to fetch AWS Skill Builder badges from candidate endpoints.")
    return []


# ==============================================================================
# ARCHIVE BUILDER & README GENERATION
# ==============================================================================

def build_archives_and_readme(badges: list[dict]) -> None:
    """Invokes archiver helper to generate markdown chunk files and update README.md."""
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
        issuer = str(b.get("issuer") or "Amazon Web Services").strip()
        v_type = str(b.get("type") or "AWS Skill Builder Badge").strip()

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

    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    index_raw = f"{RAW_BASE_DEFAULT}/aws-skills-index.md"
    part1_raw = f"{RAW_BASE_DEFAULT}/aws-skills-{now_ym}-part-01.md"

    marker_start = "<!-- AWS_SKILLS_START -->"
    marker_end = "<!-- AWS_SKILLS_END -->"

    profile_url = f"https://skillsprofile.skillbuilder.aws/user/{AWS_PROFILE_USER}"

    readme_lines = [
        "### AWS Skill Builder Credentials",
        "",
        f"[AWS Skill Builder Profile]({profile_url})",
        "",
        f"Public Profile: [Verify AWS Skill Builder Profile]({profile_url})",
        f"**Total Portfolio Credentials:** {total_count}",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/aws-skills-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({part1_raw}), or [Monolithic File](./archives/aws-skills-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    generate_platform_archive(
        platform_prefix="aws-skills",
        platform_name="AWS Skill Builder Credentials",
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
    logger.info("Starting AWS Skill Builder Pipeline with Pydantic & Loss Guards...")

    raw_badges = fetch_aws_skills_badges(AWS_PROFILE_USER)

    unique_badges = []
    seen = set()

    for badge in raw_badges:
        dedup_key = badge.get("id") or f"{badge.get('title')}-{badge.get('issued_at')}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique_badges.append(badge)

    # 1. Execute Loss Guard check prior to persistence write
    try:
        execute_data_loss_guard(unique_badges, OUTPUT_FILE)
    except PipelineDataLossAnomaly as anomaly_err:
        logger.error(f"❌ Pipeline Terminated by Anomaly Guard: {anomaly_err}")
        sys.exit(1)

    # 2. Validate Root Payload with Pydantic Schema
    payload_dict = {
        "profile_user": AWS_PROFILE_USER,
        "total_count": len(unique_badges),
        "badges": unique_badges,
    }

    try:
        validated_payload = AwsSkillsArchivePayloadModel(**payload_dict)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(validated_payload.model_dump_json(indent=2))
        logger.info(f"🎉 Persistence complete: '{OUTPUT_FILE}' updated safely ({len(unique_badges)} badges).")
    except ValidationError as ve:
        logger.error(f"❌ Root Payload Validation Error: {ve}")
        sys.exit(1)

    # 3. Build markdown archives and update README
    build_archives_and_readme(unique_badges)
    logger.info("Pipeline execution completed successfully.")


if __name__ == "__main__":
    main()
