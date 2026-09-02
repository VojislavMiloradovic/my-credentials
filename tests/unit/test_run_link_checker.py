"""
Tests for run_link_checker.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import run_link_checker


def test_load_results_file_not_found(monkeypatch):
    """Test load_results when file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch the RESULTS_FILE to point to a non-existent file in tempdir
        monkeypatch.setattr(
            run_link_checker,
            "RESULTS_FILE",
            str(Path(tmpdir) / "link_check_results" / "latest.json"),
        )
        os.environ["GITHUB_STEP_SUMMARY"] = str(Path(tmpdir) / "step_summary")
        result = run_link_checker.load_results()
        assert "error" in result
        assert "not found" in result["error"]


def test_load_results_invalid_json(monkeypatch):
    """Test load_results with invalid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results_file = Path(tmpdir) / "link_check_results" / "latest.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)
        results_file.write_text("invalid json")

        monkeypatch.setattr(run_link_checker, "RESULTS_FILE", str(results_file))
        os.environ["GITHUB_STEP_SUMMARY"] = str(Path(tmpdir) / "step_summary")
        result = run_link_checker.load_results()
        assert "error" in result
        assert "JSON parse error" in result["error"]


def test_load_results_valid_json(monkeypatch):
    """Test load_results with valid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results_file = Path(tmpdir) / "link_check_results" / "latest.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)
        test_data = {"total": 100, "successful": 95, "errors": 5}
        with open(results_file, "w") as f:
            json.dump(test_data, f)

        monkeypatch.setattr(run_link_checker, "RESULTS_FILE", str(results_file))
        os.environ["GITHUB_STEP_SUMMARY"] = str(Path(tmpdir) / "step_summary")
        result = run_link_checker.load_results()
        assert result == test_data


def test_extract_detailed_results_empty():
    """Test extract_detailed_results with empty data."""
    data = {}
    result = run_link_checker.extract_detailed_results(data)
    assert result == {
        "failed": [],
        "redirected": [],
        "excluded": [],
        "timeouts": [],
    }


def test_extract_detailed_results_fail_map():
    """Test extract_detailed_results with fail_map."""
    result = run_link_checker.extract_detailed_results(
        {
            "fail_map": {
                "https://example.com/broken": {
                    "status": 404,
                    "status_text": "Not Found",
                    "error": "Not Found",
                    "file": "README.md",
                    "line": 10,
                }
            }
        }
    )
    assert len(result["failed"]) == 1
    assert result["failed"][0]["url"] == "https://example.com/broken"
    assert result["failed"][0]["status"] == 404
    assert result["failed"][0]["file"] == "README.md"
    assert result["failed"][0]["line"] == 10


def test_extract_detailed_results_suggestion_map():
    """Test extract_detailed_results with suggestion_map (redirects)."""
    result = run_link_checker.extract_detailed_results(
        {
            "suggestion_map": {
                "https://example.com/old": {
                    "status": 301,
                    "status_text": "Moved Permanently",
                    "suggestion": "https://example.com/new",
                    "file": "README.md",
                    "line": 20,
                }
            }
        }
    )
    assert len(result["redirected"]) == 1
    assert result["redirected"][0]["url"] == "https://example.com/old"
    assert result["redirected"][0]["redirect_url"] == "https://example.com/new"
    assert result["redirected"][0]["status"] == 301


def test_extract_detailed_results_excluded_map():
    """Test extract_detailed_results with excluded_map."""
    result = run_link_checker.extract_detailed_results(
        {
            "excluded_map": {
                "https://example.com/excluded": {
                    "pattern": "example.com/excluded",
                    "file": "README.md",
                    "line": 30,
                }
            }
        }
    )
    assert len(result["excluded"]) == 1
    assert result["excluded"][0]["url"] == "https://example.com/excluded"
    assert result["excluded"][0]["pattern"] == "example.com/excluded"


def test_generate_summary_no_data():
    """Test generate_summary with error data."""
    summary = run_link_checker.generate_summary({"error": "Test error"})
    assert "Link Checker Error" in summary
    assert "Test error" in summary


