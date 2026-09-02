"""
Additional tests for run_link_checker.py to improve coverage.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import run_link_checker


def test_truncate_summary_short():
    """Test truncate_summary with short summary (no truncation needed)."""
    short = "short summary"
    result = run_link_checker.truncate_summary(short, max_bytes=1000000)
    assert result == short


def test_truncate_summary_long():
    """Test truncate_summary with long summary (truncation needed)."""
    long_summary = "x" * 2000000  # 2MB
    truncated = run_link_checker.truncate_summary(long_summary, max_bytes=1000)
    assert len(truncated.encode("utf-8")) <= 1000
    assert "truncated" in truncated.lower()
    assert "---" in truncated


def test_truncate_summary_exact_boundary():
    """Test truncate_summary at exact boundary."""
    # Create a summary that's exactly at the boundary
    summary = "x" * 1000000  # Exactly 1MB
    result = run_link_checker.truncate_summary(summary, max_bytes=1000000)
    assert result == "x" * 1000000  # Should not truncate

    # One byte over
    summary_over = "x" * 1000001
    truncated = run_link_checker.truncate_summary(summary_over, max_bytes=1000000)
    assert len(truncated.encode("utf-8")) <= 1000000
    assert "truncated" in truncated.lower()


def test_extract_detailed_results_with_empty_maps():
    """Test extract_detailed_results with empty maps."""
    data = {
        "fail_map": {},
        "suggestion_map": {},
        "excluded_map": {},
    }
    result = run_link_checker.extract_detailed_results(data)
    assert result == {
        "failed": [],
        "redirected": [],
        "excluded": [],
        "timeouts": [],
    }


def test_load_results_json_decode_error(monkeypatch):
    """Test load_results with JSON decode error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results_file = Path(tmpdir) / "link_check_results" / "latest.json"
        results_file.parent.mkdir(parents=True, exist_ok=True)
        results_file.write_text("{ invalid json }")

        import run_link_checker as rlc
        monkeypatch.setattr(rlc, "RESULTS_FILE", str(Path(tmpdir) / "link_check_results" / "latest.json"))
        result = rlc.load_results()
        assert "error" in result
        assert "JSON parse error" in result["error"]


def test_truncate_summary_unicode():
    """Test truncate_summary with unicode characters."""
    # Create a summary with unicode characters that might be cut in the middle
    unicode_text = "🚀 " * 500000  # ~2MB of emoji
    truncated = run_link_checker.truncate_summary(unicode_text, max_bytes=1000)
    assert len(truncated.encode("utf-8")) <= 1000
    assert "truncated" in truncated.lower()


def test_generate_summary_with_all_fields():
    """Test generate_summary with all possible fields populated."""
    data = {
        "total": 100,
        "successful": 95,
        "errors": 5,
        "redirects": 2,
        "excludes": 3,
        "timeouts": 1,
        "unknown": 2,
        "unsupported": 1,
        "unique": 100,
        "fail_map": {
            "https://example.com/broken1": {
                "status": 404,
                "status_text": "Not Found",
                "error": "Not Found",
                "file": "README.md",
                "line": 10,
            },
            "https://example.com/broken2": {
                "status": 500,
                "status_text": "Internal Server Error",
                "error": "Internal Server Error",
                "file": "docs.md",
                "line": 20,
            },
        },
        "suggestion_map": {
            "https://example.com/old": {
                "status": 301,
                "status_text": "Moved Permanently",
                "suggestion": "https://example.com/new",
                "file": "README.md",
                "line": 10,
            }
        },
        "excluded_map": {
            "https://example.com/excluded": {
                "pattern": "example.com/exclude",
                "file": "README.md",
                "line": 10,
            }
        },
        "timeouts": {
            "https://example.com/slow": {
                "status": "timeout",
                "error": "Connection timeout",
                "file": "README.md",
                "line": 30,
            }
        },
    }
    summary = run_link_checker.generate_summary(data)
    assert "Link Checker Summary" in summary
    assert "Total" in summary
    assert "Successful" in summary
    assert "Errors" in summary
    assert "Redirected" in summary
    assert "Excluded" in summary
    assert "Timeouts" in summary
    assert "Errors" in summary
    assert "https://example.com/broken1" in summary
    assert "https://example.com/new" in summary


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])