"""
Unit tests for validation_summary.py module.
"""

import json
import os
import sys
import tempfile

import pytest


class TestValidationSummary:
    """Tests for validation_summary module."""

    def test_validation_summary_imports(self):
        """Test that the module can be imported."""
        import validation_summary

        assert validation_summary is not None

    def test_main_with_valid_report(self):
        """Test main function with valid report file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create validation_reports directory
            reports_dir = os.path.join(tmpdir, "validation_reports")
            os.makedirs(reports_dir)

            # Create report file
            report_path = os.path.join(reports_dir, "cross_artifact_report.json")
            report_data = {
                "timestamp": "2024-01-15T10:00:00Z",
                "summary": {"total": 10, "passed": 8, "failed": 1, "warnings": 1},
                "results": [
                    {
                        "check": "source_snapshot_exists",
                        "platform": "microsoft-learn",
                        "passed": True,
                        "expected": "> 0",
                        "actual": 100,
                        "message": "Source snapshot has 100 records (0 retired)",
                        "severity": "error",
                    },
                    {
                        "check": "source_snapshot_exists",
                        "platform": "google-skills",
                        "passed": False,
                        "expected": "> 0",
                        "actual": 0,
                        "message": "Source snapshot has 0 records (0 retired)",
                        "severity": "error",
                    },
                    {
                        "check": "archive_complete_parsed",
                        "platform": "microsoft-learn",
                        "passed": False,
                        "expected": "> 0",
                        "actual": 0,
                        "message": "Complete archive has 0 records (0 retired)",
                        "severity": "warning",
                    },
                ],
            }
            with open(report_path, "w") as f:
                json.dump(report_data, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validation_summary import main

                # The main function just prints, doesn't return anything
                # It should run without error
                main()
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_main_with_missing_report(self):
        """Test main function with missing report file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validation_summary import main

                # Should handle missing file gracefully with sys.exit(1)
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_main_with_invalid_json(self):
        """Test main function with invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = os.path.join(tmpdir, "validation_reports")
            os.makedirs(reports_dir)

            report_path = os.path.join(reports_dir, "cross_artifact_report.json")
            with open(report_path, "w") as f:
                f.write("invalid json {")

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validation_summary import main

                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)


class TestValidationSummaryOutput:
    """Tests for validation_summary output format."""

    def test_output_format(self):
        """Test that the output format matches expectations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = os.path.join(tmpdir, "validation_reports")
            os.makedirs(reports_dir)

            report_path = os.path.join(reports_dir, "cross_artifact_report.json")
            report_data = {
                "timestamp": "2024-01-15T10:00:00Z",
                "summary": {"total": 2, "passed": 1, "failed": 1, "warnings": 0},
                "results": [
                    {
                        "check": "test_check_pass",
                        "platform": "test-platform",
                        "passed": True,
                        "expected": "10",
                        "actual": "10",
                        "message": "Test passed",
                        "severity": "error",
                    },
                    {
                        "check": "test_check_fail",
                        "platform": "test-platform",
                        "passed": False,
                        "expected": "10",
                        "actual": "5",
                        "message": "Test failed",
                        "severity": "error",
                    },
                ],
            }
            with open(report_path, "w") as f:
                json.dump(report_data, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                # Capture stdout
                import io
                from contextlib import redirect_stdout

                from validation_summary import main

                f = io.StringIO()
                with redirect_stdout(f):
                    main()
                output = f.getvalue()

                assert "Timestamp: 2024-01-15T10:00:00Z" in output
                assert "Total checks: 2" in output
                assert "Passed: 1" in output
                assert "Failed (errors): 1" in output
                assert "Warnings: 0" in output
                assert "Failed checks:" in output
                assert "[FAIL] [test-platform] test_check_fail" in output
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_output_with_warnings(self):
        """Test output format with warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = os.path.join(tmpdir, "validation_reports")
            os.makedirs(reports_dir)

            report_path = os.path.join(reports_dir, "cross_artifact_report.json")
            report_data = {
                "timestamp": "2024-01-15T10:00:00Z",
                "summary": {"total": 2, "passed": 1, "failed": 0, "warnings": 1},
                "results": [
                    {
                        "check": "test_check_pass",
                        "platform": "test-platform",
                        "passed": True,
                        "expected": "10",
                        "actual": "10",
                        "message": "Test passed",
                        "severity": "error",
                    },
                    {
                        "check": "test_check_warn",
                        "platform": "test-platform",
                        "passed": False,
                        "expected": "10",
                        "actual": "5",
                        "message": "Test warning",
                        "severity": "warning",
                    },
                ],
            }
            with open(report_path, "w") as f:
                json.dump(report_data, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                import io
                from contextlib import redirect_stdout

                from validation_summary import main

                f = io.StringIO()
                with redirect_stdout(f):
                    main()
                output = f.getvalue()

                assert "Warnings:" in output
                assert "[WARN] [test-platform] test_check_warn" in output
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_output_with_no_platform(self):
        """Test output format with global checks (no platform)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = os.path.join(tmpdir, "validation_reports")
            os.makedirs(reports_dir)

            report_path = os.path.join(reports_dir, "cross_artifact_report.json")
            report_data = {
                "timestamp": "2024-01-15T10:00:00Z",
                "summary": {"total": 1, "passed": 0, "failed": 1, "warnings": 0},
                "results": [
                    {
                        "check": "test_check_fail",
                        "platform": None,
                        "passed": False,
                        "expected": "10",
                        "actual": "5",
                        "message": "Global check failed",
                        "severity": "error",
                    }
                ],
            }
            with open(report_path, "w") as f:
                json.dump(report_data, f)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                import io
                from contextlib import redirect_stdout

                from validation_summary import main

                f = io.StringIO()
                with redirect_stdout(f):
                    main()
                output = f.getvalue()

                assert "[FAIL] [global] test_check_fail" in output
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)
