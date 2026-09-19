"""
update_credly_badges.py
-----------------------
Pipeline for updating Credly profile badges and credentials via Credly public API.
Refactored to use PipelineBase (Option 2 Migration).
"""

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

CREDLY_USER = os.getenv("CREDLY_USER", "vojislavmiloradovic")
CREDLY_USER_ID = os.getenv("CREDLY_USER_ID", "752aee40-7358-4ade-9a49-81e8b6f49225")
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
OUTPUT_FILENAME = "credly_badges.json"
OUTPUT_FILE = os.path.join(VALIDATION_DIR, OUTPUT_FILENAME)
ARCHIVE_DIR = "archives"
README_PATH = "README.md"
ARCHIVE_MONOLITH = os.path.join(ARCHIVE_DIR, "credly-complete.md")
MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
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


class CredlyBadgeItemModel(ProvenanceBase):
    """Normalized schema for Credly badge entities."""

    # Platform-specific fields
    id: str = Field(..., min_length=1, description="Credly unique badge ID")
    title: str = Field(..., min_length=1, description="Badge title")
    name: str = Field(..., min_length=1, description="Title alias for compatibility")
    issuer: str = Field(..., min_length=1, description="Organization issuing the badge")
    issuer_name: str = Field(
        ..., min_length=1, description="Issuer alias for compatibility"
    )
    issued_at: str | None = Field(None, description="ISO YYYY-MM-DD earned date")
    issued_at_date: str | None = Field(None, description="Alias for issued date")
    date: str | None = Field(None, description="Alias for issued date")
    image_url: str | None = Field(None, description="Badge image asset URL")
    verify_url: str | None = Field(None, description="Public verification link")
    url: str | None = Field(None, description="Alias for verify_url")
    type: str = Field("Credly Verified Badge", description="Classification type")
    verification_type: str = Field(
        "Credly Verified Badge", description="Verification category"
    )
    skills: list[str] = Field(default_factory=list, description="Associated skills")
    retired: bool = Field(
        False, description="Whether the content has been retired by the platform"
    )

    # Provenance fields with platform-specific defaults
    source_platform: str = Field(default="credly", description="Platform identifier")
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
            clean = []
            for item in val:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("title")
                    if name and str(name).strip():
                        clean.append(str(name).strip())
                elif isinstance(item, str) and item.strip():
                    clean.append(item.strip())
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


class CredlyArchivePayloadModel(BaseModel):
    """Root model for Credly persistence JSON validation."""

    credly_user: str
    total_count: int = Field(ge=0)
    credentials: list[CredlyBadgeItemModel]


# ==============================================================================
# CREDLY API FETCHING & MERGING (module-level for backward compat)
# ==============================================================================


def parse_credly_badges_from_json(json_path: str) -> list[dict]:
    """Reads existing Credly badge entries directly from specified JSON file."""
    if not os.path.exists(json_path):
        return []

    logging.getLogger("credly").info(
        f"[FILE] Reading existing Credly badges from JSON: '{json_path}'"
    )
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_list = (
            data.get("credentials", [])
            if isinstance(data, dict)
            else (data if isinstance(data, list) else [])
        )
        badges = []
        for item in raw_list:
            if isinstance(item, dict):
                try:
                    validated = CredlyBadgeItemModel(**item)
                    badges.append(validated.model_dump(mode="json"))
                except ValidationError as ve:
                    logging.getLogger("credly").warning(
                        f"[WARN] Skipping invalid JSON badge entry: {ve}"
                    )

        logging.getLogger("credly").info(
            f"[OK] Loaded {len(badges)} valid Credly badges from JSON file."
        )
        return badges
    except (json.JSONDecodeError, OSError) as e:
        logging.getLogger("credly").warning(
            f"[WARN] Error reading JSON file '{json_path}': {e}"
        )
        return []


def load_existing_local_badges() -> list[dict]:
    """Loads existing local badges from for_validation directory prior to API fetch."""
    candidates = [
        OUTPUT_FILE,
        OUTPUT_FILENAME,
        os.path.join("data", OUTPUT_FILENAME),
    ]
    for path in candidates:
        if os.path.exists(path):
            badges = parse_credly_badges_from_json(path)
            if badges:
                return badges
    return []


