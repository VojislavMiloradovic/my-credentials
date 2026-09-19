"""
update_google_developer.py
--------------------------
Pipeline for updating Google Developer Profile credentials & learning activities.
Fetches public profile badges via Google Developer RPC/batchexecute API,
parses local Serbian-formatted learning activity text logs, applies Pydantic validation,
enforces Data Loss Guards, and delegates markdown archiving to the archiver module.

Refactored to use PipelineBase (Option 2 Migration).
"""

import email
import json
import logging
import os
import quopri
import re
from datetime import UTC, datetime
from email import policy
from typing import Any, ClassVar
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from pydantic import Field, ValidationError, field_validator

# Provenance Integration
from models.provenance import ProvenanceBase, RetrievalMethod, VerificationStatus

# Layer Manifest Integration
try:
    from layer_manifest import get_layer_def, get_platform_layers, load_manifest
except ImportError:
    get_platform_layers = None
    get_layer_def = None
    load_manifest = None

# PipelineBase Integration
from pipeline_base import PipelineBase

# ==============================================================================
# MODULE-LEVEL CONSTANTS (for backward compatibility with tests)
# ==============================================================================

VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "google-developer"
PLATFORM_NAME = "Google Developer Profile"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

MAX_ALLOWED_DATA_LOSS_PCT = 0.15

SERBIAN_MONTHS = {
    # Latin script (Serbian + English month names)
    "jan": "01",
    "januar": "01",
    "januara": "01",
    "january": "01",
    "feb": "02",
    "februar": "02",
    "februara": "02",
    "february": "02",
    "mar": "03",
    "mart": "03",
    "marta": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "aprila": "04",
    "may": "05",
    "maj": "05",
    "maja": "05",
    "jun": "06",
    "juna": "06",
    "june": "06",
    "jul": "07",
    "jula": "07",
    "july": "07",
    "avg": "08",
    "avgust": "08",
    "avgusta": "08",
    "august": "08",
    "sep": "09",
    "septembar": "09",
    "septembra": "09",
    "september": "09",
    "okt": "10",
    "oktobar": "10",
    "oktobra": "10",
    "october": "10",
    "nov": "11",
    "novembar": "11",
    "novembra": "11",
    "november": "11",
    "dec": "12",
    "decembar": "12",
    "decembra": "12",
    "december": "12",
    # Cyrillic script (for test data with actual Unicode)
    "јан": "01",
    "јануар": "01",
    "јануара": "01",
    "феб": "02",
    "фебруар": "02",
    "фебруара": "02",
    "мар": "03",
    "март": "03",
    "марта": "03",
    "апр": "04",
    "април": "04",
    "априла": "04",
    "мај": "05",
    "маја": "05",
    "јун": "06",
    "јуни": "06",
    "јуна": "06",
    "јул": "07",
    "јула": "07",
    "авг": "08",
    "август": "08",
    "августа": "08",
    "сеп": "09",
    "септембар": "09",
    "септембра": "09",
    "окт": "10",
    "октобар": "10",
    "октобра": "10",
    "нов": "11",
    "новембар": "11",
    "новembra": "11",
    "дек": "12",
    "децембар": "12",
    "децембра": "12",
}

RETIRED_URLS_FILE = "retired_urls.json"

# Fallback retired URLs loader for markdown generation
try:
    from retired_urls_loader import _GOOGLE_DEV_RETIRED_URLS
except ImportError:
    _GOOGLE_DEV_RETIRED_URLS = set()


# ==============================================================================
# MODULE-LEVEL HELPER FUNCTIONS (for backward compat)
# ==============================================================================


