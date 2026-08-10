"""
update_google_skills.py
-----------------------
API and HTML scraping pipeline updating Google Skills / Cloud Skills Boost credentials.
Includes Pydantic schema validation models, HTML/JSON response parsing, and
data loss/anomaly guards to prevent archive corruption or silent record drops.
"""

import hashlib
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
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
logger = logging.getLogger("google_skills_updater")

# Configuration Constants
VALIDATION_DIR = "for_validation"
GOOGLE_SKILLS_PROFILE_ID = os.getenv("GOOGLE_SKILLS_PROFILE_ID", "2011cb91-6066-4d7f-bbec-644b1530829b")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", os.path.join(VALIDATION_DIR, "google_skills_badges.json"))

# Data Loss / Anomaly Guard Tolerances
MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Fail if new badge count drops >15% below stored archive

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.8",
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

    # Handle numeric string timestamp
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
    """Normalized schema for processed Google Skills badge entity validated before archive output."""
    id: str = Field(..., min_length=1, description="Unique badge ID or generated slug hash")
    title: str = Field(..., min_length=1, description="Verified credential or badge title")
    name: str = Field(..., min_length=1, description="Standard title duplicate for compatibility")
    issuer: str = Field("Google Cloud", description="Issuing organization or authority")
    issuer_name: str = Field("Google Cloud", description="Issuer alias for schema compatibility")
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Hosted badge image asset URL")
    verify_url: str | None = Field(None, description="Public verification link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("Google Skill Badge", description="Credential classification type")
    verification_type: str = Field("Google Skill Badge", description="Alias for verification category")
    skills: list[str] = Field(default_factory=list, description="Array of extracted skill strings")

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


class GoogleSkillsArchivePayloadModel(BaseModel):
    """Root model for JSON persistence validation."""
    profile_id: str
    total_count: int = Field(ge=0)
    badges: list[GoogleBadgeItemModel]


# ==============================================================================
# ANOMALY & LOSS GUARD ASSERTIONS
# ==============================================================================

class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous archive baseline."""


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    """
    Loss Guard: Compares new incoming parsed badge count against existing local JSON.
    Prevents corrupt API/HTML responses from silently clearing archive data.
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

def generate_badge_id(title: str, date_str: str | None, verify_url: str | None = None) -> str:
    """Generates a stable, unique identifier for Google Skills badges.
    Prioritizes Google's canonical numeric badge ID from verify_url if present.
    """
    if verify_url:
        m = re.search(r"/badges/(\d+)", verify_url)
        if m:
            return f"google-skills-badge-{m.group(1)}"
        m_id = re.search(r"[?&]id=([^&]+)", verify_url)
        if m_id:
            return f"google-skills-badge-{m_id.group(1)}"

    raw = f"google-skills-{title.strip().lower()}-{date_str or ''}-{verify_url or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_badges_from_html(html_content: str, profile_id: str) -> list[dict]:
    """Parses Google Skills / Cloud Skills Boost profile HTML for earned badges."""
    soup = BeautifulSoup(html_content, "html.parser")
    badges = []

    badge_cards = (
        soup.select(".public-profile-badge")
        or soup.select(".profile-badge")
        or soup.select(".ql-badge")
        or soup.select(".badge-item")
        or soup.find_all(
            "div",
            class_=lambda c: c
            and "badge" in c.lower()
            and "grid" not in c.lower()
            and "container" not in c.lower(),
        )
    )

    logger.info(f"  Extracted {len(badge_cards)} raw badge elements from profile HTML.")
    public_profile_url = f"https://www.skills.google/public_profiles/{profile_id}"

    for idx, card in enumerate(badge_cards, start=1):
        title = None
        raw_date = None

        # Extract Verification Link FIRST so verify_url is available for canonical ID generation
        link_elem = card.find("a")
        verify_url = link_elem.get("href") if link_elem else public_profile_url
        if verify_url and verify_url.startswith("/"):
            verify_url = f"https://www.skills.google{verify_url}"

        # Strategy 1: Explicit CSS Selectors for Title
        title_elem = (
            card.select_one(".public-profile-badge__name")
            or card.select_one(".public-profile-badge__title")
            or card.select_one(".badge-name")
            or card.select_one(".badge-title")
            or card.select_one(".ql-subhead-1")
            or card.select_one(".ql-subhead-2")
            or card.select_one(".ql-title")
            or card.select_one(".ql-title-medium")
            or card.select_one(".ql-body-1")
            or card.select_one("h1")
            or card.select_one("h2")
            or card.select_one("h3")
            or card.select_one("h4")
            or card.select_one("a.ql-subhead-1")
            or card.select_one("a")
        )
        if title_elem:
            title = title_elem.get_text(strip=True)

        # Extract all clean lines of text inside card for fallbacks
        lines = [
            line.strip()
            for line in card.get_text(separator="\n").split("\n")
            if line.strip()
        ]

        # Strategy 2: Text Line Fallback for Title
        if not title and lines:
            for line in lines:
                line_lower = line.lower()
                if not any(
                    k in line_lower
                    for k in [
                        "earned",
                        "completed",
                        "est",
                        "edt",
                        "pst",
                        "pdt",
                        "format_quote",
                        "share",
                        "verify",
                        "view credential",
                    ]
                ):
                    title = line
                    break

        if not title:
            logger.warning(f"⚠️ Could not extract title for badge card #{idx}. Skipping element.")
            continue

        # Extract Date
        date_elem = (
            card.select_one(".public-profile-badge__date")
            or card.select_one(".badge-date")
            or card.select_one(".ql-body-2")
            or card.select_one(".ql-date")
            or card.select_one(".ql-caption")
            or card.select_one("span.date")
            or card.select_one("p.date")
        )
        if date_elem:
            raw_date = date_elem.get_text(strip=True)
        else:
            for line in lines:
                line_lower = line.lower()
                if any(
                    k in line_lower
                    for k in [
                        "earned",
                        "completed",
                        "jan",
                        "feb",
                        "mar",
                        "apr",
                        "may",
                        "jun",
                        "jul",
                        "aug",
                        "sep",
                        "oct",
                        "nov",
                        "dec",
                    ]
                ):
                    raw_date = line
                    break

        if raw_date:
            for keyword in ["Earned", "Completed", "EST", "EDT", "PST", "PDT"]:
                raw_date = raw_date.replace(keyword, "").strip()

        # Extract Image URL
        img_elem = card.find("img")
        image_url = img_elem.get("src") if img_elem else None

        badge_id = generate_badge_id(title, raw_date, verify_url)

        raw_entry = {
            "id": badge_id,
            "title": title,
            "name": title,
            "issuer": "Google Cloud",
            "issuer_name": "Google Cloud",
            "issued_at": raw_date,
            "issued_at_date": raw_date,
            "date": raw_date,
            "image_url": image_url,
            "verify_url": verify_url,
            "url": verify_url,
            "type": "Google Skill Badge",
            "verification_type": "Google Skill Badge",
            "skills": [title],
        }

        try:
            validated_model = GoogleBadgeItemModel(**raw_entry)
            badges.append(validated_model.model_dump())
        except ValidationError as ve:
            logger.warning(
                f"⚠️ Anomaly Guard: Skipping malformed Google Skills badge entry #{idx}: {ve}"
            )

    return badges


def fetch_google_skills_badges(profile_id: str) -> list[dict]:
    """Fetches public profile content from Google Skills / Cloud Skills Boost."""
    urls = [
        f"https://www.skills.google/public_profiles/{profile_id}",
        f"https://www.cloudskillsboost.google/public_profiles/{profile_id}",
    ]

    for url in urls:
        logger.info(f"🔄 Attempting fetch from: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code == 200:
                parsed_badges = parse_badges_from_html(response.text, profile_id)
                if parsed_badges:
                    logger.info(f"✅ Successfully fetched {len(parsed_badges)} badges from {url}")
                    return parsed_badges
            else:
                logger.warning(f"⚠️ Endpoint returned status code {response.status_code}: {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Request failed for {url}: {e}")

    logger.error("❌ Failed to fetch Google Skills badges from all candidate URLs.")
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
        issuer = str(b.get("issuer") or "Google Cloud").strip()
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

    now_ym = datetime.now(UTC).strftime("%Y-%m")
    index_raw = f"{RAW_BASE_DEFAULT}/google-skills-index.md"
    part1_raw = f"{RAW_BASE_DEFAULT}/google-skills-{now_ym}-part-01.md"

    marker_start = "<!-- GOOGLE_SKILLS_START -->"
    marker_end = "<!-- GOOGLE_SKILLS_END -->"

    profile_url = f"https://www.skills.google/public_profiles/{GOOGLE_SKILLS_PROFILE_ID}"

    readme_lines = [
        "### Google Skills Credentials",
        "",
        f"[Google Skills Profile]({profile_url})",
        "",
        f"Public Profile: [Verify Google Skills Profile]({profile_url})",
        f"**Total Portfolio Credentials:** {total_count}",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/google-skills-index.md) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({part1_raw}), or [Monolithic File](./archives/google-skills-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    generate_platform_archive(
        platform_prefix="google-skills",
        platform_name="Google Skills Credentials",
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
    logger.info("Starting Google Skills API/Scraping Pipeline with Pydantic & Loss Guards...")

    # Ensure validation directory exists before execution
    output_dir = os.path.dirname(OUTPUT_FILE)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    raw_badges = fetch_google_skills_badges(GOOGLE_SKILLS_PROFILE_ID)

    unique_badges = []
    seen = set()

    for badge in raw_badges:
        dedup_key = (
            badge.get("id")
            or badge.get("verify_url")
            or f"{badge.get('title')}-{badge.get('issued_at')}"
        )
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
        "profile_id": GOOGLE_SKILLS_PROFILE_ID,
        "total_count": len(unique_badges),
        "badges": unique_badges,
    }

    try:
        validated_payload = GoogleSkillsArchivePayloadModel(**payload_dict)
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