def fetch_credly_badges(username: str) -> list[dict] | None:
    """Fetches badges directly from Credly's public user API endpoint with pagination."""
    url = f"https://www.credly.com/users/{username}/badges.json"
    logging.getLogger("credly").info(
        f"[SYNC] Fetching Credly badges from API endpoint: {url}"
    )

    badges = []
    seen_badge_ids: set[str] = set()
    page = 1

    while True:
        try:
            response = requests.get(f"{url}?page={page}", headers=HEADERS, timeout=20)
            if response.status_code != 200:
                logging.getLogger("credly").warning(
                    f"[WARN] Credly API returned status code {response.status_code} on page {page}."
                )
                return None if not badges else badges

            payload = response.json()
            data_list = payload.get("data", []) if isinstance(payload, dict) else []

            if not data_list:
                break

            ids_before_page = len(seen_badge_ids)
            for item in data_list:
                badge_template = item.get("badge_template", {}) or {}
                issuer_info = badge_template.get("issuer", {}) or {}

                title = badge_template.get("name") or item.get("name") or "Credly Badge"
                # Extract issuer name from entities[0].entity.name (e.g., "Acronis") for consistency
                # rather than summary (e.g., "issued by Acronis") which can vary
                issuer_name = "Credly Issuer"
                entities = issuer_info.get("entities")
                if entities and isinstance(entities, list) and len(entities) > 0:
                    entity = entities[0].get("entity", {})
                    if entity.get("name"):
                        issuer_name = entity["name"]
                # Fallback to summary or name if entities not available
                if issuer_name == "Credly Issuer":
                    issuer_name = (
                        issuer_info.get("summary")
                        or issuer_info.get("name")
                        or badge_template.get("issuer_name")
                        or "Credly Issuer"
                    )

                dt = item.get("issued_at") or item.get("created_at")
                badge_id = str(item.get("id"))
                if badge_id in seen_badge_ids:
                    continue
                seen_badge_ids.add(badge_id)
                verify_url = f"https://www.credly.com/badges/{badge_id}/public_url"

                raw_skills = badge_template.get("skills", [])

                raw_entry = {
                    "id": badge_id,
                    "title": title,
                    "name": title,
                    "issuer": issuer_name,
                    "issuer_name": issuer_name,
                    "issued_at": dt,
                    "issued_at_date": dt,
                    "date": dt,
                    "image_url": badge_template.get("image_url")
                    or item.get("image_url"),
                    "verify_url": verify_url,
                    "url": verify_url,
                    "type": "Credly Verified Badge",
                    "verification_type": "Credly Verified Badge",
                    "skills": raw_skills,
                }

                try:
                    validated = CredlyBadgeItemModel(**raw_entry)
                    badges.append(validated.model_dump(mode="json"))
                except ValidationError as ve:
                    logging.getLogger("credly").warning(
                        f"[WARN] Skipping invalid Credly API entry '{title}': {ve}"
                    )

            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            next_page = metadata.get("next_page") or metadata.get("next_page_url")
            if next_page is None and len(data_list) < 48:
                break
            if len(seen_badge_ids) == ids_before_page and page > 1:
                logging.getLogger("credly").warning(
                    "[WARN] Credly API returned no new badge IDs; stopping pagination."
                )
                break
            page += 1

        except requests.exceptions.RequestException as e:
            logging.getLogger("credly").error(
                f"[FAIL] Exception occurred while requesting Credly API: {e}"
            )
            return None if not badges else badges

    if badges:
        logging.getLogger("credly").info(
            f"[OK] Successfully fetched {len(badges)} badges from Credly API."
        )

    return badges


def fetch_credly_external_badges(user_id: str) -> list[dict] | None:
    """Fetches Credly's public external/open-badge records."""
    url = f"https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public"
    logging.getLogger("credly").info(
        f"[SYNC] Fetching External Open Badges API endpoint: {url}"
    )

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        logging.getLogger("credly").error(
            f"[FAIL] Exception occurred while requesting external Credly badges: {exc}"
        )
        return None

    records = payload.get("data", []) if isinstance(payload, dict) else []
    badges = []
    for item in records:
        external = item.get("external_badge", {}) or {}
        badge_id = str(item.get("id") or external.get("credly_record_id") or "").strip()
        title = str(external.get("badge_name") or "Credly External Badge").strip()
        issuer = str(external.get("issuer_name") or "External Issuer").strip()
        verify_url = external.get("badge_url") or external.get("badge_id")
        issued_at = external.get("issued_at_date") or external.get("issued_at")

        raw_entry = {
            "id": badge_id,
            "title": title,
            "name": title,
            "issuer": issuer,
            "issuer_name": issuer,
            "issued_at": issued_at,
            "issued_at_date": issued_at,
            "date": issued_at,
            "image_url": external.get("image_url"),
            "verify_url": verify_url,
            "url": verify_url,
            "type": "Credly External Badge",
            "verification_type": "Credly External Badge",
            "skills": external.get("skills", []),
        }
        try:
            badges.append(CredlyBadgeItemModel(**raw_entry).model_dump(mode="json"))
        except ValidationError as exc:
            logging.getLogger("credly").warning(
                f"[WARN] Skipping invalid external Credly entry '{title}': {exc}"
            )

    logging.getLogger("credly").info(
        f"[OK] Successfully fetched {len(badges)} external open badges from Credly API."
    )
    return badges


def merge_badge_datasets(
    api_badges: list[dict], external_badges: list[dict]
) -> list[dict]:
    """Unions the two live Credly datasets by stable record ID."""
    badge_map = {}

    for b in api_badges + external_badges:
        key = b.get("id") or f"{b.get('title')}-{b.get('issued_at')}"
        if key:
            badge_map[key] = b

    merged = list(badge_map.values())
    logging.getLogger("credly").info(
        f"[LINK] Union Merge Complete: Total = {len(merged)} badges "
        f"(Native={len(api_badges)}, External={len(external_badges)})."
    )
    return merged


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
    return _get_count("credly", json_path, monolith_path)