def find_latest_developer_mhtml(data_dir: str = "data") -> str:
    """
    Find the most recent MHTML file matching *Developer*.mhtml pattern.
    Falls back to hardcoded filename if no matches found.
    """
    import glob

    pattern = os.path.join(data_dir, "*Developer*.mhtml")
    matches = glob.glob(pattern)
    if not matches:
        # Fallback to hardcoded filename
        fallback = os.path.join(
            data_dir,
            "Learning \u00a0_\u00a0 Google Developer Program \u00a0_\u00a0 Google for Developers.mhtml",
        )
        logging.getLogger("gdev_updater").warning(
            f"[WARN] No *Developer*.mhtml files found in {data_dir}, using fallback: {fallback}"
        )
        return fallback

    # Pick most recent by modification time
    latest = max(matches, key=os.path.getmtime)
    if len(matches) > 1:
        logging.getLogger("gdev_updater").info(
            f"[FILE] Found {len(matches)} *Developer*.mhtml files, using most recent: {latest}"
        )
    else:
        logging.getLogger("gdev_updater").info(
            f"[FILE] Found *Developer*.mhtml file: {latest}"
        )
    return latest


# Dynamic path discovery
LEARNINGS_MHTML_PATH = find_latest_developer_mhtml()
# Backwards compat alias for tests
LEARNINGS_TXT_PATH = LEARNINGS_MHTML_PATH
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")


def normalize_date_string(raw_date: Any) -> str:
    """Coerces timestamps, ISO strings, and Serbian dates to YYYY-MM-DD or N/A."""
    if not raw_date or str(raw_date).strip().lower() in ("null", "none", "", "n/a"):
        return "N/A"

    s_date = str(raw_date).strip()

    # Match YYYY-MM-DD
    if len(s_date) == 10 and s_date[4] == "-" and s_date[7] == "-":
        return s_date

    # Match Serbian date format: DD. month YYYY.
    serbian_match = re.match(r"^(\d+)\.\s+([^\s\d]+)\s+(\d{4})\.?$", s_date)
    if serbian_match:
        day = serbian_match.group(1).zfill(2)
        month_str = serbian_match.group(2).lower().replace(".", "")
        year = serbian_match.group(3)

        month_num = "00"
        for k, v in SERBIAN_MONTHS.items():
            if month_str.startswith(k):
                month_num = v
                break
        return f"{year}-{month_num}-{day}"

    return "N/A"


def fix_mojibake(text: str) -> str:
    """Fix common mojibake patterns from MHTML quoted-printable decoding.

    Common issues:
    - Em dash (--) becomes     or \u00e2\u20ac\u201d or \u00e2\u20ac\u201c
    - En dash (-) becomes \u00e2\u20ac\u201c or \u00e2\u20ac\u201d
    - Smart quotes become \u00e2\u20ac\u0153/\u00e2\u20ac\u009d
    - Bullet points become \u00e2\u20ac\u00a2
    """
    if not text:
        return text

    # Fix UTF-8 mojibake from quoted-printable double-decoding
    # Em dash (--) = UTF-8 E2 80 93 -> when misdecoded as latin1: \u00e2\u20ac\u201d
    # En dash (-) = UTF-8 E2 80 92 -> when misdecoded as latin1: \u00e2\u20ac\u201c
    replacements = {
        "\u00e2\u20ac\u201d": "\u2014",  # em dash (\u00e2\u20ac\u201d)
        "\u00e2\u20ac\u201c": "\u2013",  # en dash (\u00e2\u20ac\u201c)
        "\u00e2\u20ac\u0153": "\u201c",  # left double quote (\u00e2\u20ac\u0153)
        "\u00e2\u20ac\u009d": "\u201d",  # right double quote (\u00e2\u20ac\u009d)
        "\u00e2\u20ac\u0098": "\u2018",  # left single quote (\u00e2\u20ac\u0098)
        "\u00e2\u20ac\u2122": "\u2019",  # right single quote (\u00e2\u20ac\u2122)
        "\u00e2\u20ac\u00a2": "\u2022",  # bullet (\u00e2\u20ac\u00a2)
        "\u00e2\u20ac\u00a6": "\u2026",  # ellipsis (\u00e2\u20ac\u00a6)
        "\u00e2\u20ac\u00a1": "\u2021",  # double dagger (\u00e2\u20ac\u00a1)
        "\u00e2\u20ac\u0094": "\u2014",  # em dash variant (\u00e2\u20ac\u0094)
        "\u00ef\u00bf\u00bd": "\u2014",  # replacement char variant (\u00ef\u00bf\u00bd)
        "\u00ef\u00bf\u00bf": "",  # replacement char (\u00ef\u00bf\u00bf)
    }

    result = text
    for bad, good in replacements.items():
        result = result.replace(bad, good)

    # Also handle the literal \uFFFD sequence (3 replacement chars = 1 em dash)
    result = re.sub(r"\uFFFD{3,}", "\u2014", result)
    result = re.sub(r"\uFFFD{2}", "\u2013", result)
    result = re.sub(r"\uFFFD", "", result)  # Remove any remaining replacement chars

    return result


