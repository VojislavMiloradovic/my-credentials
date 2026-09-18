"""
update_google_skills.py
-----------------------
Pipeline for updating Google Skills / Developer credentials from public profile APIs,
local JSON fallbacks, or exported badge data.
Refactored to use PipelineBase (Option 2 Migration).
"""

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, ClassVar

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Provenance Integration
from models.provenance import ProvenanceBase, RetrievalMethod, VerificationStatus

# PipelineBase Integration
from pipeline_base import PipelineBase

# Playwright for JS-rendered dates
try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None

# ==============================================================================
# MODULE-LEVEL CONSTANTS (for backward compatibility with tests)
# ==============================================================================

GOOGLE_PROFILE_ID = (
    os.getenv("GOOGLE_PROFILE_ID") or "2011cb91-6066-4d7f-bbec-644b1530829b"
)
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "google_skills_badges.json"
OUTPUT_FILE = os.path.join(VALIDATION_DIR, OUTPUT_FILENAME)
ARCHIVE_DIR = "archives"
README_PATH = "README.md"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, "google-skills-complete.md")
MARKER_START = "<!-- GOOGLE_SKILLS_START -->"
MARKER_END = "<!-- GOOGLE_SKILLS_END -->"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Optional internal learning statistics manually editable by user
INTERNAL_STATS = {
    "Course": 396,
    "Check": 1986,
    "Classroom": 0,
    "Game": 10,
    "Lab": 311,
    "Lesson": 4985,
    "Path": 20,
}

