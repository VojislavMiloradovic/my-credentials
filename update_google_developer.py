"""
update_google_developer.py
--------------------------
Pipeline for updating Google Developer Profile credentials & learning activities.
Fetches public profile badges via Google Developer RPC/batchexecute API,
parses local Serbian-formatted learning activity text logs, applies Pydantic validation,
enforces Data Loss Guards, and delegates markdown archiving to the archiver module.
"""

import email
import json
import logging
import os
import quopri
import re
import sys
from datetime import UTC, datetime
from email import policy
from typing import Any
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError, field_validator

# Archive Integration Helper
try:
    from archiver import (
        RAW_BASE_DEFAULT,
        generate_platform_archive,
        safe_write_file,
        update_readme_stats,
    )
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

    def update_readme_stats(*args, **kwargs):
        """Fallback no-op for update_readme_stats."""
        return


# Content-Aware Loss Guard
try:
    from loss_guard import PipelineDataLossAnomaly, execute_content_loss_guard
except ImportError:
    # Fallback if loss_guard not available
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

# Fallback retired URLs loader for markdown generation
try:
    from retired_urls_loader import _GOOGLE_DEV_RETIRED_URLS
except ImportError:
    _GOOGLE_DEV_RETIRED_URLS = set()


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
    url_field: str = "url",
    id_fields: list[str] | None = None,
    retired_field: str = "retired",
) -> tuple[int, int]:
    """Mark items as retired if their ID or URL matches known retired rules."""
    if not retired_rules:
        return len(items), 0
    search_id_fields = id_fields or ["id", "title", "url"]
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
logger = logging.getLogger("gdev_updater")

# Configuration Constants
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "google-developer"
PLATFORM_NAME = "Google Developer Profile"
# MHTML file with Google Developer learnings badge page (replaces google_learnings.txt)
LEARNINGS_MHTML_PATH = os.path.join(
    "data",
    "Learning \u00a0_\u00a0 Google Developer Program \u00a0_\u00a0 Google for Developers.mhtml",
)
# Backwards compat alias for tests
LEARNINGS_TXT_PATH = LEARNINGS_MHTML_PATH
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-complete.md")

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

MAX_ALLOWED_DATA_LOSS_PCT = 0.15  # Guard threshold for dataset drop protection

SERBIAN_MONTHS = {
    "јан": "01",
    "јануар": "01",
    "јануара": "01",
    "jan": "01",
    "januar": "01",
    "januara": "01",
    "феб": "02",
    "фебруар": "02",
    "фебруара": "02",
    "feb": "02",
    "februar": "02",
    "februara": "02",
    "мар": "03",
    "март": "03",
    "марта": "03",
    "mar": "03",
    "mart": "03",
    "marta": "03",
    "апр": "04",
    "април": "04",
    "априла": "04",
    "apr": "04",
    "april": "04",
    "aprila": "04",
    "мај": "05",
    "маја": "05",
    "maj": "05",
    "maja": "05",
    "јун": "06",
    "јуна": "06",
    "jun": "06",
    "juna": "06",
    "јул": "07",
    "јула": "07",
    "jul": "07",
    "jula": "07",
    "авг": "08",
    "август": "08",
    "августа": "08",
    "avg": "08",
    "august": "08",
    "augusta": "08",
    "сеп": "09",
    "септембар": "09",
    "септембара": "09",
    "sep": "09",
    "septembar": "09",
    "septembra": "09",
    "окт": "10",
    "октобар": "10",
    "октобара": "10",
    "okt": "10",
    "oktobar": "10",
    "oktobra": "10",
    "нов": "11",
    "новембар": "11",
    "новембара": "11",
    "nov": "11",
    "novembar": "11",
    "novembra": "11",
    "дец": "12",
    "децембар": "12",
    "децембара": "12",
    "dec": "12",
    "decembar": "12",
    "decembra": "12",
}


