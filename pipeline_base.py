"""
Pipeline Base Class - Option 2 Migration
Encapsulates common pipeline orchestration logic to eliminate duplication across update_*.py files.
"""

import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, ClassVar, Self

# Import shared orchestration functions from loss_guard
import loss_guard
from loss_guard import (
    load_retired_rules,
    run_provider_loss_guards,
)
from scripts.sync_fixtures import FIXTURE_MAP, sync_fixtures

# Try to import archiver
try:
    from archiver import (
        RAW_BASE_DEFAULT,
        atomic_write_text,
        generate_platform_archive,
        safe_write_file,
    )
except ImportError:
    atomic_write_text = None
    generate_platform_archive = None
    safe_write_file = None
    RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"


def _atomic_write_json(
    filepath: str,
    payload: dict[str, Any],
    *,
    ensure_ascii: bool = False,
) -> None:
    """Atomically write JSON payload to filepath via temp file + os.replace."""
    serialized = json.dumps(payload, indent=2, ensure_ascii=ensure_ascii)
    if atomic_write_text is not None:
        atomic_write_text(filepath, serialized, encoding="utf-8", newline=None)
        return

    parent_dir = os.path.dirname(filepath) or "."
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent_dir,
            prefix=f".{os.path.basename(filepath)}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(serialized)
            tmp_file.flush()
        os.replace(tmp_path, filepath)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _atomic_copy_restore(src_path: str, dst_path: str) -> None:
    """Atomically restore a snapshotted file back to dst_path."""
    parent_dir = os.path.dirname(dst_path) or "."
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=parent_dir,
            prefix=f".{os.path.basename(dst_path)}.",
            suffix=".restore.tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
        shutil.copy2(src_path, tmp_path)
        try:
            os.replace(tmp_path, dst_path)
        except OSError:
            if os.name != "nt" or not os.path.exists(dst_path):
                raise
            backup_path = f"{dst_path}.bak"
            os.replace(dst_path, backup_path)
            try:
                os.replace(tmp_path, dst_path)
            except OSError:
                if not os.path.exists(dst_path) and os.path.exists(backup_path):
                    os.replace(backup_path, dst_path)
                raise
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


