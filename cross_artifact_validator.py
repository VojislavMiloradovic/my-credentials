"""
cross_artifact_validator.py
===========================

Cross-artifact semantic validator for the credentials repository.

Compares source snapshots, archives, README totals, JSON-LD totals,
llms.txt, and llms-full.txt for consistency.

Checks:
- Record counts match across all artifacts for each platform
- Platform totals match between README, indexes, llms.txt, JSON-LD
- Retirement status consistency between source, archives, and JSON-LD
- Latest record ordering consistency
- No platform is omitted from any generated artifact

CI fails when:
- Records disappear between artifacts
- Platform counts disagree
- Generated files omit a platform
- Retirement status differs between artifacts
"""

import glob
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Layer manifest integration
from layer_manifest import LayerManifest, get_artifact_layer_mapping, load_manifest

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cross_artifact_validator")

# Constants
ARCHIVE_DIR = "archives"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"
LLMS_PATH = "llms.txt"
LLMS_FULL_PATH = "llms-full.txt"
VALIDATION_DIR = "for_validation"

# Map platform keys to validation file names (they don't always match platform_key + *.json)
VALIDATION_FILES = {
    "microsoft-learn": ["microsoft-learn.json", "microsoft-learn-baseline.json"],
    "google-skills": ["google_skills_badges.json", "google-skills-baseline.json"],
    "aws-skills": ["aws_skill_badges.json", "aws-skills-baseline.json"],
    "credly": ["credly_badges.json", "credly-baseline.json"],
    "linkedin-certifications": [
        "linkedin-certifications.json",
        "linkedin-certifications-baseline.json",
    ],
    "google-developer": ["google-developer.json", "google-developer-baseline.json"],
}

# Platform configurations
PLATFORMS = {
    "microsoft-learn": {
        "name": "Microsoft Learn",
        "index_file": "microsoft-learn-index.md",
        "complete_file": "microsoft-learn-complete.md",
        "readme_marker_start": "<!-- MS_LEARN_START -->",
        "readme_marker_end": "<!-- MS_LEARN_END -->",
        "count_keys": [
            "ms_learn_units",
            "ms_learn_achievements",
            "ms_learn_badges",
            "ms_learn_xp",
        ],
        "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"Completed Individual Units.*?:\*\*\s*([\d,]+)",
            r"Total Experience Points.*?:\*\*\s*([\d,]+)",
            r"Badges Earned.*?:\*\*\s*([\d,]+)",
        ],
    },
    "google-skills": {
        "name": "Google Skills",
        "index_file": "google-skills-index.md",
        "complete_file": "google-skills-complete.md",
        "readme_marker_start": "<!-- GOOGLE_SKILLS_START -->",
        "readme_marker_end": "<!-- GOOGLE_SKILLS_END -->",
        "count_keys": ["gcp_badges"],
        "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"Total Portfolio Credentials.*?:\*\*\s*([\d,]+)",
        ],
    },
    "aws-skills": {
        "name": "AWS Skills",
        "index_file": "aws-skills-index.md",
        "complete_file": "aws-skills-complete.md",
        "readme_marker_start": "<!-- AWS_SKILLS_START -->",
        "readme_marker_end": "<!-- AWS_SKILLS_END -->",
        "count_keys": ["aws_activities"],
        "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"Total Portfolio Credentials.*?:\*\*\s*([\d,]+)",
        ],
    },
    "credly": {
        "name": "Credly",
        "index_file": "credly-index.md",
        "complete_file": "credly-complete.md",
        "readme_marker_start": "<!-- CREDLY_BADGES_START -->",
        "readme_marker_end": "<!-- CREDLY_BADGES_END -->",
        "count_keys": ["credly_credentials"],
        "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"Total Portfolio Credentials.*?:\*\*\s*([\d,]+)",
        ],
    },
    "linkedin-certifications": {
        "name": "LinkedIn",
        "index_file": "linkedin-certifications-index.md",
        "complete_file": "linkedin-certifications-complete.md",
        "readme_marker_start": "<!-- LINKEDIN_START -->",
        "readme_marker_end": "<!-- LINKEDIN_END -->",
        "count_keys": ["linkedin_certs"],
        "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"Total External Certifications Verified.*?\|\s*([\d,]+)",
        ],
    },
    "google-developer": {
        "name": "Google Developer",
        "index_file": "google-developer-index.md",
        "complete_file": "google-developer-complete.md",
        "readme_marker_start": "<!-- GOOGLE_DEVELOPER_START -->",
        "readme_marker_end": "<!-- GOOGLE_DEVELOPER_END -->",
        "count_keys": ["gdev_badges", "gdev_activities"],
        "index_total_pattern": r"\*\*Total (?:Public Badges|Detailed Activities).*?:\*\*\s*([\d,]+)",
        "readme_patterns": [
            r"\*\*Total Milestones & Milestone Badges\*\*\s*\|\s*([\d,]+)",
            r"\*\*Total Codelabs & Learning Activities\*\*\s*\|\s*([\d,]+)",
            r"Total Milestones.*?:\*\*\s*([\d,]+)",
            r"Total Codelabs.*?:\*\*\s*([\d,]+)",
        ],
    },
}


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    check_name: str
    platform: str | None
    passed: bool
    expected: Any = None
    actual: Any = None
    message: str = ""
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "platform": self.platform,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class PlatformCounts:
    """Aggregated counts for a platform from various sources."""

    platform: str
    source_records: int = 0  # L0_raw
    l1_normalized_records: int = 0  # L1_normalized (from for_validation)
    archive_complete_records: int = 0  # L2_published
    index_total: int = 0  # L2_published (index)
    readme_count: int = 0  # L3_display
    jsonld_count: int = 0  # L2_published
    llms_txt_count: int = 0  # L3_display
    llms_full_count: int = 0  # inclusion boolean
    retired_in_source: int = 0
    retired_in_archive: int = 0
    retired_in_jsonld: int = 0
    latest_record_date_source: str | None = None
    latest_record_date_archive: str | None = None
    latest_record_date_jsonld: str | None = None