RETIRED_URLS_FILE = "retired_urls.json"

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
    raw = f"google-skills-{title.strip().lower()}-{date_str or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class GoogleBadgeItemModel(ProvenanceBase):
    """Normalized schema for Google Skills credential entities."""

    # Platform-specific fields
    id: str = Field(..., min_length=1, description="Unique badge ID or hash")
    title: str = Field(
        ..., min_length=1, description="Google achievement or skill title"
    )
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field("Google Cloud", description="Issuing body")
    issuer_name: str = Field(
        "Google Cloud", description="Issuer alias for compatibility"
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
        "Google Skill Badge", description="Credential classification type"
    )
    verification_type: str = Field(
        "Google Skill Badge", description="Alias for verification category"
    )
    skills: list[str] = Field(default_factory=list, description="Associated skills")
    retired: bool = Field(
        False, description="Whether the content has been retired by the platform"
    )

    # Provenance fields with platform-specific defaults
    source_platform: str = Field(
        default="google-skills", description="Platform identifier"
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
        default=RetrievalMethod.API, description="How retrieved"
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


class GoogleSkillsArchivePayloadModel(BaseModel):
    """Root model for Google Skills JSON validation."""

    profile_id: str
    total_count: int = Field(ge=0)
    badges: list[GoogleBadgeItemModel]


# ==============================================================================
# DATA INGESTION & PARSERS (module-level for backward compat)
# ==============================================================================


def parse_google_badges_from_json(json_path: str) -> list[dict]:
    """Reads existing Google badge entries directly from local JSON storage."""
    if not os.path.exists(json_path):
        return []

    logging.getLogger("google_skills").info(
        f"[FILE] Reading existing Google badges from JSON: '{json_path}'"
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
                    validated = GoogleBadgeItemModel(**item)
                    badges.append(validated.model_dump(mode="json"))
                except ValidationError as ve:
                    logging.getLogger("google_skills").warning(
                        f"[WARN] Skipping invalid JSON badge entry: {ve}"
                    )

        logging.getLogger("google_skills").info(
            f"[OK] Loaded {len(badges)} valid Google badges from JSON file."
        )
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logging.getLogger("google_skills").warning(
            f"[WARN] Error reading JSON file '{json_path}': {e}"
        )
        return []


def fetch_google_skills_badges_playwright(
    profile_id: str, url: str | None = None
) -> list[dict]:
    """Fetch Google Skills badges using Playwright to get JS-rendered dates."""
    if not PLAYWRIGHT_AVAILABLE:
        return []

    target_url = url or f"https://www.skills.google/public_profiles/{profile_id}"
    logging.getLogger("google_skills").info(
        f"[THEATER] Launching Playwright to fetch: {target_url}"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.set_default_timeout(90000)

            page.goto(target_url, wait_until="domcontentloaded", timeout=90000)

            for selector in [
                "text=Earned",
                "text=earned",
                "[class*='earned']",
                "[class*='date']",
            ]:
                try:
                    page.wait_for_selector(selector, timeout=15000)
                    break
                except Exception:
                    continue

            page.wait_for_timeout(5000)

            badges_data = page.evaluate("""
                () => {
                    const results = [];
                    const badgeContainers = document.querySelectorAll('.profile-badge');
                    
                    badgeContainers.forEach(container => {
                        const link = container.querySelector('.badge-image');
                        if (!link) return;
                        
                        const href = link.href;
                        const badgeIdMatch = href.match(/\\/badges\\/(\\d+)/);
                        const badgeId = badgeIdMatch ? `google-skills-badge-${badgeIdMatch[1]}` : null;
                        
                        const titleEl = container.querySelector('.ql-title-medium');
                        const title = titleEl ? titleEl.textContent?.trim() : null;
                        
                        const dateEl = container.querySelector('.ql-body-medium');
                        let earnedDate = null;
                        if (dateEl) {
                            const text = dateEl.textContent || '';
                            const match = text.match(/Earned\\s+([A-Za-z]{3}\\s+\\d{1,2},?\\s+\\d{4})/i);
                            if (match) {
                                earnedDate = match[1];
                            }
                        }
                        
                        if (title) {
                            results.push({
                                id: badgeId,
                                title: title,
                                href: href,
                                earnedDate: earnedDate
                            });
                        }
                    });
                    
                    return results;
                }
            """)

            browser.close()

        logging.getLogger("google_skills").info(
            f"[THEATER] Playwright extracted {len(badges_data)} badges from DOM"
        )

        parsed = []
        for badge in badges_data:
            title = badge.get("title", "").strip()
            if not title:
                continue

            href = badge.get("href", "")
            m = re.search(r"/badges/(\d+)", href)
            b_id = (
                f"google-skills-badge-{m.group(1)}"
                if m
                else badge.get("id") or generate_badge_id(title, None)
            )
            verify = (
                f"https://www.skills.google{href}" if href.startswith("/") else href
            )

            dt = None
            earned_date = badge.get("earnedDate")
            if earned_date:
                dt = normalize_date_string(earned_date)

            raw_entry = {
                "id": b_id,
                "title": title,
                "name": title,
                "issuer": "Google Cloud",
                "issuer_name": "Google Cloud",
                "issued_at": dt,
                "issued_at_date": dt,
                "date": dt,
                "verify_url": verify,
                "url": verify,
                "type": "Google Skill Badge",
                "verification_type": "Google Skill Badge",
                "skills": [title],
            }
            try:
                parsed.append(GoogleBadgeItemModel(**raw_entry).model_dump(mode="json"))
            except ValidationError:
                pass

        if parsed:
            with_dates = sum(1 for b in parsed if b.get("issued_at"))
            logging.getLogger("google_skills").info(
                f"[THEATER] Playwright successfully retrieved {len(parsed)} badges ({with_dates} with dates)"
            )
            return parsed
        return []
    except Exception as e:
        logging.getLogger("google_skills").warning(
            f"[WARN] Playwright scraping failed: {e}"
        )
        return []


def fetch_google_skills_badges(profile_id: str) -> list[dict]:
    """Orchestrates fetching Google Skills badges via profile JSON/HTML endpoints or local fallbacks."""
    endpoints = [
        (f"https://www.skills.google/public_profiles/{profile_id}.json", True),
        (f"https://cloudskillsboost.google/public_profiles/{profile_id}.json", True),
        (f"https://www.skills.google/public_profiles/{profile_id}", False),
        (f"https://cloudskillsboost.google/public_profiles/{profile_id}", False),
    ]

    html_endpoint_accessible = False

    for url, is_json in endpoints:
        logging.getLogger("google_skills").info(
            f"[SYNC] Attempting fetch from Google Skills endpoint: {url}"
        )
        headers = dict(HEADERS)
        if not is_json:
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            )
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200:
                if not is_json:
                    html_endpoint_accessible = True
                if is_json or "json" in response.headers.get("Content-Type", ""):
                    try:
                        data = response.json()
                        raw_list = data.get(
                            "badges",
                            data.get("items", data if isinstance(data, list) else []),
                        )
                        parsed = []
                        for item in raw_list:
                            if isinstance(item, dict):
                                title = (
                                    item.get("title")
                                    or item.get("name")
                                    or item.get("badge_title")
                                )
                                dt = (
                                    item.get("earned_at")
                                    or item.get("issued_at")
                                    or item.get("date")
                                )
                                b_id = item.get("id") or generate_badge_id(
                                    str(title), str(dt)
                                )
                                verify = (
                                    item.get("verify_url")
                                    or item.get("url")
                                    or f"https://www.skills.google/public_profiles/{profile_id}"
                                )

                                raw_entry = {
                                    "id": str(b_id),
                                    "title": str(title),
                                    "name": str(title),
                                    "issuer": "Google Cloud",
                                    "issuer_name": "Google Cloud",
                                    "issued_at": dt,
                                    "issued_at_date": dt,
                                    "date": dt,
                                    "image_url": item.get("image_url")
                                    or item.get("icon"),
                                    "verify_url": verify,
                                    "url": verify,
                                    "type": item.get("type", "Google Skill Badge"),
                                    "verification_type": item.get(
                                        "type", "Google Skill Badge"
                                    ),
                                    "skills": item.get(
                                        "skills", [title] if title else ["Google Cloud"]
                                    ),
                                }
                                try:
                                    parsed.append(
                                        GoogleBadgeItemModel(**raw_entry).model_dump(
                                            mode="json"
                                        )
                                    )
                                except ValidationError:
                                    pass
                        if parsed:
                            logging.getLogger("google_skills").info(
                                f"[OK] Successfully retrieved {len(parsed)} badges via JSON endpoint."
                            )
                            return parsed
                    except json.JSONDecodeError:
                        logging.getLogger("google_skills").info(
                            f"[WARN] Endpoint {url} returned non-JSON response."
                        )
                else:
                    # HTML Scraper Fallback using BeautifulSoup
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(response.text, "html.parser")

                        badge_containers = soup.find_all(
                            class_=lambda x: (
                                x
                                and "profile-badge" in x.lower()
                                and "profile-badges" not in x.lower()
                            )
                        )

                        if not badge_containers:
                            badge_containers = soup.find_all(
                                class_=re.compile(
                                    r"public-profile-badge|badge-item|badge",
                                    re.IGNORECASE,
                                )
                            )

                        parsed = []
                        for container in badge_containers:
                            link_el = container.find(
                                "a", href=re.compile(r"/badges/\d+")
                            )

                            title_el = container.find(
                                class_=re.compile(
                                    r"ql-title|title|name|heading", re.IGNORECASE
                                )
                            )

                            date_el = container.find(
                                class_=re.compile(
                                    r"ql-body|date|earned|issued", re.IGNORECASE
                                )
                            )

                            img_el = container.find("img", src=True)

                            if title_el:
                                title = title_el.get_text(strip=True)

                                dt = None
                                if date_el:
                                    date_text = date_el.get_text(strip=True)
                                    earned_match = re.search(
                                        r"Earned\s+([A-Za-z]{3}\s+\d{1,2},?\s+\d{4})",
                                        date_text,
                                        re.IGNORECASE,
                                    )
                                    if earned_match:
                                        dt = normalize_date_string(
                                            earned_match.group(1)
                                        )

                                verify = (
                                    link_el["href"]
                                    if link_el
                                    else f"https://www.skills.google/public_profiles/{profile_id}"
                                )
                                if verify.startswith("/"):
                                    verify = f"https://www.skills.google{verify}"
                                m = re.search(r"/badges/(\d+)", verify)
                                b_id = (
                                    f"google-skills-badge-{m.group(1)}"
                                    if m
                                    else generate_badge_id(title, dt)
                                )

                                raw_entry = {
                                    "id": b_id,
                                    "title": title,
                                    "name": title,
                                    "issuer": "Google Cloud",
                                    "issuer_name": "Google Cloud",
                                    "issued_at": dt,
                                    "issued_at_date": dt,
                                    "date": dt,
                                    "image_url": img_el["src"] if img_el else None,
                                    "verify_url": verify,
                                    "url": verify,
                                    "type": "Google Skill Badge",
                                    "verification_type": "Google Skill Badge",
                                    "skills": [title],
                                }
                                try:
                                    parsed.append(
                                        GoogleBadgeItemModel(**raw_entry).model_dump(
                                            mode="json"
                                        )
                                    )
                                except ValidationError:
                                    pass
                        if parsed:
                            has_dates = any(b.get("issued_at") for b in parsed)
                            if not has_dates and PLAYWRIGHT_AVAILABLE:
                                logging.getLogger("google_skills").info(
                                    "[SYNC] No dates in static HTML; trying Playwright for JS-rendered dates..."
                                )
                                pw_parsed = fetch_google_skills_badges_playwright(
                                    profile_id, url
                                )
                                if pw_parsed:
                                    return pw_parsed
                            logging.getLogger("google_skills").info(
                                f"[OK] Successfully retrieved {len(parsed)} badges via HTML profile page."
                            )
                            return parsed
                    except Exception as parse_err:
                        logging.getLogger("google_skills").info(
                            f"[WARN] HTML parsing fallback for {url} did not yield badges: {parse_err}"
                        )
            else:
                logging.getLogger("google_skills").info(
                    f"[WARN] Endpoint {url} responded with HTTP {response.status_code}"
                )
        except requests.exceptions.RequestException as e:
            logging.getLogger("google_skills").info(
                f"[WARN] Network request to {url} skipped/failed: {e}"
            )

    if PLAYWRIGHT_AVAILABLE and html_endpoint_accessible:
        logging.getLogger("google_skills").info(
            "[SYNC] Trying Playwright for JS-rendered badges and dates..."
        )
        pw_parsed = fetch_google_skills_badges_playwright(profile_id)
        if pw_parsed:
            return pw_parsed

    # 2. Secondary Strategy: Fallback to local data files
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

    logging.getLogger("google_skills").error(
        "[FAIL] Failed to acquire Google Skills badges from network or local files."
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


# Backward-compatibility wrappers (for tests)
from loss_guard import execute_content_loss_guard as _execute_content
from loss_guard import execute_data_loss_guard as _execute_guard
from loss_guard import get_stored_archive_baseline_count as _get_count


def get_stored_archive_baseline_count(json_path: str, monolith_path: str) -> int:
    return _get_count("google-skills", json_path, monolith_path)


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    return _execute_guard(new_badges, "google-skills", output_file, ARCHIVE_MONOLITH)


def execute_content_loss_guard(*args, **kwargs):
    return _execute_content(*args, **kwargs)


# ==============================================================================
# PIPELINE CLASS
# ==============================================================================


class GoogleSkillsPipeline(PipelineBase):
    PLATFORM_NAME = "google-skills"
    PLATFORM_PREFIX = "google-skills"
    PLATFORM_DISPLAY_NAME = "Google Skills Credentials"
    ARCHIVE_DIR = "archives"
    README_PATH = "README.md"
    ARCHIVE_MONOLITH = os.path.join("archives", "google-skills-complete.md")
    MARKER_START = "<!-- GOOGLE_SKILLS_START -->"
    MARKER_END = "<!-- GOOGLE_SKILLS_END -->"

    TABLE_HEADERS: ClassVar[list[str]] = [
        "Date Earned",
        "Credential Name",
        "Issuer",
        "Verification Type",
    ]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---", ":---:"]

    GOOGLE_PROFILE_ID = GOOGLE_PROFILE_ID
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
        """Orchestrates fetching Google Skills badges via profile JSON/HTML endpoints or local fallbacks."""
        # Load local badges for fallback
        local_badges = []
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
                    break

        raw_badges = fetch_google_skills_badges(self.GOOGLE_PROFILE_ID)

        if raw_badges is None or len(raw_badges) == 0:
            self.logger.warning(
                f"[WARN] Google Skills API returned 0 badges or failed; "
                f"retaining the previous local dataset ({len(local_badges)} badges)."
            )
            return local_badges
        else:
            return raw_badges

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

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        """Format single record for markdown table: (row_text, date)."""
        date_str = str(record.get("issued_at") or "2026-01-01").strip()
        title = str(record.get("title") or "Unknown Credential").strip()
        verify_url = record.get("verify_url")
        issuer = str(record.get("issuer") or "Google").strip()
        v_type = str(record.get("type") or "Google Skill Badge").strip()
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

        index_raw = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-skills-index.md"
        profile_url = (
            f"https://www.skills.google/public_profiles/{self.GOOGLE_PROFILE_ID}"
        )

        readme_lines = [
            "### Google Skills Credentials",
            "",
            f"**Public Profile:** [Verify Google Skills Profile]({profile_url})",
            "",
            f"**Total Portfolio Credentials:** {total_count}",
            f"**Total Verified Skills Mapped:** {total_skills}",
            "",
        ]

        if INTERNAL_STATS and any(v > 0 for v in INTERNAL_STATS.values()):
            readme_lines.extend(
                [
                    "#### Google Skills Learning Statistics",
                    "",
                    "| Metric | Count |",
                    "| :--- | :---: |",
                ]
            )
            for activity_type, count in sorted(INTERNAL_STATS.items()):
                readme_lines.append(f"| **{activity_type}** | {count:,} |")
            readme_lines.append("")

        readme_lines.extend(
            [
                "#### Latest Earned Credentials",
                "",
                f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/google-skills-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]{{LATEST_SLICE_NORMAL}} ([Raw]{{LATEST_SLICE_RAW}}), or [Monolithic File](./archives/google-skills-complete.md).",
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
        """Build validation payload with Google Skills-specific fields."""
        layer_metadata = {}
        try:
            from layer_manifest import load_manifest

            manifest = load_manifest()
            if "google-skills" in manifest.platforms:
                platform = manifest.platforms["google-skills"]
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
            "profile_id": self.GOOGLE_PROFILE_ID,
            "total_count": len(records),
            "badges": records,
            "_layer_metadata": layer_metadata,
        }

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records for L2 archive JSON."""
        return records

    def persist_validation(self, records):
        """Persist validated data with Google Skills-specific filename."""
        os.makedirs(self.VALIDATION_DIR, exist_ok=True)
        validation_file = self.OUTPUT_FILE

        payload = self.get_validation_payload(records)
        try:
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self.logger.info(f"[SAVE] Full data persisted: '{validation_file}'")
        except Exception as e:
            self.logger.warning(f"[WARN] Could not persist validation data: {e}")


# Module-level main function for backward compat
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    GoogleSkillsPipeline().run()


if __name__ == "__main__":
    main()
    # Sync fixtures for test consistency
    try:
        from scripts.sync_fixtures import sync_fixtures

        sync_fixtures("google-skills")
    except Exception as exc:
        logging.getLogger("google_skills").warning(
            f"[WARN] Fixture sync failed (non-fatal): {exc}"
        )