def execute_data_loss_guard(new_badges: list[dict], output_file: str) -> None:
    return _execute_guard(new_badges, "credly", output_file, ARCHIVE_MONOLITH)


def execute_content_loss_guard(*args, **kwargs):
    return _execute_content(*args, **kwargs)


# ==============================================================================
# PIPELINE CLASS
# ==============================================================================


class CredlyPipeline(PipelineBase):
    PLATFORM_NAME = "credly"
    PLATFORM_PREFIX = "credly"
    PLATFORM_DISPLAY_NAME = "Credly Verified Credentials"
    ARCHIVE_DIR = "archives"
    README_PATH = "README.md"
    ARCHIVE_MONOLITH = os.path.join("archives", "credly-complete.md")
    MARKER_START = "<!-- CREDLY_BADGES_START -->"
    MARKER_END = "<!-- CREDLY_BADGES_END -->"

    TABLE_HEADERS: ClassVar[list[str]] = [
        "Date Earned",
        "Credential Name",
        "Issuer",
        "Verification Type",
    ]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---", ":---:"]

    CREDLY_USER = CREDLY_USER
    CREDLY_USER_ID = CREDLY_USER_ID
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
        """Fetch and merge both live Credly datasets."""
        # Load existing local badges BEFORE calling API
        local_badges = load_existing_local_badges()

        # Fetch both live Credly datasets
        native_badges = fetch_credly_badges(self.CREDLY_USER)
        external_badges = fetch_credly_external_badges(self.CREDLY_USER_ID)

        # Treat empty results (0 badges) as failure and fall back to local data.
        # An API returning 0 badges when baseline has data indicates an issue, not success.
        native_ok = native_badges is not None and len(native_badges) > 0
        external_ok = external_badges is not None and len(external_badges) > 0

        if not native_ok or not external_ok:
            self.logger.warning(
                f"[WARN] One or more Credly sources failed or returned 0 badges "
                f"(native_ok={native_ok}, external_ok={external_ok}); "
                f"retaining the previous local dataset ({len(local_badges)} badges)."
            )
            return local_badges
        else:
            return merge_badge_datasets(native_badges, external_badges)

    def parse_data(self, raw_data) -> list[dict]:
        """Parse/transform raw data - already validated via Pydantic in fetch_data."""
        return raw_data

    def pre_loss_guard(self, records: list[dict]) -> list[dict]:
        """No deduplication needed - merge_badge_datasets already handles it."""
        return records

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
        issuer = str(record.get("issuer") or "Credly").strip()
        v_type = str(record.get("type") or "Credly Verified Badge").strip()
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

        index_raw = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-index.md"
        profile_url = f"https://www.credly.com/users/{self.CREDLY_USER}"

        readme_lines = [
            "### Credly Verified Credentials",
            "",
            f"**Public Profile:** [Verify Credly Profile]({profile_url})",
            "",
            f"**Total Portfolio Credentials:** {total_count}",
            f"**Total Verified Skills Mapped:** {total_skills}",
            "",
            "#### Latest Earned Credentials",
            "",
            f"Showing latest 10 of {total_count} credentials. View full dataset via [Platform Archive Index](./archives/credly-index.md) ([Raw Index]({index_raw})), latest slice [Latest Slice]({{LATEST_SLICE_NORMAL}}) ([Raw]({{LATEST_SLICE_RAW}})), or [Monolithic File](./archives/credly-complete.md).",
            "",
            "| Date Earned | Credential Name | Issuer | Verification Type |",
            "| :---: | :--- | :--- | :---: |",
        ]

        for record in records[:10]:
            row_text, _ = self.format_for_archive(record)
            readme_lines.append(row_text)

        return readme_lines

    def get_validation_payload(self, records: list[dict]) -> dict:
        """Build validation payload with Credly-specific fields."""
        layer_metadata = {}
        try:
            from layer_manifest import load_manifest

            manifest = load_manifest()
            if "credly" in manifest.platforms:
                platform = manifest.platforms["credly"]
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
            "credly_user": self.CREDLY_USER,
            "total_count": len(records),
            "credentials": records,  # Credly uses "credentials" per manifest
            "_layer_metadata": layer_metadata,
        }

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records for L2 archive JSON."""
        return records

    def persist_validation(self, records):
        """Persist validated data with Credly-specific filename."""
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
    CredlyPipeline().run()


if __name__ == "__main__":
    main()
    # Sync fixtures for test consistency
    try:
        from scripts.sync_fixtures import sync_fixtures

        sync_fixtures("credly")
    except Exception as exc:
        logging.getLogger("credly").warning(
            f"[WARN] Fixture sync failed (non-fatal): {exc}"
        )