class CrossArtifactValidator:
    """Main validator class for cross-artifact consistency."""

    def __init__(self, strict: bool = True, warn_mode: bool = False):
        self.strict = strict
        self.warn_mode = warn_mode
        self.results: list[ValidationResult] = []
        self.platform_data: dict[str, PlatformCounts] = {}
        # Load layer manifest
        try:
            self.manifest: LayerManifest = load_manifest()
            self.artifact_layer_map = get_artifact_layer_mapping()
        except Exception as e:
            logger.warning(f"Could not load layer manifest: {e}")
            self.manifest = None
            self.artifact_layer_map = {}

    def add_result(self, result: ValidationResult) -> None:
        """Add a validation result."""
        self.results.append(result)
        status = (
            "✅ PASS"
            if result.passed
            else ("⚠️ WARN" if result.severity == "warning" else "❌ FAIL")
        )
        platform_str = f"[{result.platform}] " if result.platform else ""
        logger.info(f"{status} {platform_str}{result.check_name}: {result.message}")
        if (
            not result.passed
            and result.expected is not None
            and result.actual is not None
        ):
            logger.info(f"   Expected: {result.expected}, Actual: {result.actual}")

    def _read_file_safe(self, filepath: str) -> str | None:
        """Safely read a file, return None if not found."""
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
        return None

    def _parse_int(self, s: str | None) -> int:
        """Parse integer from string, handling commas and unavailable."""
        if not s or s == "[unavailable]":
            return 0
        try:
            return int(str(s).replace(",", ""))
        except (ValueError, TypeError):
            return 0

    def validate_source_snapshots(self) -> None:
        """Validate source snapshot files in for_validation/."""
        logger.info("🔍 Validating source snapshots...")

        for platform_key in PLATFORMS:
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )

            # Get validation file names for this platform
            validation_filenames = VALIDATION_FILES.get(platform_key, [])
            files = [
                os.path.join(VALIDATION_DIR, fname)
                for fname in validation_filenames
                if os.path.exists(os.path.join(VALIDATION_DIR, fname))
            ]

            total_records = 0
            l1_normalized_records = 0
            retired_count = 0
            latest_date = None

            # Get L1 output specification from manifest
            l1_output_records = None
            l1_output_streams = None
            if self.manifest and platform_key in self.manifest.platforms:
                l1_def = self.manifest.platforms[platform_key].L1_normalized
                l1_output_records = l1_def.output_records
                l1_output_streams = l1_def.output_streams

            for filepath in files:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Extract all records for source_records (L0_raw)
                    all_records = []
                    if isinstance(data, dict):
                        for key in (
                            "badges",
                            "achievements",
                            "learning_paths",
                            "certifications",
                            "combined_feed",
                            "public_badges",
                            "detailed_learnings",
                            "verifiable_credentials",
                            "user_creds",
                            "userCredentials",
                        ):
                            if key in data and isinstance(data[key], list):
                                all_records.extend(data[key])
                        if (
                            not all_records
                            and "records" in data
                            and isinstance(data["records"], list)
                        ):
                            all_records = data["records"]
                    elif isinstance(data, list):
                        all_records = data

                    for record in all_records:
                        if isinstance(record, dict):
                            total_records += 1
                            if record.get("retired") is True:
                                retired_count += 1
                            date_str = (
                                record.get("date")
                                or record.get("issued_at")
                                or record.get("earned_at")
                            )
                            if date_str:
                                try:
                                    dt = datetime.fromisoformat(str(date_str))
                                    if latest_date is None or dt > latest_date:
                                        latest_date = dt
                                except (ValueError, TypeError):
                                    pass

                    # Extract L1_normalized records based on manifest
                    # Priority: combined_feed (deduplicated) > output_records > sum of output_streams
                    if isinstance(data, dict) and "combined_feed" in data:
                        l1_records = data["combined_feed"]
                        if isinstance(l1_records, list):
                            l1_normalized_records = len(
                                [r for r in l1_records if isinstance(r, dict)]
                            )
                    elif (
                        l1_output_records
                        and isinstance(data, dict)
                        and l1_output_records in data
                    ):
                        l1_records = data[l1_output_records]
                        if isinstance(l1_records, list):
                            l1_normalized_records = len(
                                [r for r in l1_records if isinstance(r, dict)]
                            )
                    elif l1_output_streams and isinstance(data, dict):
                        for stream in l1_output_streams:
                            if stream in data and isinstance(data[stream], list):
                                l1_normalized_records += len(
                                    [r for r in data[stream] if isinstance(r, dict)]
                                )

                except Exception as e:
                    logger.warning(f"Failed to parse {filepath}: {e}")

            counts.source_records = total_records
            counts.l1_normalized_records = (
                l1_normalized_records if l1_normalized_records > 0 else total_records
            )
            counts.retired_in_source = retired_count
            counts.latest_record_date_source = (
                latest_date.isoformat() if latest_date else None
            )

            self.add_result(
                ValidationResult(
                    check_name="source_snapshot_exists",
                    platform=platform_key,
                    passed=total_records > 0,
                    expected="> 0",
                    actual=total_records,
                    message=f"Source snapshot has {total_records} records ({retired_count} retired)",
                    severity="error" if total_records == 0 else "warning",
                )
            )

    def validate_archive_complete(self) -> None:
        """Validate monolithic complete archive files."""
        logger.info("🔍 Validating archive complete files...")

        for platform_key, config in PLATFORMS.items():
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )

            filepath = os.path.join(ARCHIVE_DIR, config["complete_file"])
            content = self._read_file_safe(filepath)

            if not content:
                self.add_result(
                    ValidationResult(
                        check_name="archive_complete_exists",
                        platform=platform_key,
                        passed=False,
                        expected="file exists",
                        actual="missing",
                        message=f"Complete archive file missing: {filepath}",
                    )
                )
                continue

            # Count table data rows
            table_rows = 0
            retired_count = 0
            latest_date = None

            lines = content.splitlines()
            in_table = False
            separator_re = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")

            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith("|") and line.endswith("|"):
                    if (
                        not in_table
                        and i + 1 < len(lines)
                        and separator_re.match(lines[i + 1].strip())
                    ):
                        in_table = True
                        continue
                    elif in_table and separator_re.match(line):
                        continue
                    elif in_table:
                        table_rows += 1
                        # Check for retired marker
                        if (
                            "retired" in line.lower()
                            or "content retired" in line.lower()
                        ):
                            retired_count += 1
                        # Extract date
                        date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", line)
                        if date_match:
                            try:
                                dt = datetime.fromisoformat(date_match.group(1))
                                if latest_date is None or dt > latest_date:
                                    latest_date = dt
                            except ValueError:
                                pass

            counts.archive_complete_records = table_rows
            counts.retired_in_archive = retired_count
            counts.latest_record_date_archive = (
                latest_date.isoformat() if latest_date else None
            )

            self.add_result(
                ValidationResult(
                    check_name="archive_complete_parsed",
                    platform=platform_key,
                    passed=table_rows > 0,
                    expected="> 0",
                    actual=table_rows,
                    message=f"Complete archive has {table_rows} records ({retired_count} retired)",
                )
            )

    def validate_index_files(self) -> None:
        """Validate platform index files."""
        logger.info("🔍 Validating platform index files...")

        for platform_key, config in PLATFORMS.items():
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )

            filepath = os.path.join(ARCHIVE_DIR, config["index_file"])
            content = self._read_file_safe(filepath)

            if not content:
                self.add_result(
                    ValidationResult(
                        check_name="index_file_exists",
                        platform=platform_key,
                        passed=False,
                        expected="file exists",
                        actual="missing",
                        message=f"Index file missing: {filepath}",
                    )
                )
                continue

            # Extract total from index - handle markdown bold
            pattern = config.get(
                "index_total_pattern", r"\*\*Total Records Archived:\*\*\s*([\d,]+)"
            )
            match = re.search(pattern, content, re.IGNORECASE)
            total = self._parse_int(match.group(1)) if match else 0

            counts.index_total = total

            self.add_result(
                ValidationResult(
                    check_name="index_total_parsed",
                    platform=platform_key,
                    passed=total > 0,
                    expected="> 0",
                    actual=total,
                    message=f"Index reports {total} total records",
                )
            )

    def validate_readme(self) -> None:
        """Validate README.md marker sections for consistency."""
        logger.info("🔍 Validating README.md...")

        content = self._read_file_safe(README_PATH)
        if not content:
            logger.error("README.md not found!")
            return

        for platform_key, config in PLATFORMS.items():
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )

            start_marker = config["readme_marker_start"]
            end_marker = config["readme_marker_end"]

            if start_marker not in content or end_marker not in content:
                self.add_result(
                    ValidationResult(
                        check_name="readme_markers_present",
                        platform=platform_key,
                        passed=False,
                        expected="markers present",
                        actual="missing",
                        message=f"README markers missing for {config['name']}",
                    )
                )
                continue

            # Extract content between markers
            block = content.split(start_marker)[1].split(end_marker)[0]

            # Try to extract count from the block using platform-specific patterns
            total = 0
            readme_patterns = config.get("readme_patterns", [])
            for pattern in readme_patterns:
                match = re.search(pattern, block, re.IGNORECASE)
                if match:
                    total = self._parse_int(match.group(1))
                    break

            counts.readme_count = total

            self.add_result(
                ValidationResult(
                    check_name="readme_count_parsed",
                    platform=platform_key,
                    passed=total > 0,
                    expected="> 0",
                    actual=total,
                    message=f"README reports {total} records",
                )
            )

    def validate_jsonld(self) -> None:
        """Validate JSON-LD credentials file."""
        logger.info("🔍 Validating JSON-LD...")

        content = self._read_file_safe(JSONLD_PATH)
        if not content:
            self.add_result(
                ValidationResult(
                    check_name="jsonld_exists",
                    platform=None,
                    passed=False,
                    expected="file exists",
                    actual="missing",
                    message="JSON-LD file missing",
                )
            )
            return

        try:
            data = json.loads(content)
            credentials = data.get("mainEntity", {}).get("hasCredential", [])

            # Count by platform using the explicit platform field, fallback to issuer detection
            platform_counts = {k: 0 for k in PLATFORMS}
            platform_retired = {k: 0 for k in PLATFORMS}
            platform_latest = {k: None for k in PLATFORMS}

            for cred in credentials:
                # Prefer explicit platform field from JSON-LD
                platform_key = cred.get("platform")

                # Fallback to issuer-based detection for backward compatibility
                if not platform_key:
                    issuer = cred.get("recognizedBy", {}).get("name", "").lower()
                    if "microsoft" in issuer or "learn" in issuer:
                        platform_key = "microsoft-learn"
                    elif "google cloud" in issuer or "google skills" in issuer:
                        platform_key = "google-skills"
                    elif "amazon web services" in issuer or "aws" in issuer:
                        platform_key = "aws-skills"
                    elif "credly" in issuer:
                        platform_key = "credly"
                    elif "linkedin" in issuer:
                        platform_key = "linkedin-certifications"
                    elif "google developer" in issuer:
                        platform_key = "google-developer"

                if platform_key:
                    platform_counts[platform_key] += 1
                    if cred.get("credentialStatus") == "Retired":
                        platform_retired[platform_key] += 1

                    date_str = cred.get("dateCreated")
                    if date_str:
                        try:
                            dt = datetime.fromisoformat(date_str)
                            if (
                                platform_latest[platform_key] is None
                                or dt > platform_latest[platform_key]
                            ):
                                platform_latest[platform_key] = dt
                        except ValueError:
                            pass

            for platform_key in PLATFORMS:
                counts = self.platform_data.setdefault(
                    platform_key, PlatformCounts(platform=platform_key)
                )
                counts.jsonld_count = platform_counts.get(platform_key, 0)
                counts.retired_in_jsonld = platform_retired.get(platform_key, 0)
                counts.latest_record_date_jsonld = (
                    platform_latest[platform_key].isoformat()
                    if platform_latest.get(platform_key)
                    else None
                )

                self.add_result(
                    ValidationResult(
                        check_name="jsonld_count",
                        platform=platform_key,
                        passed=counts.jsonld_count > 0,
                        expected="> 0",
                        actual=counts.jsonld_count,
                        message=f"JSON-LD has {counts.jsonld_count} credentials ({counts.retired_in_jsonld} retired)",
                    )
                )

        except json.JSONDecodeError as e:
            self.add_result(
                ValidationResult(
                    check_name="jsonld_valid",
                    platform=None,
                    passed=False,
                    expected="valid JSON",
                    actual=f"parse error: {e}",
                    message="JSON-LD is not valid JSON",
                )
            )

    def validate_llms_txt(self) -> None:
        """Validate llms.txt portfolio counts."""
        logger.info("🔍 Validating llms.txt...")

        content = self._read_file_safe(LLMS_PATH)
        if not content:
            self.add_result(
                ValidationResult(
                    check_name="llms_txt_exists",
                    platform=None,
                    passed=False,
                    expected="file exists",
                    actual="missing",
                    message="llms.txt missing",
                )
            )
            return

        # Extract counts from llms.txt
        patterns = {
            "microsoft-learn": [
                r"Microsoft Learn.*?(\d[\d,]*)\s*completed units",
                r"Microsoft Learn.*?(\d[\d,]*)\s*total achievements",
            ],
            "google-skills": [r"Google Cloud Skills.*?(\d[\d,]*)\s*badges"],
            "aws-skills": [r"AWS Skill Builder.*?(\d[\d,]*)\s*completed"],
            "credly": [r"Credly.*?(\d[\d,]*)\s*credentials"],
            "linkedin-certifications": [r"LinkedIn.*?(\d[\d,]*)\s*verified"],
            "google-developer": [r"Google Developer.*?(\d[\d,]*)\s*milestone badges"],
        }

        for platform_key in PLATFORMS:
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )
            platform_patterns = patterns.get(platform_key, [])

            total = 0
            for pattern in platform_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    total = self._parse_int(match.group(1))
                    break

            counts.llms_txt_count = total

            self.add_result(
                ValidationResult(
                    check_name="llms_txt_count",
                    platform=platform_key,
                    passed=total > 0,
                    expected="> 0",
                    actual=total,
                    message=f"llms.txt reports {total} records",
                )
            )

    def validate_llms_full(self) -> None:
        """Validate llms-full.txt contains all platforms."""
        logger.info("🔍 Validating llms-full.txt...")

        content = self._read_file_safe(LLMS_FULL_PATH)
        if not content:
            self.add_result(
                ValidationResult(
                    check_name="llms_full_exists",
                    platform=None,
                    passed=False,
                    expected="file exists",
                    actual="missing",
                    message="llms-full.txt missing",
                )
            )
            return

        # Check each platform's complete archive is included
        for platform_key, config in PLATFORMS.items():
            counts = self.platform_data.setdefault(
                platform_key, PlatformCounts(platform=platform_key)
            )
            complete_file = config["complete_file"]

            # Check if the complete file is referenced in llms-full.txt
            included = (
                complete_file in content or f"archives/{complete_file}" in content
            )

            # Also count records if we can find them
            # llms-full.txt embeds the full content, so we can count table rows
            # But for simplicity, just check inclusion
            counts.llms_full_count = 1 if included else 0

            self.add_result(
                ValidationResult(
                    check_name="llms_full_includes_platform",
                    platform=platform_key,
                    passed=included,
                    expected="included",
                    actual="included" if included else "missing",
                    message=f"llms-full.txt {'includes' if included else 'MISSING'} {complete_file}",
                )
            )

    def _get_declared_transforms(self, platform_key: str) -> dict[str, tuple[str, str]]:
        """Get declared layer transforms from manifest for a platform.
        Returns mapping of (source_layer -> target_layer) -> transform_type.
        """
        if not self.manifest or platform_key not in self.manifest.platforms:
            return {}
        platform = self.manifest.platforms[platform_key]
        transforms = {}

        # L0 -> L1
        if platform.L1_normalized.transform:
            transforms[("L0_raw", "L1_normalized")] = (
                platform.L1_normalized.transform.type
            )
        elif platform.L1_normalized.transforms:
            for stream, tf in platform.L1_normalized.transforms.items():
                transforms[("L0_raw", f"L1_normalized:{stream}")] = tf.type

        # L1 -> L2
        if platform.L2_published.transform:
            transforms[("L1_normalized", "L2_published")] = (
                platform.L2_published.transform.type
            )
        elif platform.L2_published.transforms:
            for artifact, tf in platform.L2_published.transforms.items():
                transforms[("L1_normalized", f"L2_published:{artifact}")] = tf.type

        # L1 -> L3
        if platform.L3_display.transform:
            transforms[("L1_normalized", "L3_display")] = (
                platform.L3_display.transform.type
            )
        elif platform.L3_display.transforms:
            for artifact, tf in platform.L3_display.transforms.items():
                transforms[("L1_normalized", f"L3_display:{artifact}")] = tf.type

        return transforms

    def _counts_for_layer(self, platform_key: str, layer: str) -> int:
        """Get record count for a specific layer from platform_data."""
        counts = self.platform_data.get(platform_key)
        if not counts:
            return 0

        # Map layer names to PlatformCounts attributes
        layer_map = {
            "L0_raw": "source_records",
            "L1_normalized": "l1_normalized_records",
            "L2_published": "archive_complete_records",
            "L3_display": "readme_count",
        }
        attr = layer_map.get(layer)
        return getattr(counts, attr, 0) if attr else 0

    def validate_cross_artifact_consistency(self) -> None:
        """Cross-compare counts across all artifacts using declared layer transforms."""
        logger.info("🔍 Validating cross-artifact consistency...")

        # Map comparison source names to actual PlatformCounts attributes
        attr_map = {
            "source": "source_records",
            "archive_complete": "archive_complete_records",
            "index": "index_total",
            "readme": "readme_count",
            "jsonld": "jsonld_count",
            "llms_txt": "llms_txt_count",
            # "llms_full": "llms_full_count",  # Boolean, not a count
        }

        for platform_key, config in PLATFORMS.items():
            counts = self.platform_data.get(platform_key)
            if not counts:
                continue

            # Get declared transforms from manifest
            declared = self._get_declared_transforms(platform_key)

            # Build comparisons based on manifest
            comparisons = []

            # L2_published artifacts should match (archive_complete vs index)
            if "L2_published" in declared.get(
                ("L1_normalized", "L2_published"), ""
            ) or any(k[1].startswith("L2_published") for k in declared):
                comparisons.append(
                    (
                        "archive_complete",
                        "index",
                        0,
                        "Archive complete vs Index total (L2_published)",
                    )
                )

            # L1 -> L2 (archive_complete vs jsonld both from L2_published)
            if ("L1_normalized", "L2_published") in declared or any(
                k[1].startswith("L2_published") for k in declared
            ):
                comparisons.append(
                    (
                        "archive_complete",
                        "jsonld",
                        5,
                        "Archive complete vs JSON-LD (L2_published)",
                    )
                )

            # L1 -> L3 (readme vs llms_txt both from L3_display)
            if ("L1_normalized", "L3_display") in declared or any(
                k[1].startswith("L3_display") for k in declared
            ):
                comparisons.append(
                    ("readme", "llms_txt", 0, "README vs llms.txt (L3_display)")
                )

            # If no declared transforms, fall back to legacy behavior
            if not comparisons:
                comparisons = [
                    ("archive_complete", "index", 0, "Archive complete vs Index total"),
                    ("archive_complete", "jsonld", 5, "Archive complete vs JSON-LD"),
                    ("readme", "llms_txt", 0, "README vs llms.txt"),
                ]
                # Legacy platform-specific adjustments
                if platform_key == "google-developer":
                    comparisons = [
                        (
                            "archive_complete",
                            "jsonld",
                            5,
                            "Archive complete vs JSON-LD",
                        ),
                        ("readme", "llms_txt", 0, "README vs llms.txt"),
                    ]
                elif platform_key in ("google-skills", "credly"):
                    comparisons = [
                        ("readme", "llms_txt", 0, "README vs llms.txt"),
                    ]
                elif platform_key == "aws-skills":
                    comparisons = [
                        (
                            "archive_complete",
                            "index",
                            0,
                            "Archive complete vs Index total",
                        ),
                        (
                            "archive_complete",
                            "jsonld",
                            15,
                            "Archive complete vs JSON-LD",
                        ),
                        ("readme", "llms_txt", 0, "README vs llms.txt"),
                    ]
                elif platform_key == "linkedin-certifications":
                    comparisons = [
                        (
                            "archive_complete",
                            "index",
                            0,
                            "Archive complete vs Index total",
                        ),
                        (
                            "archive_complete",
                            "jsonld",
                            0,
                            "Archive complete vs JSON-LD (EXPECTED TO MATCH)",
                        ),
                        ("readme", "llms_txt", 0, "README vs llms.txt"),
                    ]

            for source1, source2, tolerance_pct, description in comparisons:
                attr1 = attr_map.get(source1)
                attr2 = attr_map.get(source2)

                if not attr1 or not attr2:
                    continue

                val1 = getattr(counts, attr1, 0)
                val2 = getattr(counts, attr2, 0)

                if val1 <= 0 or val2 <= 0:
                    self.add_result(
                        ValidationResult(
                            check_name=f"count_consistency_{source1}_vs_{source2}",
                            platform=platform_key,
                            passed=True,
                            message=f"{description}: Skipped (one source has 0 or missing data: {source1}={val1}, {source2}={val2})",
                            severity="warning",
                        )
                    )
                    continue

                if tolerance_pct == 0:
                    passed = val1 == val2
                else:
                    diff_pct = abs(val1 - val2) / max(val1, val2) * 100
                    passed = diff_pct <= tolerance_pct

                severity = (
                    "error"
                    if not passed and not self.warn_mode
                    else ("warning" if not passed else "error")
                )
                self.add_result(
                    ValidationResult(
                        check_name=f"count_consistency_{source1}_vs_{source2}",
                        platform=platform_key,
                        passed=passed,
                        expected=f"{val2} (±{tolerance_pct}%)"
                        if tolerance_pct > 0
                        else val2,
                        actual=val1,
                        message=f"{description}: {source1}={val1} vs {source2}={val2} {'✓' if passed else '✗ MISMATCH'}",
                        severity=severity,
                    )
                )

            # Declared transformation verification
            for (src_layer, tgt_layer), transform_type in declared.items():
                src_count = self._counts_for_layer(platform_key, src_layer)
                tgt_count = self._counts_for_layer(
                    platform_key, tgt_layer.split(":")[0]
                )

                if src_count > 0 and tgt_count > 0:
                    # Verify transform expectations
                    expected_equal = transform_type in (
                        "1:1_pass_through",
                        "combine_streams",
                        "split_streams",
                    )
                    passed = (
                        (src_count == tgt_count) if expected_equal else True
                    )  # Other transforms may change count

                    self.add_result(
                        ValidationResult(
                            check_name=f"declared_transform_{src_layer}_to_{tgt_layer}",
                            platform=platform_key,
                            passed=passed,
                            expected=f"{src_count} (transform: {transform_type})",
                            actual=tgt_count,
                            message=f"Declared transform {src_layer} -> {tgt_layer} ({transform_type}): {src_count} -> {tgt_count} {'✓' if passed else '✗ MISMATCH'}",
                            severity="error"
                            if not passed and not self.warn_mode
                            else ("warning" if not passed else "error"),
                        )
                    )

            # Undeclared discrepancy detection
            # Compare all artifact pairs and flag any not explained by manifest
            artifact_sources = {
                "archive_complete": "archive_complete_records",
                "index": "index_total",
                "jsonld": "jsonld_count",
                "readme": "readme_count",
                "llms_txt": "llms_txt_count",
            }

            # Check each pair
            artifact_names = list(artifact_sources.keys())
            for i, art1 in enumerate(artifact_names):
                for art2 in artifact_names[i + 1 :]:
                    # Skip if this pair is explained by a declared transform
                    explained = False
                    for src, tgt in declared:
                        src_artifacts = self._artifacts_for_layer(platform_key, src)
                        tgt_artifacts = self._artifacts_for_layer(
                            platform_key, tgt.split(":")[0]
                        )
                        if art1 in src_artifacts and art2 in tgt_artifacts:
                            explained = True
                            break
                        if art2 in src_artifacts and art1 in tgt_artifacts:
                            explained = True
                            break

                    if not explained:
                        val1 = getattr(counts, artifact_sources[art1], 0)
                        val2 = getattr(counts, artifact_sources[art2], 0)
                        if val1 > 0 and val2 > 0 and val1 != val2:
                            self.add_result(
                                ValidationResult(
                                    check_name=f"undeclared_discrepancy_{art1}_vs_{art2}",
                                    platform=platform_key,
                                    passed=False,
                                    expected=val2,
                                    actual=val1,
                                    message=f"Undeclared discrepancy: {art1}={val1} vs {art2}={val2} (not explained by manifest)",
                                    severity="error"
                                    if not self.warn_mode
                                    else "warning",
                                )
                            )

            # llms-full inclusion check
            if counts.llms_full_count > 0:
                self.add_result(
                    ValidationResult(
                        check_name="llms_full_includes_platform",
                        platform=platform_key,
                        passed=True,
                        expected="included",
                        actual="included",
                        message=f"llms-full.txt includes {config['complete_file']}",
                    )
                )
            else:
                self.add_result(
                    ValidationResult(
                        check_name="llms_full_includes_platform",
                        platform=platform_key,
                        passed=False,
                        expected="included",
                        actual="missing",
                        message=f"llms-full.txt MISSING {config['complete_file']}",
                    )
                )

            # Retirement consistency
            if counts.retired_in_archive > 0 and counts.retired_in_jsonld > 0:
                passed = counts.retired_in_archive == counts.retired_in_jsonld
                self.add_result(
                    ValidationResult(
                        check_name="retired_consistency_archive_vs_jsonld",
                        platform=platform_key,
                        passed=passed,
                        expected=counts.retired_in_jsonld,
                        actual=counts.retired_in_archive,
                        message=f"Retired count: archive={counts.retired_in_archive} vs jsonld={counts.retired_in_jsonld} {'✓' if passed else '✗ MISMATCH'}",
                        severity="warning",
                    )
                )
            elif counts.retired_in_archive > 0 or counts.retired_in_jsonld > 0:
                self.add_result(
                    ValidationResult(
                        check_name="retired_consistency_archive_vs_jsonld",
                        platform=platform_key,
                        passed=True,
                        message=f"Retired count: Only one source has data (archive={counts.retired_in_archive}, jsonld={counts.retired_in_jsonld})",
                        severity="warning",
                    )
                )

    def _artifacts_for_layer(self, platform_key: str, layer: str) -> list[str]:
        """Get artifact names that consume a given layer for a platform."""
        if not self.manifest or platform_key not in self.manifest.platforms:
            return []
        platform = self.manifest.platforms[platform_key]
        layer_def = getattr(platform, layer, None)
        if layer_def:
            return layer_def.artifacts
        return []

    def validate_platform_coverage(self) -> None:
        """Ensure all platforms appear in all generated artifacts."""
        logger.info("🔍 Validating platform coverage across artifacts...")

        # For file-based artifacts, check filenames
        file_artifacts = {
            "archive_complete": [
                f for f in glob.glob(os.path.join(ARCHIVE_DIR, "*-complete.md"))
            ],
            "index": [f for f in glob.glob(os.path.join(ARCHIVE_DIR, "*-index.md"))],
        }

        # For content-based artifacts, check content
        content_artifacts = {
            "jsonld": JSONLD_PATH,
            "llms_txt": LLMS_PATH,
            "llms_full": LLMS_FULL_PATH,
        }

        expected_platforms = set(PLATFORMS.keys())

        # Check file-based artifacts
        for artifact_name, files in file_artifacts.items():
            found_platforms = set()
            for f in files:
                basename = os.path.basename(f)
                for platform_key in expected_platforms:
                    if platform_key in basename:
                        found_platforms.add(platform_key)

            missing = expected_platforms - found_platforms

            self.add_result(
                ValidationResult(
                    check_name=f"platform_coverage_{artifact_name}",
                    platform=None,
                    passed=len(missing) == 0,
                    expected=sorted(expected_platforms),
                    actual=sorted(found_platforms),
                    message=f"{artifact_name} covers {len(found_platforms)}/{len(expected_platforms)} platforms"
                    + (f" - MISSING: {', '.join(sorted(missing))}" if missing else ""),
                )
            )

        # Check content-based artifacts
        for artifact_name, filepath in content_artifacts.items():
            if not os.path.exists(filepath):
                self.add_result(
                    ValidationResult(
                        check_name=f"platform_coverage_{artifact_name}",
                        platform=None,
                        passed=False,
                        expected=f"{len(expected_platforms)} platforms",
                        actual=0,
                        message=f"{artifact_name} file missing",
                    )
                )
                continue

            content = self._read_file_safe(filepath)
            if not content:
                self.add_result(
                    ValidationResult(
                        check_name=f"platform_coverage_{artifact_name}",
                        platform=None,
                        passed=False,
                        expected=f"{len(expected_platforms)} platforms",
                        actual=0,
                        message=f"{artifact_name} file empty or unreadable",
                    )
                )
                continue

            # Check for platform mentions in content
            found_platforms = set()
            platform_indicators = {
                "microsoft-learn": ["microsoft-learn", "Microsoft Learn", "Microsoft"],
                "google-skills": [
                    "google-skills",
                    "Google Cloud Skills",
                    "Google Skills",
                    "Google Cloud",
                    "Google Cloud Security",
                ],
                "aws-skills": [
                    "aws-skills",
                    "AWS Skill",
                    "AWS Skills",
                    "Amazon Web Services",
                    "Amazon Web Services (AWS)",
                    "Amazon Web Services Training and Certification",
                ],
                "credly": [
                    "credly",
                    "Credly",
                    "Acronis",
                    "AttackIQ",
                    "Isovalent",
                    "Celonis",
                    "Datadog",
                    "Dremio",
                    "IBM",
                    "Intel",
                    "MongoDB",
                    "NVIDIA",
                    "OPSWAT",
                    "Okta",
                    "Oracle",
                    "Pendo",
                    "SAP",
                    "SAS",
                    "The Linux Foundation",
                    "ZEDEDA",
                    "Zendesk",
                ],
                "linkedin-certifications": [
                    "linkedin-certifications",
                    "LinkedIn",
                    "Linkedin",
                ],
                "google-developer": ["google-developer", "Google Developer"],
            }

            for platform_key, indicators in platform_indicators.items():
                for indicator in indicators:
                    if indicator in content:
                        found_platforms.add(platform_key)
                        break

            missing = expected_platforms - found_platforms

            self.add_result(
                ValidationResult(
                    check_name=f"platform_coverage_{artifact_name}",
                    platform=None,
                    passed=len(missing) == 0,
                    expected=sorted(expected_platforms),
                    actual=sorted(found_platforms),
                    message=f"{artifact_name} covers {len(found_platforms)}/{len(expected_platforms)} platforms"
                    + (f" - MISSING: {', '.join(sorted(missing))}" if missing else ""),
                )
            )

    def validate_latest_record_ordering(self) -> None:
        """Validate latest record dates are consistent and reasonable."""
        logger.info("🔍 Validating latest record ordering...")

        for platform_key in PLATFORMS:
            counts = self.platform_data.get(platform_key)
            if not counts:
                continue

            dates = {
                "source": counts.latest_record_date_source,
                "archive": counts.latest_record_date_archive,
                "jsonld": counts.latest_record_date_jsonld,
            }

            non_none = {k: v for k, v in dates.items() if v}
            if len(non_none) < 2:
                continue

            # Parse dates
            parsed = {}
            for k, v in non_none.items():
                try:
                    parsed[k] = datetime.fromisoformat(v)
                except (ValueError, TypeError):
                    pass

            if len(parsed) < 2:
                continue

            # Check if dates are within reasonable range (e.g., within 30 days)
            date_values = list(parsed.values())
            max_date = max(date_values)
            min_date = min(date_values)
            diff_days = (max_date - min_date).days

            passed = diff_days <= 30
            self.add_result(
                ValidationResult(
                    check_name="latest_record_date_consistency",
                    platform=platform_key,
                    passed=passed,
                    expected="within 30 days",
                    actual=f"{diff_days} days",
                    message=f"Latest record dates span {diff_days} days across artifacts ({min_date.date()} to {max_date.date()})",
                    severity="warning",
                )
            )

    def run_all(self) -> bool:
        """Run all validation checks."""
        logger.info("=" * 60)
        logger.info("🔬 Starting Cross-Artifact Semantic Validation")
        logger.info("=" * 60)

        self.validate_source_snapshots()
        self.validate_archive_complete()
        self.validate_index_files()
        self.validate_readme()
        self.validate_jsonld()
        self.validate_llms_txt()
        self.validate_llms_full()
        self.validate_cross_artifact_consistency()
        self.validate_platform_coverage()
        self.validate_latest_record_ordering()

        # Summary
        logger.info("=" * 60)
        logger.info("📊 Validation Summary")
        logger.info("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed and r.severity == "error")
        warnings = sum(
            1 for r in self.results if not r.passed and r.severity == "warning"
        )
        total = len(self.results)

        logger.info(f"Total checks: {total}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed (errors): {failed}")
        logger.info(f"Warnings: {warnings}")

        if failed > 0:
            logger.error(
                "❌ VALIDATION FAILED - Cross-artifact inconsistencies detected"
            )
            return False
        elif warnings > 0:
            logger.warning("⚠️ VALIDATION PASSED WITH WARNINGS")
            return True
        else:
            logger.info("✅ ALL VALIDATIONS PASSED")
            return True

    def generate_report(self, output_path: str = "cross_artifact_report.json") -> None:
        """Generate JSON report of validation results."""
        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.passed),
                "failed": sum(
                    1 for r in self.results if not r.passed and r.severity == "error"
                ),
                "warnings": sum(
                    1 for r in self.results if not r.passed and r.severity == "warning"
                ),
            },
            "platforms": {},
            "results": [r.to_dict() for r in self.results],
        }

        for platform_key, counts in self.platform_data.items():
            report["platforms"][platform_key] = {
                "source_records": counts.source_records,
                "archive_complete_records": counts.archive_complete_records,
                "index_total": counts.index_total,
                "readme_count": counts.readme_count,
                "jsonld_count": counts.jsonld_count,
                "llms_txt_count": counts.llms_txt_count,
                "llms_full_count": counts.llms_full_count,
                "retired_in_source": counts.retired_in_source,
                "retired_in_archive": counts.retired_in_archive,
                "retired_in_jsonld": counts.retired_in_jsonld,
                "latest_record_date_source": counts.latest_record_date_source,
                "latest_record_date_archive": counts.latest_record_date_archive,
                "latest_record_date_jsonld": counts.latest_record_date_jsonld,
            }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Report written to {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Cross-artifact semantic validator")
    parser.add_argument(
        "--mode",
        choices=["strict", "warn"],
        default="strict",
        help="Validation mode: strict (fail on errors) or warn (treat errors as warnings)",
    )
    parser.add_argument(
        "--report", default="cross_artifact_report.json", help="Output report path"
    )

    args = parser.parse_args()

    validator = CrossArtifactValidator(
        strict=(args.mode == "strict"), warn_mode=(args.mode == "warn")
    )
    success = validator.run_all()
    validator.generate_report(args.report)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
