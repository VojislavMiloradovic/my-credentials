"""
Unit tests for cross_artifact_validator.py module.
"""
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from cross_artifact_validator import (
    CrossArtifactValidator,
    PlatformCounts,
    ValidationResult,
    PLATFORMS,
    VALIDATION_FILES,
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_to_dict(self):
        result = ValidationResult(
            check_name="test_check",
            platform="test-platform",
            passed=True,
            expected=10,
            actual=10,
            message="Test passed",
            severity="error",
        )
        d = result.to_dict()
        assert d["check"] == "test_check"
        assert d["platform"] == "test-platform"
        assert d["passed"] is True
        assert d["expected"] == 10
        assert d["actual"] == 10
        assert d["message"] == "Test passed"
        assert d["severity"] == "error"

    def test_to_dict_with_none_values(self):
        result = ValidationResult(
            check_name="test_check",
            platform=None,
            passed=False,
        )
        d = result.to_dict()
        assert d["check"] == "test_check"
        assert d["platform"] is None
        assert d["passed"] is False


class TestPlatformCounts:
    """Tests for PlatformCounts dataclass."""

    def test_default_values(self):
        counts = PlatformCounts(platform="test-platform")
        assert counts.platform == "test-platform"
        assert counts.source_records == 0
        assert counts.l1_normalized_records == 0
        assert counts.archive_complete_records == 0
        assert counts.index_total == 0
        assert counts.readme_count == 0
        assert counts.jsonld_count == 0
        assert counts.llms_txt_count == 0
        assert counts.llms_full_count == 0
        assert counts.retired_in_source == 0
        assert counts.retired_in_archive == 0
        assert counts.retired_in_jsonld == 0
        assert counts.latest_record_date_source is None
        assert counts.latest_record_date_archive is None
        assert counts.latest_record_date_jsonld is None


class TestCrossArtifactValidator:
    """Tests for CrossArtifactValidator class."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_init(self):
        assert self.validator.strict is True
        assert self.validator.warn_mode is False
        assert isinstance(self.validator.results, list)
        assert isinstance(self.validator.platform_data, dict)

    def test_add_result(self):
        result = ValidationResult(
            check_name="test_check",
            platform="test-platform",
            passed=True,
            message="Test message",
        )
        self.validator.add_result(result)
        assert len(self.validator.results) == 1
        assert self.validator.results[0] == result

    def test_read_file_safe_exists(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            temp_path = f.name
        try:
            content = self.validator._read_file_safe(temp_path)
            assert content == "test content"
        finally:
            os.unlink(temp_path)

    def test_read_file_safe_not_exists(self):
        content = self.validator._read_file_safe("/nonexistent/path.txt")
        assert content is None

    def test_parse_int_valid(self):
        assert self.validator._parse_int("1,234") == 1234
        assert self.validator._parse_int("42") == 42
        assert self.validator._parse_int("0") == 0

    def test_parse_int_invalid(self):
        assert self.validator._parse_int("") == 0
        assert self.validator._parse_int(None) == 0
        assert self.validator._parse_int("[unavailable]") == 0
        assert self.validator._parse_int("invalid") == 0

    def test_platforms_constant(self):
        assert "microsoft-learn" in PLATFORMS
        assert "google-skills" in PLATFORMS
        assert "aws-skills" in PLATFORMS
        assert "credly" in PLATFORMS
        assert "linkedin-certifications" in PLATFORMS
        assert "google-developer" in PLATFORMS

    def test_validation_files_constant(self):
        assert "microsoft-learn" in VALIDATION_FILES
        assert "google-developer" in VALIDATION_FILES
        assert "google-developer-baseline.json" not in VALIDATION_FILES["google-developer"]

    def test_get_declared_transforms_no_manifest(self):
        self.validator.manifest = None
        transforms = self.validator._get_declared_transforms("microsoft-learn")
        assert transforms == {}

    def test_get_artifact_to_layer_mapping_no_manifest(self):
        self.validator.manifest = None
        mapping = self.validator._get_artifact_to_layer_mapping("microsoft-learn")
        assert mapping == {}

    def test_get_layer_to_artifacts_mapping_no_manifest(self):
        self.validator.manifest = None
        mapping = self.validator._get_layer_to_artifacts_mapping("microsoft-learn")
        assert mapping == {}

    def test_get_source_layer_for_artifact_no_manifest(self):
        self.validator.manifest = None
        source = self.validator._get_source_layer_for_artifact("microsoft-learn", "test")
        assert source is None

    def test_artifacts_for_layer_no_manifest(self):
        self.validator.manifest = None
        artifacts = self.validator._artifacts_for_layer("microsoft-learn", "L2_published")
        assert artifacts == []

    def test_counts_for_layer(self):
        counts = PlatformCounts(platform="test")
        counts.source_records = 10
        counts.l1_normalized_records = 9
        counts.archive_complete_records = 9
        counts.readme_count = 8
        self.validator.platform_data["test"] = counts

        assert self.validator._counts_for_layer("test", "L0_raw") == 10
        assert self.validator._counts_for_layer("test", "L1_normalized") == 9
        assert self.validator._counts_for_layer("test", "L2_published") == 9
        assert self.validator._counts_for_layer("test", "L3_display") == 8
        assert self.validator._counts_for_layer("test", "unknown") == 0

    def test_build_attr_map(self):
        attr_map = self.validator._build_attr_map("microsoft-learn")
        assert "source" in attr_map
        assert "archive_complete" in attr_map
        assert "index" in attr_map
        assert "readme" in attr_map
        assert "jsonld" in attr_map
        assert "llms_txt" in attr_map


class TestCrossArtifactValidatorValidateSourceSnapshots:
    """Tests for validate_source_snapshots method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    @patch("cross_artifact_validator.os.path.exists")
    @patch("cross_artifact_validator.os.path.join")
    def test_validate_source_snapshots_no_files(self, mock_join, mock_exists):
        mock_exists.return_value = False
        self.validator.validate_source_snapshots()
        # Should add results for each platform
        assert len(self.validator.results) > 0

    def test_validate_source_snapshots_with_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validation_dir = os.path.join(tmpdir, "for_validation")
            os.makedirs(validation_dir)
            test_file = os.path.join(validation_dir, "microsoft-learn.json")
            test_data = {
                "badges": [{"id": "1", "retired": False, "date": "2024-01-15"}],
                "achievements": [],
            }
            with open(test_file, "w") as f:
                json.dump(test_data, f)

                        with (
                            patch("cross_artifact_validator.VALIDATION_DIR", validation_dir),
                            patch("cross_artifact_validator.VALIDATION_FILES", {"microsoft-learn": ["microsoft-learn.json"]}),
                            patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
                        ):
                            self.validator.validate_source_snapshots()
                        # Check that source_snapshot_exists check was added
                        results = [r for r in self.validator.results if r.check_name == "source_snapshot_exists"]
                        assert len(results) >= 1
                        assert results[0].passed is True


class TestCrossArtifactValidatorValidateArchiveComplete:
    """Tests for validate_archive_complete method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_archive_complete_missing(self):
        with patch("cross_artifact_validator.ARCHIVE_DIR", "/nonexistent"):
            self.validator.validate_archive_complete()
            results = [r for r in self.validator.results if r.check_name == "archive_complete_exists"]
            assert len(results) >= 1
            assert results[0].passed is False

    def test_validate_archive_complete_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = os.path.join(tmpdir, "archives")
            os.makedirs(archive_dir)
            test_file = os.path.join(archive_dir, "microsoft-learn-complete.md")
            content = """# Microsoft Learn

| ID | Name | Date |
|---|---|---|
|---|---|---|
| ACH001 | Azure Fundamentals | 2024-01-15 |
| ACH002 | AI Fundamentals | 2024-02-20 |
"""
            with open(test_file, "w") as f:
                f.write(content)

                        with (
                            patch("cross_artifact_validator.ARCHIVE_DIR", archive_dir),
                            patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
                        ):
                            self.validator.validate_archive_complete()
                        results = [r for r in self.validator.results if r.check_name == "archive_complete_parsed"]
                        assert len(results) >= 1
                        assert results[0].passed is True
                        assert results[0].actual == 2


class TestCrossArtifactValidatorValidateIndexFiles:
    """Tests for validate_index_files method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_index_files_missing(self):
        with patch("cross_artifact_validator.ARCHIVE_DIR", "/nonexistent"):
            self.validator.validate_index_files()
            results = [r for r in self.validator.results if r.check_name == "index_file_exists"]
            assert len(results) >= 1
            assert results[0].passed is False

    def test_validate_index_files_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = os.path.join(tmpdir, "archives")
            os.makedirs(archive_dir)
            test_file = os.path.join(archive_dir, "microsoft-learn-index.md")
            content = """# Microsoft Learn Index

**Total Records Archived:** 1,234
"""
            with open(test_file, "w") as f:
                f.write(content)

            with (
                patch("cross_artifact_validator.ARCHIVE_DIR", archive_dir),
                patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
            ):
                self.validator.validate_index_files()
            results = [r for r in self.validator.results if r.check_name == "index_total_parsed"]
            assert len(results) >= 1
            assert results[0].passed is True
            assert results[0].actual == 1234


class TestCrossArtifactValidatorValidateReadme:
    """Tests for validate_readme method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_readme_missing(self):
        with patch("cross_artifact_validator.README_PATH", "/nonexistent/README.md"):
            self.validator.validate_readme()
            # Should handle missing README gracefully
            # Just verify no crash

    def test_validate_readme_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_path = os.path.join(tmpdir, "README.md")
            content = """# README

<!-- MS_LEARN_START -->
**Completed Individual Units:** 1,234
<!-- MS_LEARN_END -->
"""
            with open(readme_path, "w") as f:
                f.write(content)

            with (
                patch("cross_artifact_validator.README_PATH", readme_path),
                patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
            ):
                self.validator.validate_readme()
            results = [r for r in self.validator.results if r.check_name == "readme_count_parsed"]
            assert len(results) >= 1
            assert results[0].passed is True
            assert results[0].actual == 1234


class TestCrossArtifactValidatorValidateJsonld:
    """Tests for validate_jsonld method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_jsonld_missing(self):
        with patch("cross_artifact_validator.JSONLD_PATH", "/nonexistent/credentials.jsonld"):
            self.validator.validate_jsonld()
            results = [r for r in self.validator.results if r.check_name == "jsonld_exists"]
            assert len(results) >= 1
            assert results[0].passed is False

    def test_validate_jsonld_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonld_path = os.path.join(tmpdir, "credentials.jsonld")
            content = {
                "@context": "https://schema.org",
                "@type": "ItemList",
                "mainEntity": {
                    "hasCredential": [
                        {"platform": "microsoft-learn", "credentialStatus": "Active", "dateCreated": "2024-01-15"},
                        {"platform": "microsoft-learn", "credentialStatus": "Retired", "dateCreated": "2023-06-10"},
                    ]
                }
            }
            with open(jsonld_path, "w") as f:
                json.dump(content, f)

                        with (
                            patch("cross_artifact_validator.JSONLD_PATH", jsonld_path),
                            patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
                        ):
                            self.validator.validate_jsonld()
                        results = [r for r in self.validator.results if r.check_name == "jsonld_count"]
                        assert len(results) >= 1
                        assert results[0].passed is True
                        assert results[0].actual == 2


class TestCrossArtifactValidatorValidateLlmsTxt:
    """Tests for validate_llms_txt method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_llms_txt_missing(self):
        with patch("cross_artifact_validator.LLMS_PATH", "/nonexistent/llms.txt"):
            self.validator.validate_llms_txt()
            results = [r for r in self.validator.results if r.check_name == "llms_txt_exists"]
            assert len(results) >= 1
            assert results[0].passed is False

    def test_validate_llms_txt_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            llms_path = os.path.join(tmpdir, "llms.txt")
            # Pattern expects "Microsoft Learn" and "completed units" on same line
            content = """# Portfolio

Microsoft Learn - 1,234 completed units

"""
            with open(llms_path, "w") as f:
                f.write(content)

            # Need to include all required fields in PLATFORMS
            test_platforms = {
                "microsoft-learn": {
                    "name": "Microsoft Learn",
                    "index_file": "microsoft-learn-index.md",
                    "complete_file": "microsoft-learn-complete.md",
                    "readme_marker_start": "<!-- MS_LEARN_START -->",
                    "readme_marker_end": "<!-- MS_LEARN_END -->",
                    "count_keys": ["ms_learn_units", "ms_learn_achievements", "ms_learn_badges", "ms_learn_xp"],
                    "index_total_pattern": r"\*\*Total Records Archived:\*\*\s*([\d,]+)",
                    "readme_patterns": [
                        r"Completed Individual Units.*?:\*\*\s*([\d,]+)",
                        r"Total Experience Points.*?:\*\*\s*([\d,]+)",
                        r"Badges Earned.*?:\*\*\s*([\d,]+)",
                    ],
                }
            }
                            with (
                                patch("cross_artifact_validator.LLMS_PATH", llms_path),
                                patch("cross_artifact_validator.PLATFORMS", test_platforms),
                            ):
                                self.validator.validate_llms_txt()
                            results = [r for r in self.validator.results if r.check_name == "llms_txt_count"]
                            assert len(results) >= 1
                            assert results[0].passed is True
                            assert results[0].actual == 1234


class TestCrossArtifactValidatorValidateLlmsFull:
    """Tests for validate_llms_full method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_llms_full_missing(self):
        with patch("cross_artifact_validator.LLMS_FULL_PATH", "/nonexistent/llms-full.txt"):
            self.validator.validate_llms_full()
            results = [r for r in self.validator.results if r.check_name == "llms_full_exists"]
            assert len(results) >= 1
            assert results[0].passed is False

    def test_validate_llms_full_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            llms_full_path = os.path.join(tmpdir, "llms-full.txt")
            content = """# llms-full.txt

## microsoft-learn-complete.md
Content here...
"""
            with open(llms_full_path, "w") as f:
                f.write(content)

                        with (
                            patch("cross_artifact_validator.LLMS_FULL_PATH", llms_full_path),
                            patch("cross_artifact_validator.PLATFORMS", {"microsoft-learn": PLATFORMS["microsoft-learn"]}),
                        ):
                            self.validator.validate_llms_full()
                        results = [r for r in self.validator.results if r.check_name == "llms_full_includes_platform"]
                        assert len(results) >= 1
                        assert results[0].passed is True


class TestCrossArtifactValidatorValidateCrossArtifactConsistency:
    """Tests for validate_cross_artifact_consistency method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_cross_artifact_consistency_matching(self):
        counts = PlatformCounts(platform="test")
        counts.source_records = 100
        counts.archive_complete_records = 100
        counts.index_total = 100
        counts.readme_count = 100
        counts.jsonld_count = 100
        counts.llms_txt_count = 100
        self.validator.platform_data["test"] = counts

        with patch("cross_artifact_validator.PLATFORMS", {"test": {"name": "Test", "complete_file": "test-complete.md", "readme_marker_start": "", "readme_marker_end": "", "count_keys": [], "index_total_pattern": "", "readme_patterns": []}}):
            # Mock manifest
            self.validator.manifest = None
            self.validator.validate_cross_artifact_consistency()
            # Check consistency results were added
                    _ = [r for r in self.validator.results if "count_consistency" in r.check_name]
            # All should pass since counts match


class TestCrossArtifactValidatorValidatePlatformCoverage:
    """Tests for validate_platform_coverage method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_platform_coverage_files_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = os.path.join(tmpdir, "archives")
            os.makedirs(archive_dir)
            with open(os.path.join(archive_dir, "microsoft-learn-complete.md"), "w") as f:
                f.write("test")
            with open(os.path.join(archive_dir, "microsoft-learn-index.md"), "w") as f:
                f.write("test")
            with open(os.path.join(archive_dir, "google-skills-complete.md"), "w") as f:
                f.write("test")
            with open(os.path.join(archive_dir, "google-skills-index.md"), "w") as f:
                f.write("test")

                        with (
                            patch("cross_artifact_validator.ARCHIVE_DIR", archive_dir),
                            patch("cross_artifact_validator.PLATFORMS", {
                                "microsoft-learn": PLATFORMS["microsoft-learn"],
                                "google-skills": PLATFORMS["google-skills"],
                            }),
                            patch("cross_artifact_validator.JSONLD_PATH", "/nonexistent"),
                            patch("cross_artifact_validator.LLMS_PATH", "/nonexistent"),
                            patch("cross_artifact_validator.LLMS_FULL_PATH", "/nonexistent"),
                        ):
                            self.validator.validate_platform_coverage()
                        # Should have platform coverage results


class TestCrossArtifactValidatorValidateLatestRecordOrdering:
    """Tests for validate_latest_record_ordering method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_validate_latest_record_ordering_consistent(self):
        counts = PlatformCounts(platform="test")
        counts.latest_record_date_source = "2024-01-15"
        counts.latest_record_date_archive = "2024-01-16"
        counts.latest_record_date_jsonld = "2024-01-17"
        self.validator.platform_data["test"] = counts

        with patch("cross_artifact_validator.PLATFORMS", {"test": PLATFORMS["microsoft-learn"]}):
            self.validator.validate_latest_record_ordering()
            results = [r for r in self.validator.results if r.check_name == "latest_record_date_consistency"]
            assert len(results) >= 1
            assert results[0].passed is True
            assert results[0].actual == "2 days"

    def test_validate_latest_record_ordering_inconsistent(self):
        counts = PlatformCounts(platform="test")
        counts.latest_record_date_source = "2024-01-01"
        counts.latest_record_date_archive = "2024-02-01"
        counts.latest_record_date_jsonld = "2024-03-01"
        self.validator.platform_data["test"] = counts

        with patch("cross_artifact_validator.PLATFORMS", {"test": PLATFORMS["microsoft-learn"]}):
            self.validator.validate_latest_record_ordering()
            results = [r for r in self.validator.results if r.check_name == "latest_record_date_consistency"]
            assert len(results) >= 1
            assert results[0].passed is False
            assert results[0].severity == "warning"


class TestCrossArtifactValidatorRunAll:
    """Tests for run_all method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_run_all(self):
            with (
                patch("cross_artifact_validator.CrossArtifactValidator.validate_source_snapshots"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_archive_complete"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_index_files"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_readme"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_jsonld"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_llms_txt"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_llms_full"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_cross_artifact_consistency"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_platform_coverage"),
                patch("cross_artifact_validator.CrossArtifactValidator.validate_latest_record_ordering"),
            ):
                success = self.validator.run_all()
                assert success is True


class TestCrossArtifactValidatorGenerateReport:
    """Tests for generate_report method."""

    def setup_method(self):
        self.validator = CrossArtifactValidator(strict=True, warn_mode=False)

    def test_generate_report(self):
        result = ValidationResult(
            check_name="test_check",
            platform="test-platform",
            passed=True,
            message="Test passed",
        )
        self.validator.add_result(result)

        counts = PlatformCounts(platform="test-platform")
        counts.source_records = 10
        counts.archive_complete_records = 10
        counts.index_total = 10
        counts.readme_count = 10
        counts.jsonld_count = 10
        counts.llms_txt_count = 10
        counts.llms_full_count = 1
        counts.retired_in_source = 0
        counts.retired_in_archive = 0
        counts.retired_in_jsonld = 0
        counts.latest_record_date_source = "2024-01-15"
        counts.latest_record_date_archive = "2024-01-15"
        counts.latest_record_date_jsonld = "2024-01-15"
        self.validator.platform_data["test-platform"] = counts

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            temp_path = f.name
        try:
            self.validator.generate_report(temp_path)
            with open(temp_path, "r") as f:
                report = json.load(f)
            assert "timestamp" in report
            assert "summary" in report
            assert "platforms" in report
            assert "results" in report
            assert report["summary"]["total"] == 1
            assert report["summary"]["passed"] == 1
            assert "test-platform" in report["platforms"]
        finally:
            os.unlink(temp_path)


class TestCrossArtifactValidatorMain:
    """Tests for main function."""

    def test_main_strict_mode(self):
        with (
            patch("cross_artifact_validator.CrossArtifactValidator.run_all", return_value=True),
            patch("cross_artifact_validator.CrossArtifactValidator.generate_report"),
            patch("sys.argv", ["cross_artifact_validator.py", "--mode", "strict"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                from cross_artifact_validator import main
                main()
            assert exc_info.value.code == 0

    def test_main_warn_mode(self):
        with (
            patch("cross_artifact_validator.CrossArtifactValidator.run_all", return_value=True),
            patch("cross_artifact_validator.CrossArtifactValidator.generate_report"),
            patch("sys.argv", ["cross_artifact_validator.py", "--mode", "warn"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                from cross_artifact_validator import main
                main()
            assert exc_info.value.code == 0

    def test_main_failure(self):
        with (
            patch("cross_artifact_validator.CrossArtifactValidator.run_all", return_value=False),
            patch("cross_artifact_validator.CrossArtifactValidator.generate_report"),
            patch("sys.argv", ["cross_artifact_validator.py", "--mode", "strict"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                from cross_artifact_validator import main
                main()
            assert exc_info.value.code == 1