class PublicationTransaction:
    """Snapshot/rollback transaction guarding the publication phase.

    Snapshots platform-scoped validation files, baselines, archives, README, and
    synced test fixtures before publication mutations begin. Any exception during
    publication rolls back all tracked artifacts to their pre-run state so local
    or CI failures never leave partial state or advance baselines.
    """

    def __init__(
        self,
        *,
        tracked_files: list[str],
        tracked_dir_prefixes: list[tuple[str, tuple[str, ...]]],
        logger: logging.Logger,
    ) -> None:
        self.tracked_files = [
            os.path.abspath(p) for p in dict.fromkeys(tracked_files) if p
        ]
        self.tracked_dir_prefixes: list[tuple[str, tuple[str, ...]]] = []
        seen_dirs: dict[str, set[str]] = {}
        for dir_path, prefixes in tracked_dir_prefixes:
            if not dir_path:
                continue
            abs_dir = os.path.abspath(dir_path)
            seen_dirs.setdefault(abs_dir, set()).update(prefixes)
        for abs_dir, prefix_set in seen_dirs.items():
            self.tracked_dir_prefixes.append((abs_dir, tuple(sorted(prefix_set))))

        self.logger = logger
        self._backup_dir: tempfile.TemporaryDirectory[str] | None = None
        self._file_snapshots: dict[str, tuple[bool, str | None]] = {}
        self._dir_existed: dict[str, bool] = {}
        self._dir_snapshots: dict[tuple[str, str], str] = {}

    def __enter__(self) -> Self:
        self._backup_dir = tempfile.TemporaryDirectory(prefix="pub_tx_")
        counter = 0

        for abs_path in self.tracked_files:
            if os.path.isfile(abs_path):
                backup_path = os.path.join(self._backup_dir.name, f"file_{counter}")
                counter += 1
                shutil.copy2(abs_path, backup_path)
                self._file_snapshots[abs_path] = (True, backup_path)
            else:
                self._file_snapshots[abs_path] = (False, None)

        for abs_dir, prefixes in self.tracked_dir_prefixes:
            dir_exists = os.path.isdir(abs_dir)
            self._dir_existed[abs_dir] = dir_exists
            if not dir_exists:
                continue
            for entry in os.listdir(abs_dir):
                if any(entry.startswith(prefix) for prefix in prefixes):
                    full_path = os.path.join(abs_dir, entry)
                    if os.path.isfile(full_path):
                        backup_path = os.path.join(
                            self._backup_dir.name, f"dir_{counter}"
                        )
                        counter += 1
                        shutil.copy2(full_path, backup_path)
                        self._dir_snapshots[(abs_dir, entry)] = backup_path

        return self

    def rollback(self) -> None:
        """Restore all pre-run files and remove files newly created in the transaction."""
        self.logger.error(
            "[ROLLBACK] Publication failed; restoring pre-run validation, archive, README, baseline, and fixture state."
        )

        # 1. Remove newly created directory-matched files and restore snapshotted ones
        for abs_dir, prefixes in self.tracked_dir_prefixes:
            if os.path.isdir(abs_dir):
                for entry in os.listdir(abs_dir):
                    if any(entry.startswith(prefix) for prefix in prefixes):
                        full_path = os.path.join(abs_dir, entry)
                        if (
                            abs_dir,
                            entry,
                        ) not in self._dir_snapshots and os.path.isfile(full_path):
                            try:
                                os.remove(full_path)
                            except OSError as e:
                                self.logger.warning(
                                    f"[ROLLBACK] Could not remove new file '{full_path}': {e}"
                                )

        for (abs_dir, entry), backup_path in self._dir_snapshots.items():
            target_path = os.path.join(abs_dir, entry)
            _atomic_copy_restore(backup_path, target_path)

        for abs_dir, _ in self.tracked_dir_prefixes:
            if not self._dir_existed.get(abs_dir, True) and os.path.isdir(abs_dir):
                try:
                    if not os.listdir(abs_dir):
                        os.rmdir(abs_dir)
                except OSError:
                    pass

        # 2. Restore or delete individually tracked files
        for abs_path, (existed, backup_path) in self._file_snapshots.items():
            if existed and backup_path is not None:
                _atomic_copy_restore(backup_path, abs_path)
            elif not existed and os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError as e:
                    self.logger.warning(
                        f"[ROLLBACK] Could not remove new file '{abs_path}': {e}"
                    )

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            if self._backup_dir is not None:
                self._backup_dir.cleanup()
                self._backup_dir = None
        return False


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

    # Paths for count loss guard baseline lookup (override in subclass if needed)
    JSON_PATH: str | None = None
    MONOLITH_PATH: str | None = None

    # Archive table config
    TABLE_HEADERS: ClassVar[list[str]] = ["Date", "Title", "Description"]
    TABLE_ALIGNMENTS: ClassVar[list[str]] = [":---:", ":---", ":---"]

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._retired_rules: list[dict] | None = None
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
        """Load retired rules for this platform (cached after first call)."""
        if not hasattr(self, "_retired_rules") or self._retired_rules is None:
            self._retired_rules = load_retired_rules(self.PLATFORM_NAME)
        return self._retired_rules

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
    def _resolve_runtime_path(self, attr_name: str, default_value: str) -> str:
        """Resolve path attributes dynamically, respecting test module patches."""
        if attr_name in self.__dict__:
            return str(self.__dict__[attr_name])
        current_val = getattr(self, attr_name)
        if current_val != default_value:
            return str(current_val)
        module = sys.modules.get(self.__class__.__module__)
        if module and hasattr(module, attr_name):
            mod_val = getattr(module, attr_name)
            if mod_val:
                return str(mod_val)
        return str(current_val)

    def _effective_validation_dir(self) -> str:
        return self._resolve_runtime_path("VALIDATION_DIR", "for_validation")

    def _effective_archive_dir(self) -> str:
        return self._resolve_runtime_path("ARCHIVE_DIR", "archives")

    def _effective_readme_path(self) -> str:
        return self._resolve_runtime_path("README_PATH", "README.md")

    def _write_validation_payload(
        self,
        validation_file: str,
        payload: dict[str, Any],
        *,
        ensure_ascii: bool = False,
    ) -> None:
        """Atomically persist validation JSON and raise on failure."""
        _atomic_write_json(validation_file, payload, ensure_ascii=ensure_ascii)
        self.logger.info(f"[SAVE] Full data persisted: '{validation_file}'")

    @contextmanager
    def _publication_transaction(self):
        """Wrap publication mutations in an atomic snapshot/rollback transaction."""
        validation_dir = self._effective_validation_dir()
        archive_dir = self._effective_archive_dir()
        readme_path = self._effective_readme_path()

        tracked_files = [readme_path]
        output_file = getattr(self, "OUTPUT_FILE", None)
        if output_file:
            tracked_files.append(str(output_file))
        for _, dst in FIXTURE_MAP.get(self.PLATFORM_NAME, []):
            tracked_files.append(dst)

        prefixes = tuple(dict.fromkeys([self.PLATFORM_NAME, self.PLATFORM_PREFIX]))
        tracked_dir_prefixes: list[tuple[str, tuple[str, ...]]] = [
            (validation_dir, prefixes),
            (loss_guard.VALIDATION_DIR, prefixes),
            (archive_dir, (f"{self.PLATFORM_PREFIX}-",)),
        ]

        with PublicationTransaction(
            tracked_files=tracked_files,
            tracked_dir_prefixes=tracked_dir_prefixes,
            logger=self.logger,
        ):
            yield

    def generate_baselines(self, records: list[dict]) -> None:
        """Generate baseline fingerprints for loss guard validation.

        Override for multi-stream providers (e.g., google-developer).
        Raises RuntimeError if saving any baseline fails.
        """
        if self.STREAMS:
            from loss_guard import generate_all_provider_baselines

            results = generate_all_provider_baselines(records, self.PLATFORM_NAME)
            if not results or not all(results.values()):
                raise RuntimeError(
                    f"Failed to save one or more stream baselines for {self.PLATFORM_NAME}: {results}"
                )
        else:
            from loss_guard import generate_provider_baseline as _gen_baseline

            if not _gen_baseline(records, self.PLATFORM_NAME):
                raise RuntimeError(f"Failed to save baseline for {self.PLATFORM_NAME}")

    @property
    def INPUT_JSON_PATH(self) -> str:
        """Get the input JSON path from module-level JSON_PATH variable.

        This property reads the module-level JSON_PATH variable which can be
        patched by tests. Subclasses should override if they need different behavior.
        """
        # Import the module-level JSON_PATH from the subclass's module
        import sys

        module = sys.modules.get(self.__class__.__module__)
        if module and hasattr(module, "JSON_PATH"):
            return module.JSON_PATH
        return self.JSON_PATH or ""

    @property
    def INPUT_MONOLITH_PATH(self) -> str:
        """Get the input monolith path from module-level MONOLITH_PATH variable.

        This property reads the module-level MONOLITH_PATH variable which can be
        patched by tests via patch. Falls back to class attribute MONOLITH_PATH.
        """
        import sys

        module = sys.modules.get(self.__class__.__module__)
        if module and hasattr(module, "MONOLITH_PATH"):
            return module.MONOLITH_PATH
        # Fall back to class attribute (production default)
        return getattr(self.__class__, "MONOLITH_PATH", "") or ""

    def run(self):
        """Execute complete pipeline."""
        self.logger.info(f"[START] Starting {self.PLATFORM_DISPLAY_NAME} Pipeline...")

        # 1. Fetch & parse
        raw = self.fetch_data()
        records = self.parse_data(raw)

        if not records:
            self.logger.error("[FAIL] No records extracted. Aborting.")
            sys.exit(1)

        # 2. Pre-guard hook (deduplication, etc.)
        records = self.pre_loss_guard(records)

        # 3. Run loss guards (orchestrated) - READ ONLY, no baseline persistence
        if self.STREAMS:
            run_provider_loss_guards(
                records,
                self.PLATFORM_NAME,
                fail_on_warn=self.FAIL_ON_WARN,
                json_path=self.INPUT_JSON_PATH,
                monolith_path=self.INPUT_MONOLITH_PATH,
                persist_baseline=False,
            )
        else:
            run_provider_loss_guards(
                records,
                self.PLATFORM_NAME,
                fail_on_warn=self.FAIL_ON_WARN,
                json_path=self.INPUT_JSON_PATH,
                monolith_path=self.INPUT_MONOLITH_PATH,
                persist_baseline=False,
            )

        # 4. Post-guard hook (retired marking)
        records = self.post_loss_guard(records)

        # 5-13. Transactional publication phase: any failure rolls back all
        # generated artifacts and prevents baselines from advancing.
        # GitHub baseline recovery workflows (temporarily commenting out CI checks
        # to regenerate corrupted baselines) continue to work because the gate
        # only rejects failed publication steps, not clean regenerations.
        with self._publication_transaction():
            # 5. Persist validation data
            self.persist_validation(records)

            # 6. Sort for archive (newest first)
            records.sort(key=self._sort_key, reverse=True)

            # 7. Format for archive
            formatted_rows = [self.format_for_archive(r) for r in records]

            # 8. Build README lines with placeholder slice (will be replaced after archive generation)
            readme_lines = self.build_readme_lines(records, "")

            # 9. Generate archive with README lines (archiver writes README with placeholders)
            latest_slice = self.generate_archive(formatted_rows, readme_lines)

            # 10. Replace placeholder slice links in readme_lines with actual latest_slice
            if latest_slice:
                LATEST_SLICE_NORMAL = "./archives/" + latest_slice
                LATEST_SLICE_RAW = RAW_BASE_DEFAULT + "/" + latest_slice
                for i, line in enumerate(readme_lines):
                    if "{LATEST_SLICE_NORMAL}" in line:
                        readme_lines[i] = line.replace(
                            "{LATEST_SLICE_NORMAL}", LATEST_SLICE_NORMAL
                        ).replace("{LATEST_SLICE_RAW}", LATEST_SLICE_RAW)
                        break

            # 11. Update README with resolved slice links
            self.update_readme(readme_lines, latest_slice)

            # 12. Generate baseline (all local generation complete)
            self.generate_baselines(records)

            # 13. Sync fixtures (now copies the NEW baseline files)
            self.sync_fixtures()

        self.logger.info(
            f"[DONE] {self.PLATFORM_DISPLAY_NAME} pipeline complete ({len(records)} combined items)."
        )

    def _sort_key(self, record):
        date = record.get("date", "0000-00-00")
        if date is None or date == "N/A":
            return "0000-00-00"
        return date

    def persist_validation(self, records):
        """Persist validated data with layer metadata."""
        # Fix 3: Contamination detection - fail if record count is suspiciously low
        # Only run in CI environment (not in local tests or pytest)
        in_ci = os.getenv("CI") == "true"
        in_pytest = (
            "pytest" in sys.modules
            or os.getenv("PYTEST_CURRENT_TEST") is not None
            or "PYTEST_VERSION" in os.environ
        )
        if in_ci and not in_pytest:
            # MIN_EXPECTED is defined in child pipeline modules
            min_expected = getattr(self, "MIN_EXPECTED", {}).get(self.PLATFORM_NAME, 0)
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
        validation_dir = self._effective_validation_dir()
        os.makedirs(validation_dir, exist_ok=True)
        validation_file = os.path.join(validation_dir, f"{self.PLATFORM_NAME}.json")

        payload = self.get_validation_payload(records)
        self._write_validation_payload(validation_file, payload, ensure_ascii=False)

    def generate_archive(self, formatted_rows, readme_lines):
        """Generate markdown archive via archiver module."""
        if not generate_platform_archive:
            raise RuntimeError(
                "Archiver module not available; cannot generate markdown archives."
            )

        retrieved_at = datetime.now(UTC).isoformat()
        latest_slice = generate_platform_archive(
            platform_prefix=self.PLATFORM_PREFIX,
            platform_name=self.PLATFORM_DISPLAY_NAME,
            table_headers=self.TABLE_HEADERS,
            table_alignments=self.TABLE_ALIGNMENTS,
            formatted_rows=formatted_rows,
            readme_lines=readme_lines,
            marker_start=self.MARKER_START,
            marker_end=self.MARKER_END,
            archive_dir=self._effective_archive_dir(),
            readme_path=self._effective_readme_path(),
            retrieved_at=retrieved_at,
        )
        if formatted_rows and not latest_slice:
            raise RuntimeError(
                f"Archive generation returned no latest slice for {self.PLATFORM_NAME}"
            )
        return latest_slice

    def update_readme(self, readme_lines: list[str], latest_slice: str):
        """Update README.md with generated content."""
        readme_path = self._effective_readme_path()
        if not os.path.exists(readme_path):
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

        with open(readme_path, "r", encoding="utf-8") as f:
            readme_content = f.read()

        if self.MARKER_START in readme_content and self.MARKER_END in readme_content:
            before = readme_content.split(self.MARKER_START)[0]
            after = readme_content.split(self.MARKER_END)[1]
            new_block = "\n".join(readme_lines) + "\n"
            new_content = (
                before + self.MARKER_START + "\n" + new_block + self.MARKER_END + after
            )
            if not safe_write_file:
                raise RuntimeError("archiver.safe_write_file is unavailable")
            safe_write_file(readme_path, new_content)

    def sync_fixtures(self):
        """Sync baseline files to test fixtures (strict fail-fast)."""
        sync_fixtures(self.PLATFORM_NAME)


if __name__ == "__main__":
    # Allow running as standalone for testing
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    print("PipelineBase module - import and subclass to use")