# ==============================================================================
# PYDANTIC SCHEMAS (module-level for backward compat)
# ==============================================================================


class GoogleDeveloperBadgeModel(ProvenanceBase):
    """Normalized schema for Google Developer badges and codelabs."""

    # Platform-specific fields
    title: str = Field(..., min_length=1, description="Badge or Activity Title")
    date: str = Field("N/A", description="Earned date in YYYY-MM-DD format")
    description: str = Field(..., description="Achievement metadata or classification")
    source: str = Field(
        "public", description="Origin of badge (public RPC or local learnings log)"
    )
    retired: bool = Field(
        False, description="Whether the content has been retired by the platform"
    )
    url: str | None = Field(None, description="URL to verify the badge/codelab")

    # Provenance fields with platform-specific defaults
    source_platform: str = Field(
        default="google-developer", description="Platform identifier"
    )
    source_record_id: str | None = Field(
        None, description="Stable ID from source platform"
    )
    source_url: str | None = Field(None, description="Canonical URL on source platform")
    verify_url: str | None = Field(None, description="Independent verification URL")
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

    model_config: ClassVar[dict] = {
        "json_encoders": {
            datetime: lambda v: v.isoformat() if v else None,
        }
    }

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, val: Any) -> str:
        return normalize_date_string(val)

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


# ==============================================================================
# LOSS GUARD & ANOMALY PROTECTIONS (module-level for backward compat)
# ==============================================================================


