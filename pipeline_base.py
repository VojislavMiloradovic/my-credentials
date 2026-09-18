"""
Pipeline Base Class - Option 2 Migration
Encapsulates common pipeline orchestration logic to eliminate duplication across update_*.py files.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, ClassVar

# Import shared orchestration functions from loss_guard
from loss_guard import (
    generate_all_provider_baselines,
    generate_provider_baseline,
    load_retired_rules,
    run_provider_loss_guards,
)
from scripts.sync_fixtures import sync_fixtures

# Try to import archiver
try:
    from archiver import (
        RAW_BASE_DEFAULT,
        generate_platform_archive,
        safe_write_file,
    )
except ImportError:
    generate_platform_archive = None
    safe_write_file = lambda filepath, new_content: False
    RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"

# Layer manifest integration
_LAYER_MANIFEST = None


def _load_manifest() -> dict:
    """Load and cache the dataset_layers.yaml manifest."""
    global _LAYER_MANIFEST
    if _LAYER_MANIFEST is None:
        try:
            import yaml

            with open("dataset_layers.yaml", "r", encoding="utf-8") as f:
                _LAYER_MANIFEST = yaml.safe_load(f)
        except Exception:
            _LAYER_MANIFEST = {}
    return _LAYER_MANIFEST


def _get_layer_artifacts(platform_key: str, layer: str) -> list[str]:
    """Get list of artifacts for a given platform and layer."""
    manifest = _load_manifest()
    key_map = {
        "ms-learn": "microsoft-learn",
        "google-dev": "google-developer",
        "aws-skills": "aws-skills",
        "google-skills": "google-skills",
        "credly": "credly",
        "linkedin": "linkedin-certifications",
    }
    manifest_key = key_map.get(platform_key, platform_key)
    platform = manifest.get("platforms", {}).get(manifest_key, {})
    layer_info = platform.get(layer, {})
    return layer_info.get("artifacts", [])


def _get_layer_transform(platform_key: str, layer: str):
    """Get transform info for a given platform and layer."""
    manifest = _load_manifest()
    key_map = {
        "ms-learn": "microsoft-learn",
        "google-dev": "google-developer",
        "aws-skills": "aws-skills",
        "google-skills": "google-skills",
        "credly": "credly",
        "linkedin": "linkedin-certifications",
    }
    manifest_key = key_map.get(platform_key, platform_key)
    platform = manifest.get("platforms", {}).get(manifest_key, {})
    layer_info = platform.get(layer, {})
    return layer_info.get("transform", "unknown")


def generate_layer_metadata(platform_key: str) -> dict[str, Any]:
    """Generate layer metadata from manifest for a platform."""
    try:
        manifest = _load_manifest()
        key_map = {
            "ms-learn": "microsoft-learn",
            "google-dev": "google-developer",
            "aws-skills": "aws-skills",
            "google-skills": "google-skills",
            "credly": "credly",
            "linkedin": "linkedin-certifications",
        }
        manifest_key = key_map.get(platform_key, platform_key)
        if manifest_key not in manifest.get("platforms", {}):
            return {}

        platform = manifest["platforms"][manifest_key]

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
        logging.getLogger("PipelineBase").warning(
            f"[WARN] Could not generate layer metadata: {e}"
        )
        return {}


class PipelineBase:
    """Base class for credential pipelines with built-in loss guard orchestration."""

    # Class attributes to be overridden by subclasses
    PLATFORM_NAME: str = ""  # e.g., "aws-skills", "google-developer"
    PLATFORM_PREFIX: str = ""  # e.g., "aws-skills", "google-developer"
    ID_FIELD: str = "id"
    VALIDATION_DIR: str = "for_validation"
    ARCHIVE_DIR: str = "archives"
    README_PATH: str = "README.md"
    MARKER_START: str = ""
    MARKER_END: str = ""
    PLATFORM_DISPLAY_NAME: str = ""  # Human-readable name for archives

    # Loss guard config (can override PROVIDER_CONFIG defaults)
    FAIL_ON_WARN: bool = True
    THRESHOLD: float = 0.15
    BASELINE_SOURCES: list = None  # If None, uses PROVIDER_CONFIG
    STREAMS: list = None  # For multi-stream (google-developer)

    # Archive table config
    TABLE_HEADERS: ClassVar[list[str]] = ["Date", "Title", "Description"]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---"]

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.PLATFORM_NAME:
            raise ValueError("PLATFORM_NAME must be set in subclass")
        if not self.PLATFORM_PREFIX:
            self.PLATFORM_PREFIX = self.PLATFORM_NAME
        if not self.PLATFORM_DISPLAY_NAME:
            self.PLATFORM_DISPLAY_NAME = self.PLATFORM_NAME.replace("-", " ").title()
        if not self.MARKER_START:
            self.MARKER_START = (
                f"<!-- {self.PLATFORM_PREFIX.upper().replace('-', '_')}_START -->"
            )
        if not self.MARKER_END:
            self.MARKER_END = (
                f"<!-- {self.PLATFORM_PREFIX.upper().replace('-', '_')}_END -->"
            )

    # === Abstract methods (must implement) ===
    def fetch_data(self) -> list[dict]:
        """Fetch raw data from source (API, file, etc.)."""
        raise NotImplementedError

    def parse_data(self, raw_data) -> list[dict]:
        """Parse/transform raw data into standardized records."""
        raise NotImplementedError

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        """Format single record for markdown table: (row_text, date)."""
        raise NotImplementedError

    def build_readme_lines(self, records: list[dict], latest_slice: str) -> list[str]:
        """Build README section lines."""
        raise NotImplementedError

    # === Hook methods (optional override) ===
    def pre_loss_guard(self, records: list[dict]) -> list[dict]:
        """Hook before loss guard (e.g., deduplication)."""
        return records

    def post_loss_guard(self, records: list[dict]) -> list[dict]:
        """Hook after loss guard (e.g., retired marking)."""
        return records

    def get_retired_rules(self) -> list[dict]:
        """Load retired rules for this platform."""
        return load_retired_rules(self.PLATFORM_NAME)

    def get_validation_payload(self, records: list[dict]) -> dict:
        """Build validation payload - override for custom payload structure."""
        return {
            "platform": self.PLATFORM_NAME,
            "total_combined": len(records),
            "combined_feed": records,
            "_layer_metadata": generate_layer_metadata(self.PLATFORM_NAME),
        }

    def get_archive_payload(self, records: list[dict]) -> list[dict]:
        """Get records to write to L2 archive JSON - override if different from combined_feed."""
        return records

    # === Core pipeline flow (final - don't override) ===
    def run(self):
        """Execute complete pipeline."""
        self.logger.info(f"[START] Starting {self.PLATFORM_DISPLAY_NAME} Pipeline...")

        # 1. Fetch & parse
        raw = self.fetch_data()
        records = self.parse_data(raw)

        if not records:
            self.logger.error("[FAIL] No records extracted. Aborting.")
            return

        # 2. Pre-guard hook (deduplication, etc.)
        records = self.pre_loss_guard(records)

        # 3. Run loss guards (orchestrated)
        if self.STREAMS:
            run_provider_loss_guards(
                records,
                self.PLATFORM_NAME,
                fail_on_warn=self.FAIL_ON_WARN,
            )
            generate_all_provider_baselines(records, self.PLATFORM_NAME)
        else:
            run_provider_loss_guards(
                records,
                self.PLATFORM_NAME,
                fail_on_warn=self.FAIL_ON_WARN,
            )
            generate_provider_baseline(records, self.PLATFORM_NAME)

        # 4. Post-guard hook (retired marking)
        records = self.post_loss_guard(records)

        # 5. Persist validation data
        self.persist_validation(records)

        # 6. Sort for archive (newest first)
        records.sort(key=self._sort_key, reverse=True)

        # 7. Format for archive
        formatted_rows = [self.format_for_archive(r) for r in records]

        # 8. Generate archive & update README
        latest_slice = self.generate_archive(formatted_rows)

        # 9. Update README
        readme_lines = self.build_readme_lines(records, latest_slice)
        self.update_readme(readme_lines, latest_slice)

        # 10. Sync fixtures
        self.sync_fixtures()

        self.logger.info(
            f"[DONE] {self.PLATFORM_DISPLAY_NAME} pipeline complete ({len(records)} combined items)."
        )

    def _sort_key(self, record):
        date = record.get("date", "0000-00-00")
        return date if date != "N/A" else "0000-00-00"

    def persist_validation(self, records):
        """Persist validated data with layer metadata."""
        os.makedirs(self.VALIDATION_DIR, exist_ok=True)
        validation_file = os.path.join(
            self.VALIDATION_DIR, f"{self.PLATFORM_NAME}.json"
        )

        payload = self.get_validation_payload(records)
        try:
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            self.logger.info(f"[SAVE] Full data persisted: '{validation_file}'")
        except Exception as e:
            self.logger.warning(f"[WARN] Could not persist validation data: {e}")

    def generate_archive(self, formatted_rows):
        """Generate markdown archive via archiver module."""
        if not generate_platform_archive:
            self.logger.warning(
                "[WARN] Archiver module not available. Skipping markdown generation."
            )
            return None

        try:
            retrieved_at = datetime.now(UTC).isoformat()
            latest_slice = generate_platform_archive(
                platform_prefix=self.PLATFORM_PREFIX,
                platform_name=self.PLATFORM_DISPLAY_NAME,
                table_headers=self.TABLE_HEADERS,
                table_alignments=self.TABLE_ALIGNMENTS,
                formatted_rows=formatted_rows,
                readme_lines=[],  # We'll update README separately
                marker_start=self.MARKER_START,
                marker_end=self.MARKER_END,
                archive_dir=self.ARCHIVE_DIR,
                readme_path=self.README_PATH,
                retrieved_at=retrieved_at,
            )
            return latest_slice
        except Exception as e:
            self.logger.warning(f"[WARN] Archive generation failed: {e}")
            return None

    def update_readme(self, readme_lines: list[str], latest_slice: str):
        """Update README.md with generated content."""
        if not os.path.exists(self.README_PATH):
            return

        # Replace slice placeholders
        LATEST_SLICE_NORMAL = ""
        LATEST_SLICE_RAW = ""
        if latest_slice:
            LATEST_SLICE_NORMAL = "./archives/" + latest_slice
            LATEST_SLICE_RAW = RAW_BASE_DEFAULT + "/" + latest_slice

        for i, line in enumerate(readme_lines):
            if "{LATEST_SLICE_NORMAL}" in line:
                readme_lines[i] = line.replace(
                    "{LATEST_SLICE_NORMAL}", LATEST_SLICE_NORMAL
                ).replace("{LATEST_SLICE_RAW}", LATEST_SLICE_RAW)
                break

        try:
            with open(self.README_PATH, "r", encoding="utf-8") as f:
                readme_content = f.read()

            if (
                self.MARKER_START in readme_content
                and self.MARKER_END in readme_content
            ):
                before = readme_content.split(self.MARKER_START)[0]
                after = readme_content.split(self.MARKER_END)[1]
                new_block = "\n".join(readme_lines) + "\n"
                new_content = (
                    before
                    + self.MARKER_START
                    + "\n"
                    + new_block
                    + self.MARKER_END
                    + after
                )
                if safe_write_file:
                    safe_write_file(self.README_PATH, new_content)
        except Exception as e:
            self.logger.warning(f"[WARN] README update failed: {e}")

    def sync_fixtures(self):
        """Sync baseline files to test fixtures."""
        try:
            sync_fixtures(self.PLATFORM_NAME)
        except Exception as e:
            self.logger.warning(f"[WARN] Fixture sync failed (non-fatal): {e}")


if __name__ == "__main__":
    # Allow running as standalone for testing
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    print("PipelineBase module - import and subclass to use")