# ==============================================================================
# PYDANTIC SCHEMAS & DATE COERCION
# ==============================================================================


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
    - Em dash (—) becomes ��� or â€" or â€"
    - En dash (–) becomes â€" or â€"
    - Smart quotes become â€œ/â€"
    - Bullet points become â€¢
    """
    if not text:
        return text

    # Fix UTF-8 mojibake from quoted-printable double-decoding
    # Em dash (—) = UTF-8 E2 80 93 -> when misdecoded as latin1: â€"
    # En dash (–) = UTF-8 E2 80 92 -> when misdecoded as latin1: â€"
    replacements = {
        "\u00e2\u20ac\u201d": "\u2014",  # em dash (â€")
        "\u00e2\u20ac\u201c": "\u2013",  # en dash (â€")
        "\u00e2\u20ac\u0153": "\u201c",  # left double quote (â€œ)
        "\u00e2\u20ac\u009d": "\u201d",  # right double quote (â€)
        "\u00e2\u20ac\u0098": "\u2018",  # left single quote (â€˜)
        "\u00e2\u20ac\u2122": "\u2019",  # right single quote (â€™)
        "\u00e2\u20ac\u00a2": "\u2022",  # bullet (â€¢)
        "\u00e2\u20ac\u00a6": "\u2026",  # ellipsis (â€¦)
        "\u00e2\u20ac\u00a1": "\u2021",  # double dagger (â€¡)
        "\u00e2\u20ac\u0094": "\u2014",  # em dash variant (â€ )
        "\u00ef\u00bf\u00bd": "\u2014",  # replacement char variant (ï¿½)
        "\u00ef\u00bf\u00bf": "",  # replacement char (￿)
    }

    result = text
    for bad, good in replacements.items():
        result = result.replace(bad, good)

    # Also handle the literal ��� sequence (3 replacement chars = 1 em dash)
    result = re.sub(r"\uFFFD{3,}", "\u2014", result)
    result = re.sub(r"\uFFFD{2}", "\u2013", result)
    result = re.sub(r"\uFFFD", "", result)  # Remove any remaining replacement chars

    return result


class GoogleDeveloperBadgeModel(BaseModel):
    """Normalized schema for Google Developer badges and codelabs."""

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

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, val: Any) -> str:
        return normalize_date_string(val)


# ==============================================================================
# LOSS GUARD & ANOMALY PROTECTIONS
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

    logger.info(
        f"🛡️ Loss Guard Check: Stored Archive Baseline = {old_count} items | Incoming Dataset = {new_count} items."
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

    logger.info("✅ Loss Guard Assertion Passed: Incoming dataset verified.")


# ==============================================================================
# PARSERS & RPC FETCHERS
# ==============================================================================


def parse_local_learnings_txt() -> list[dict]:
    """Parses local Serbian text file of detailed learning activity codelabs."""
    if not os.path.exists(LEARNINGS_TXT_PATH):
        logger.info(
            f"ℹ️ Local activity file '{LEARNINGS_TXT_PATH}' not found. Skipping local parsing."
        )
        return []

    logger.info(f"📄 Parsing local Google learning log: '{LEARNINGS_TXT_PATH}'")
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
                title in ["Учење", "check_circle_outline You have this badge!"]
                and i > 1
            ):
                title = lines[i - 2]

            if (
                title not in ["Учење", "check_circle_outline You have this badge!"]
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
                    learnings.append(GoogleDeveloperBadgeModel(**entry).model_dump())
                except ValidationError as ve:
                    logger.warning(
                        f"⚠️ Skipping invalid local activity entry '{title}': {ve}"
                    )
        i += 1

    logger.info(
        f"✅ Extracted {len(learnings)} granular learning items from local log."
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
        logger.warning(
            f"⚠️ MHTML file '{mhtml_path}' not found. Skipping MHTML parsing."
        )
        return []

    logger.info(f"📄 Parsing Google Developer learnings from MHTML: '{mhtml_path}'")

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
                            GoogleDeveloperBadgeModel(**entry).model_dump()
                        )
                    except ValidationError as ve:
                        logger.warning(
                            f"⚠️ Skipping invalid MHTML activity entry '{title}': {ve}"
                        )

                logger.info(
                    f"✅ Extracted {len(learnings)} learning activities from MHTML ({retired_count} retired)."
                )
                return learnings
    except Exception as e:
        logger.warning(f"⚠️ MHTML parsing failed, falling back to text parser: {e}")

    # Fallback to legacy text parser
    logger.info(f"📄 Falling back to legacy text parser for: '{mhtml_path}'")
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
                        GoogleDeveloperBadgeModel(**entry).model_dump()
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
    logger.info("🌐 Fetching Google Developer public profile via RPC API...")
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
            logger.warning(
                f"⚠️ RPC request failed with status HTTP {response.status_code}"
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

        logger.info(f"✅ Extracted {len(parsed_badges)} badges from RPC endpoint.")
        return parsed_badges
    except Exception as e:
        logger.warning(f"⚠️ Exception occurred during RPC fetch: {e}")
        return []


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

            layer_metadata[layer_name] = layer_info

        return layer_metadata
    except Exception as e:
        logger.warning(f"⚠️ Could not generate layer metadata: {e}")
        return {}


# ==============================================================================
# MAIN PIPELINE EXECUTION
# ==============================================================================


def main():
    logger.info("Starting Google Developer Profile Pipeline...")

    public_badges = fetch_gdev_badges_rpc()
    detailed_learnings = parse_google_learnings_mhtml(LEARNINGS_TXT_PATH)

    # Combine feeds, deduplicating public badges against MHTML items
    combined_feed = list(public_badges)
    for dl in detailed_learnings:
        if not any(b["title"] == dl["title"] for b in combined_feed):
            combined_feed.append(dl)

    if not combined_feed:
        logger.error(
            "❌ No badge records extracted from RPC or local activity file. Aborting."
        )
        sys.exit(1)

    # 1. Execute Content-Aware Loss Guard against stored baseline
    #    Uses title + date hash as stable ID (no native ID in Google Developer data)
    #    to detect replacement/modification even when total count remains stable.
    # Note: Migration from google_learnings.txt to MHTML causes expected drop
    # (txt had ~1471 entries, MHTML shows last 1000 codelabs). Treat as warning.
    if execute_content_loss_guard:
        try:
            execute_content_loss_guard(
                new_records=combined_feed,
                platform="google-developer",
                id_field="title",
                fail_on_warn=False,  # Allow warnings (migration drop) without failing
                stream_id="combined",
            )
            logger.info("✅ Content Loss Guard passed.")
        except PipelineDataLossAnomaly as anomaly_err:
            logger.warning(
                f"⚠️ Content Loss Guard triggered (expected during MHTML migration): {anomaly_err}"
            )
            logger.warning("⚠️ Continuing pipeline with new MHTML data...")
    else:
        logger.warning(
            "⚠️ Content-aware loss guard unavailable, falling back to count-only check"
        )
        try:
            execute_data_loss_guard(combined_feed)
        except PipelineDataLossAnomaly as anomaly_err:
            logger.warning(
                f"⚠️ Count Loss Guard triggered (expected during MHTML migration): {anomaly_err}"
            )
            logger.warning("⚠️ Continuing pipeline with new MHTML data...")

    # 2. Retired URL / Identity detection
    retired_rules = load_retired_rules("google-developer")
    if retired_rules:
        _, marked = mark_retired(combined_feed, retired_rules, url_field="url")
        if marked > 0:
            logger.info(f"📝 Updated {marked} badge/activity(s) with retired status")

    # Persist full data with retired flags to for_validation for link checker
    validation_dir = VALIDATION_DIR
    os.makedirs(validation_dir, exist_ok=True)
    validation_file = os.path.join(validation_dir, "google-developer.json")

    # Generate layer metadata for cross-artifact validation
    layer_metadata = generate_layer_metadata("google-developer")

    payload = {
        "platform": "google-developer",
        "total_public_badges": len(public_badges),
        "total_detailed_learnings": len(detailed_learnings),
        "total_combined": len(combined_feed),
        "public_badges": public_badges,
        "detailed_learnings": detailed_learnings,
        "combined_feed": combined_feed,
        "_layer_metadata": layer_metadata,
    }
    try:
        with open(validation_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Full data persisted: '{validation_file}'")
    except Exception as e:
        logger.warning(f"⚠️ Could not persist full data: {e}")

    # Generate and save baseline fingerprints for L1_normalized streams
    if execute_content_loss_guard:
        try:
            # Google Developer has two L1 streams: public_badges and detailed_learnings
            execute_content_loss_guard(
                public_badges,
                platform="google-developer",
                id_field="title",  # Uses title+date for ID (see loss_guard extract_record_id)
                fail_on_warn=False,
                stream_id="public_badges",
            )
            execute_content_loss_guard(
                detailed_learnings,
                platform="google-developer",
                id_field="title",
                fail_on_warn=False,
                stream_id="detailed_learnings",
            )
            # Also baseline the combined_feed for cross-check
            execute_content_loss_guard(
                combined_feed,
                platform="google-developer",
                id_field="title",
                fail_on_warn=False,
                stream_id="combined",
            )
            logger.info("✅ Baseline fingerprints saved for google-developer streams")
        except Exception as e:
            logger.warning(f"⚠️ Could not save baseline: {e}")

    # 3. Export L2 archive
    archive_dir = ARCHIVE_DIR
    os.makedirs(archive_dir, exist_ok=True)
    archive_file = os.path.join(archive_dir, "google-developer.json")
    try:
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(combined_feed, f, indent=2, ensure_ascii=False)
        logger.info(
            f"📦 Archive saved: '{archive_file}' ({len(combined_feed)} records)"
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not save archive: {e}")

    # 4. Update README with stats
    try:
        update_readme_stats(
            platform_key="google-developer",
            total_count=len(combined_feed),
            public_badges=len(public_badges),
            detailed_learnings=len(detailed_learnings),
        )
        logger.info("📊 README updated with Google Developer stats")
    except Exception as e:
        logger.warning(f"⚠️ Could not update README: {e}")

    # 5. Sort combined entries reverse-chronologically
    combined_feed.sort(
        key=lambda x: (
            x.get("date", "0000-00-00") if x.get("date") != "N/A" else "0000-00-00"
        ),
        reverse=True,
    )

    total_public = len(public_badges)
    total_detailed = len(detailed_learnings)
    total_combined = len(combined_feed)

    formatted_rows = []
    for badge in combined_feed:
        clean_desc = badge["description"].replace("|", "\|").replace("\n", " ")
        clean_title = badge["title"].replace("|", "\|")
        # Primary check: retired flag from mark_retired
        # Fallback: check if URL is in retired_urls.json
        is_retired = (
            badge.get("retired", False)
            or badge.get("url", "") in _GOOGLE_DEV_RETIRED_URLS
        )
        if is_retired:
            clean_desc += " \U0001f6ab *Content retired*"
        row_text = f"| {badge['date']} | **{clean_title}** | {clean_desc} |"
        formatted_rows.append((row_text, badge["date"]))

    index_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-index.md"
    profile_url = "https://g.dev/vojislavmiloradovic"
    LATEST_SLICE_NORMAL = ""
    LATEST_SLICE_RAW = ""

    # 6. Assemble README sections
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
            f"Showing latest 10 merged activities. View full data via [Platform Archive Index](./archives/{PLATFORM_PREFIX}-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic Complete File](./archives/{PLATFORM_PREFIX}-complete.md).",
            "",
            "| Date Earned | Title | Description |",
            "| :---: | :--- | :--- |",
        ]
    )

    for badge in combined_feed[:10]:
        clean_desc = badge["description"].replace("|", "\\|").replace("\n", " ")
        clean_title = badge["title"].replace("|", "\\|")
        readme_lines.append(f"| *{badge['date']}* | **{clean_title}** | {clean_desc} |")

    table_headers = ["Date Earned", "Title", "Description"]
    table_alignments = [":---:", ":---", ":---"]

    # 7. Trigger Archiver
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
            LATEST_SLICE_NORMAL = "./archives/" + latest_slice
            LATEST_SLICE_RAW = RAW_BASE_DEFAULT + "/" + latest_slice
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
                readme_content = f.read()
            if MARKER_START in readme_content and MARKER_END in readme_content:
                before = readme_content.split(MARKER_START)[0]
                after = readme_content.split(MARKER_END)[1]
                new_block = "\n".join(readme_lines) + "\n"
                new_content = (
                    before + MARKER_START + "\n" + new_block + MARKER_END + after
                )
                safe_write_file("README.md", new_content)

    # Update index file with two-category breakdown required by generate_llms_txt.py
    index_file_path = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-index.md")
    if os.path.exists(index_file_path):
        try:
            with open(index_file_path, "r", encoding="utf-8") as f:
                index_content = f.read()

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
            logger.info(f"✅ Updated category breakdown metrics in {index_file_path}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update overview in {index_file_path}: {e}")

    logger.info(
        f"🎉 Google Developer pipeline complete ({total_combined} combined items)."
    )


if __name__ == "__main__":
    main()