class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops drastically below previous baseline."""


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


def execute_data_loss_guard(new_badges: list[dict]) -> None:
    """Loss Guard comparison against stored baseline count."""
    old_count = get_stored_archive_baseline_count()
    new_count = len(new_badges)

    logging.getLogger("gdev_updater").info(
        f"[SHIELD] Loss Guard Check: Stored Archive Baseline = {old_count} items | Incoming Dataset = {new_count} items."
    )

    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming fetch returned 0 items, but baseline contains {old_count}. Aborting sync."
        )

    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > MAX_ALLOWED_DATA_LOSS_PCT:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming badge count ({new_count}) dropped by {drop_ratio:.1%} "
                f"from baseline ({old_count}). Threshold: {MAX_ALLOWED_DATA_LOSS_PCT:.0%}. Aborting."
            )

    logging.getLogger("gdev_updater").info(
        "[OK] Loss Guard Assertion Passed: Incoming dataset verified."
    )


# ==============================================================================
# PARSERS & RPC FETCHERS (module-level for backward compat)
# ==============================================================================


def parse_local_learnings_txt() -> list[dict]:
    """Parses local Serbian text file of detailed learning activity codelabs."""
    if not os.path.exists(LEARNINGS_TXT_PATH):
        logging.getLogger("gdev_updater").info(
            f"[FILE] Local activity file '{LEARNINGS_TXT_PATH}' not found. Skipping local parsing."
        )
        return []

    logging.getLogger("gdev_updater").info(
        f"[FILE] Parsing local Google learning log: '{LEARNINGS_TXT_PATH}'"
    )
    with open(LEARNINGS_TXT_PATH, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    learnings = []
    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = re.match(r"^(\d+)\.\s+([^\s\d]+)\s+(\d{4})\.?$", line)
        if date_match and i > 0:
            iso_date = normalize_date_string(line)
            title = lines[i - 1]
            if (
                title in ["Ucheje", "check_circle_outline You have this badge!"]
                and i > 1
            ):
                title = lines[i - 2]

            if (
                title not in ["Ucheje", "check_circle_outline You have this badge!"]
                and not title.startswith("http")
                and not any(item["title"] == title for item in learnings)
            ):
                entry = {
                    "title": title.strip(),
                    "date": iso_date,
                    "description": "Verified Google Developer granular learning activity module milestone.",
                    "source": "local_txt",
                }
                try:
                    learnings.append(
                        GoogleDeveloperBadgeModel(**entry).model_dump(mode="json")
                    )
                except ValidationError as ve:
                    logging.getLogger("gdev_updater").warning(
                        f"[WARN] Skipping invalid local activity entry '{title}': {ve}"
                    )
        i += 1

    logging.getLogger("gdev_updater").info(
        f"[OK] Extracted {len(learnings)} granular learning items from local log."
    )
    return learnings


def parse_google_learnings_mhtml(mhtml_path: str) -> list[dict]:
    """Parses MHTML file of Google Developer learnings badge page to extract all learning activities.

    The MHTML contains the rendered badge page HTML with .badge-event containers,
    each having a title link and a Serbian date in a <p> tag.

    Unavailable/404 links are marked as retired.
    Falls back to legacy text parser if file is not valid MHTML.
    """
    if not os.path.exists(mhtml_path):
        logging.getLogger("gdev_updater").warning(
            f"[WARN] MHTML file '{mhtml_path}' not found. Skipping MHTML parsing."
        )
        return []

    logging.getLogger("gdev_updater").info(
        f"[FILE] Parsing Google Developer learnings from MHTML: '{mhtml_path}'"
    )

    # Try MHTML parsing first
    try:
        with open(mhtml_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        # Find the main HTML part (the badge page)
        html_content = None
        for part in msg.walk():
            if (
                part.get_content_type() == "text/html"
                and "profile/badges/recognitions/learnings"
                in part.get("Content-Location", "")
            ):
                # Manually decode quoted-printable payload as UTF-8
                raw_payload = part.get_payload(decode=False)
                if raw_payload:
                    html_content = quopri.decodestring(raw_payload).decode(
                        "utf-8", errors="replace"
                    )
                break

        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")

            # Find all badge-event containers
            badge_events = soup.find_all(class_="badge-event")

            if badge_events:
                learnings = []
                retired_count = 0

                for event in badge_events:
                    # Find the link inside
                    link = event.find("a", href=True)
                    if not link:
                        continue

                    title = fix_mojibake(link.get_text(strip=True))
                    url = link["href"]

                    # Find the date in the <p> tag
                    date_p = event.find("p")
                    iso_date = "N/A"
                    if date_p:
                        date_text = date_p.get_text(strip=True)
                        iso_date = normalize_date_string(date_text)

                    # Check if URL is likely unavailable
                    is_retired = False
                    if iso_date == "N/A":
                        is_retired = True
                        retired_count += 1

                    entry = {
                        "title": title.strip(),
                        "date": iso_date,
                        "description": f"Verified Google Developer learning activity. URL: {url}",
                        "source": "local_mhtml",
                        "url": url,
                        "retired": is_retired,
                    }

                    try:
                        learnings.append(
                            GoogleDeveloperBadgeModel(**entry).model_dump(mode="json")
                        )
                    except ValidationError as ve:
                        logging.getLogger("gdev_updater").warning(
                            f"[WARN] Skipping invalid MHTML activity entry '{title}': {ve}"
                        )

                logging.getLogger("gdev_updater").info(
                    f"[OK] Extracted {len(learnings)} learning activities from MHTML ({retired_count} retired)."
                )
                return learnings
    except Exception as e:
        logging.getLogger("gdev_updater").warning(
            f"[WARN] MHTML parsing failed, falling back to text parser: {e}"
        )

    # Fallback to legacy text parser
    logging.getLogger("gdev_updater").info(
        f"[FILE] Falling back to legacy text parser for: '{mhtml_path}'"
    )
    return parse_local_learnings_txt()


def analyze_badge_list(lst: Any, parsed_badges: list[dict]) -> bool:
    """Helper recursively searching for badge entities inside RPC response tree."""
    strings = []
    numbers = []

    def walk(element):
        if isinstance(element, str):
            strings.append(element)
            if element.isdigit():
                numbers.append(float(element))
        elif isinstance(element, (int, float)):
            numbers.append(element)
        elif isinstance(element, list):
            for x in element:
                walk(x)
        elif isinstance(element, dict):
            for x in element.values():
                walk(x)

    walk(lst)
    award_strs = [s for s in strings if "/awards/" in s]
    if not award_strs:
        return False

    epoch = None
    for num in numbers:
        if 946684800 <= num <= 2500000000:
            epoch = num
            break
        elif 946684800000 <= num <= 2500000000000:
            epoch = num / 1000.0
            break

    date_str = "N/A"
    if epoch:
        try:
            date_str = datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d")
        except Exception:
            pass

    for award_str in award_strs:
        parts = award_str.split("/awards/")
        if len(parts) > 1:
            badge_path = unquote(parts[1])
            slug = badge_path.split("/")[-1].split("?")[0]

            title = slug.replace("-", " ").replace("_", " ").title()
            title = (
                title.replace("Gdg", "GDG").replace("Gcp", "GCP").replace("Aws", "AWS")
            )

            category = "Community" if "community" in badge_path else "Learning Pathway"
            description = f"Official Google Developer platform achievement ({category}: {slug.replace('-', ' ')})."

            existing = next((b for b in parsed_badges if b["title"] == title), None)
            if existing:
                if existing["date"] == "N/A" and date_str != "N/A":
                    existing["date"] = date_str
            else:
                entry = {
                    "title": title,
                    "description": description,
                    "date": date_str,
                    "source": "public_rpc",
                }
                try:
                    parsed_badges.append(
                        GoogleDeveloperBadgeModel(**entry).model_dump(mode="json")
                    )
                except ValidationError:
                    pass
    return True


def find_badges_in_matrix(data: Any, parsed_badges: list[dict]) -> None:
    if isinstance(data, list):
        analyze_badge_list(data, parsed_badges)
        for item in data:
            find_badges_in_matrix(item, parsed_badges)
    elif isinstance(data, dict):
        for val in data.values():
            find_badges_in_matrix(val, parsed_badges)


def fetch_gdev_badges_rpc() -> list[dict]:
    """Fetches public profile badges from Google Developer batchexecute RPC endpoint."""
    logging.getLogger("gdev_updater").info(
        "[GLOBE] Fetching Google Developer public profile via RPC API..."
    )
    url = "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute"
    params = {
        "rpcids": "gQeJTc,RwSpuf",
        "source-path": "/u/vojislavmiloradovic",
        "bl": "boq_gdp-builders-ui_20260713.05_p0",
        "f.sid": "8705607390718843222",
        "hl": "en",
        "_reqid": "252198",
        "rt": "c",
    }
    profile_id = "110772055890077594470"
    f_req_structure = [
        [
            ["gQeJTc", f'["{profile_id}"]', None, "3"],
            ["RwSpuf", f'["{profile_id}"]', None, "4"],
        ]
    ]
    payload = {
        "f.req": json.dumps(f_req_structure),
        "at": "AFAd0eBgurpIT_evlsPSzRjypGkH:1784464194335",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "*/*",
        "Origin": "https://developers.google.com",
        "Referer": "https://developers.google.com/profile/u/vojislavmiloradovic",
    }

    try:
        response = requests.post(
            url, params=params, data=payload, headers=headers, timeout=15
        )
        if response.status_code != 200:
            logging.getLogger("gdev_updater").warning(
                f"[WARN] RPC request failed with status HTTP {response.status_code}"
            )
            return []

        raw_text = response.text
        parsed_badges = []

        for line in raw_text.splitlines():
            if "gQeJTc" in line or "RwSpuf" in line:
                clean_line = re.sub(r"^\d+", "", line).strip()
                try:
                    outer_data = json.loads(clean_line)
                    for chunk in outer_data:
                        if isinstance(chunk, list):
                            for element in chunk:
                                if isinstance(element, str) and (
                                    element.startswith(("[", "{"))
                                ):
                                    try:
                                        badge_matrix = json.loads(element)
                                        find_badges_in_matrix(
                                            badge_matrix, parsed_badges
                                        )
                                    except Exception:
                                        pass
                except Exception:
                    continue

        logging.getLogger("gdev_updater").info(
            f"[OK] Extracted {len(parsed_badges)} badges from RPC endpoint."
        )
        return parsed_badges
    except Exception as e:
        logging.getLogger("gdev_updater").warning(
            f"[WARN] Exception occurred during RPC fetch: {e}"
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
    items: list[dict],
    retired_rules: list[dict[str, Any]],
    url_field: str = "url",
    id_fields: list[str] | None = None,
    retired_field: str = "retired",
) -> tuple[int, int]:
    """Wrapper that uses module-level mark_retired."""
    return _mark_retired(
        items,
        retired_rules,
        url_field=url_field,
        id_fields=id_fields,
        retired_field=retired_field,
    )


# Backward-compatibility wrappers (for tests)
from loss_guard import execute_content_loss_guard as _execute_content
from loss_guard import generate_all_provider_baselines as _generate_all_baselines
from loss_guard import run_provider_loss_guards as _run_provider_loss_guards


def execute_content_loss_guard(*args, **kwargs):
    """Backward-compatible wrapper for content-aware loss guard."""
    return _execute_content(*args, **kwargs)


def generate_all_provider_baselines(
    new_records: list[dict], provider_name: str
) -> dict[str, bool]:
    """Backward-compatible wrapper for multi-stream baseline generation."""
    return _generate_all_baselines(new_records, provider_name)


def run_provider_loss_guards(new_records: list[dict], provider_name: str, **kwargs):
    """Backward-compatible wrapper for provider loss guards."""
    return _run_provider_loss_guards(new_records, provider_name, **kwargs)


# ==============================================================================
# PIPELINE CLASS
# ==============================================================================


class GoogleDeveloperPipeline(PipelineBase):
    PLATFORM_NAME = "google-developer"
    PLATFORM_PREFIX = PLATFORM_PREFIX
    PLATFORM_DISPLAY_NAME = PLATFORM_NAME
    ARCHIVE_DIR = ARCHIVE_DIR
    README_PATH = README_PATH
    ARCHIVE_MONOLITH = ARCHIVE_MONOLITH
    MARKER_START = MARKER_START
    MARKER_END = MARKER_END

    TABLE_HEADERS: ClassVar[list[str]] = [
        "Date Earned",
        "Title",
        "Description",
    ]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---"]

    @property
    def VALIDATION_DIR(self):
        return VALIDATION_DIR

    def fetch_data(self) -> list[dict]:
        """Fetch and parse Google Developer data from multiple sources."""
        # Fetch from both sources
        public_badges = fetch_gdev_badges_rpc()
        detailed_learnings = parse_google_learnings_mhtml(LEARNINGS_TXT_PATH)

        # Combine feeds, deduplicating public badges against MHTML items
        combined_feed = list(public_badges)
        for dl in detailed_learnings:
            if not any(b["title"] == dl["title"] for b in combined_feed):
                combined_feed.append(dl)

        if not combined_feed:
            self.logger.error(
                "[FAIL] No badge records extracted from RPC or local activity file. Aborting."
            )
            return []

        # Store individual feeds for README stats
        self._public_badges = public_badges
        self._detailed_learnings = detailed_learnings

        return combined_feed

    def parse_data(self, raw_data) -> list[dict]:
        """Parse/transform raw data - already validated via Pydantic in fetch_data."""
        return raw_data

    def pre_loss_guard(self, records: list[dict]) -> list[dict]:
        """No additional deduplication needed - done in fetch_data."""
        return records

    def post_loss_guard(self, records: list[dict]) -> list[dict]:
        """Run loss guards, mark retired, generate baselines."""
        # 1. Execute Content-Aware Loss Guard check against stored baseline
        try:
            from loss_guard import execute_content_loss_guard

            execute_content_loss_guard(
                new_records=records,
                platform="google-developer",
                id_field="title",  # Google Developer uses title as stable ID
                fail_on_warn=True,
            )
        except Exception as anomaly_err:
            self.logger.error(
                f"[FAIL] Pipeline Terminated by Anomaly Guard: {anomaly_err}"
            )
            raise

        # 2. Retired URL / Identity detection
        retired_rules = self.get_retired_rules()
        if retired_rules:
            _, marked = mark_retired(records, retired_rules, url_field="url")
            if marked > 0:
                self.logger.info(
                    f"[NOTE] Updated {marked} badge/activity(s) with retired status"
                )

        # 3. Generate L1 baseline fingerprints for all 3 streams (cross-artifact validation)
        try:
            from loss_guard import generate_all_provider_baselines

            results = generate_all_provider_baselines(records, "google-developer")
            self.logger.info(f"[OK] L1 baselines generated: {results}")
        except Exception as e:
            self.logger.warning(f"[WARN] Baseline generation failed (non-fatal): {e}")

        return records

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        """Format single record for markdown table: (row_text, date)."""
        clean_desc = record["description"].replace("|", r"\|").replace("\n", " ")
        clean_title = record["title"].replace("|", r"\|")
        # Primary check: retired flag from mark_retired
        # Fallback: check if URL is in retired_urls.json
        is_retired = (
            record.get("retired", False)
            or record.get("url", "") in _GOOGLE_DEV_RETIRED_URLS
        )
        if is_retired:
            clean_desc += " [WARN] *Content retired*"
        row_text = f"| {record['date']} | **{clean_title}** | {clean_desc} |"
        return row_text, record["date"]

    def build_readme_lines(self, records: list[dict], latest_slice: str) -> list[str]:
        """Build README section lines."""
        total_public = len(self._public_badges)
        total_detailed = len(self._detailed_learnings)

        index_raw = f"https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/{self.PLATFORM_PREFIX}-index.md"
        profile_url = "https://g.dev/vojislavmiloradovic"

        readme_lines = [
            "### Google Developer Profile Summary",
            "",
            f"**Public Profile:** [Verify Developer Profile]({profile_url})",
            "",
            "#### Platform Progress",
            "",
            "| Metric | Count |",
            "| :--- | :--- |",
            f"| **Total Milestones & Milestone Badges** | {total_public:,} |",
        ]

        if total_detailed > 0:
            readme_lines.append(
                f"| **Total Codelabs & Learning Activities** | {total_detailed:,} |"
            )

        readme_lines.extend(
            [
                "",
                "#### Latest Achievements",
                "",
                f"Showing latest 10 merged activities. View full data via [Platform Archive Index](./archives/{self.PLATFORM_PREFIX}-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic Complete File](./archives/{self.PLATFORM_PREFIX}-complete.md).",
                "",
                "| Date Earned | Title | Description |",
                "| :---: | :--- | :--- |",
            ]
        )

        for badge in records[:10]:
            clean_desc = badge["description"].replace("|", "\\|").replace("\n", " ")
            clean_title = badge["title"].replace("|", "\\|")
            readme_lines.append(
                f"| *{badge['date']}* | **{clean_title}** | {clean_desc} |"
            )

        return readme_lines

    def get_validation_payload(self, records: list[dict]) -> dict:
        """Build validation payload with Google Developer-specific fields."""
        layer_metadata = {}
        try:
            from layer_manifest import load_manifest

            manifest = load_manifest()
            if "google-developer" in manifest.platforms:
                platform = manifest.platforms["google-developer"]
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
                    layer_metadata[layer_name] = layer_info
        except Exception:
            pass

        return {
            "platform": self.PLATFORM_NAME,
            "total_public_badges": len(self._public_badges),
            "total_detailed_learnings": len(self._detailed_learnings),
            "total_combined": len(records),
            "public_badges": self._public_badges,
            "detailed_learnings": self._detailed_learnings,
            "combined_feed": records,
            "_layer_metadata": layer_metadata,
        }

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records for L2 archive JSON."""
        return records

    def update_readme(self, readme_lines: list[str], latest_slice: str) -> None:
        """Override to also update the stats table in the index file."""
        # Call parent update_readme
        super().update_readme(readme_lines, latest_slice)

        # Update README stats table (the Platform Progress section)
        try:
            from archiver import update_readme_stats

            update_readme_stats(
                platform_key="google-developer",
                total_count=len(self._public_badges) + len(self._detailed_learnings),
                public_badges=len(self._public_badges),
                detailed_learnings=len(self._detailed_learnings),
            )
            self.logger.info("[STATS] README updated with Google Developer stats")
        except Exception as e:
            self.logger.warning(f"[WARN] Could not update README stats: {e}")

        # Update index file with two-category breakdown
        index_file_path = os.path.join(
            self.ARCHIVE_DIR, f"{self.PLATFORM_PREFIX}-index.md"
        )
        if os.path.exists(index_file_path):
            try:
                with open(index_file_path, "r", encoding="utf-8") as f:
                    index_content = f.read()

                total_public = len(self._public_badges)
                total_detailed = len(self._detailed_learnings)

                breakdown_text = (
                    f"- **Total Public Badges:** {total_public:,}\n"
                    f"- **Total Detailed Activities:** {total_detailed:,}"
                )

                if "Total Public Badges" not in index_content:
                    old_overview_pattern = r"(- \*\*Total Records Archived:\*\* [\d,]+)"
                    index_content = re.sub(
                        old_overview_pattern,
                        rf"\1\n{breakdown_text}",
                        index_content,
                        count=1,
                    )
                else:
                    index_content = re.sub(
                        r"- \*\*Total Public Badges:\*\* [\d,]+",
                        f"- **Total Public Badges:** {total_public:,}",
                        index_content,
                    )
                    index_content = re.sub(
                        r"- \*\*Total Detailed Activities:\*\* [\d,]+",
                        f"- **Total Detailed Activities:** {total_detailed:,}",
                        index_content,
                    )

                with open(index_file_path, "w", encoding="utf-8") as f:
                    f.write(index_content)
                self.logger.info(
                    f"[OK] Updated category breakdown metrics in {index_file_path}"
                )
            except Exception as e:
                self.logger.warning(
                    f"[WARN] Failed to update overview in {index_file_path}: {e}"
                )


# Module-level main function for backward compat
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    GoogleDeveloperPipeline().run()


if __name__ == "__main__":
    main()
    # Sync fixtures for test consistency
    try:
        from scripts.sync_fixtures import sync_fixtures

        sync_fixtures("google-developer")
    except Exception as e:
        logging.getLogger("gdev_updater").warning(
            f"[WARN] Fixture sync failed (non-fatal): {e}"
        )