def test_generate_summary_basic():
    """Test generate_summary with basic data."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 5,
        "redirects": 2,
        "excludes": 3,
        "timeouts": 0,
        "unknown": 0,
        "unsupported": 0,
        "unique": 100,
        "success_map": {},
        "fail_map": {},
        "suggestion_map": {},
        "excluded_map": {},
    }
    summary = run_link_checker.generate_summary(data)
    assert "Link Checker Summary" in summary
    assert "Total" in summary
    assert "Successful" in summary
    assert "Errors" in summary


def test_generate_summary_with_failures():
    """Test generate_summary with failures."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 5,
        "redirects": 2,
        "excludes": 3,
        "timeouts": 0,
        "unknown": 0,
        "unsupported": 0,
        "unique": 100,
        "fail_map": {
            "https://example.com/broken": {
                "status": 404,
                "status_text": "Not Found",
                "error": "Not Found",
                "file": "README.md",
                "line": 10,
            }
        },
        "suggestion_map": {},
        "excluded_map": {},
    }
    summary = run_link_checker.generate_summary(data)
    assert "Errors" in summary
    assert "https://example.com/broken" in summary
    assert "404" in summary


def test_generate_summary_with_redirects():
    """Test generate_summary with redirects."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 0,
        "redirects": 2,
        "excludes": 0,
        "timeouts": 0,
        "unknown": 0,
        "unsupported": 0,
        "unique": 100,
        "suggestion_map": {
            "https://example.com/old": {
                "status": 301,
                "status_text": "Moved Permanently",
                "suggestion": "https://example.com/new",
                "file": "README.md",
                "line": 10,
            }
        },
        "fail_map": {},
        "excluded_map": {},
    }
    summary = run_link_checker.generate_summary(data)
    assert "Redirected" in summary
    assert "https://example.com/old" in summary
    assert "https://example.com/new" in summary


def test_extract_detailed_results_with_string_values():
    """Test extract_detailed_results handles string values in maps."""
    result = run_link_checker.extract_detailed_results(
        {"fail_map": {"https://example.com/broken": "Simple error string"}}
    )
    assert len(result["failed"]) == 1
    assert result["failed"][0]["url"] == "https://example.com/broken"
    assert result["failed"][0]["error"] == "Simple error string"


def test_extract_detailed_results_excluded_with_string():
    """Test extract_detailed_results handles string in excluded_map."""
    result = run_link_checker.extract_detailed_results(
        {"excluded_map": {"https://example.com/excluded": "simple pattern"}}
    )
    assert len(result["excluded"]) == 1
    assert result["excluded"][0]["url"] == "https://example.com/excluded"
    assert result["excluded"][0]["pattern"] == "simple pattern"


def test_generate_summary_with_timeouts():
    """Test generate_summary with timeouts."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 0,
        "redirects": 0,
        "excludes": 0,
        "timeouts": 3,
        "unknown": 0,
        "unsupported": 0,
        "unique": 100,
        "fail_map": {},
        "suggestion_map": {},
        "excluded_map": {},
    }
    summary = run_link_checker.generate_summary(data)
    assert "Timeouts" in summary
    assert "3" in summary


def test_generate_summary_with_excludes():
    """Test generate_summary with excluded links."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 0,
        "redirects": 0,
        "excludes": 3,
        "timeouts": 0,
        "unknown": 0,
        "unsupported": 0,
        "unique": 100,
        "excluded_map": {
            "https://example.com/excluded1": {
                "pattern": "example.com/exclude",
                "file": "README.md",
                "line": 10,
            },
            "https://example.com/excluded2": {
                "pattern": "example.com/exclude",
                "file": "README.md",
                "line": 20,
            },
            "https://example.com/excluded3": {
                "pattern": "other.com/exclude",
                "file": "README.md",
                "line": 30,
            },
        },
        "fail_map": {},
        "suggestion_map": {},
    }
    summary = run_link_checker.generate_summary(data)
    assert "Excluded" in summary
    assert "example.com/exclude" in summary
    assert "other.com/exclude" in summary


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
