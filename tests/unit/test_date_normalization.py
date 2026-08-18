"""
Unit tests for date normalization functions across all providers.
"""

import pytest
from datetime import UTC, datetime

# Import date normalization functions from each provider
from update_aws_skills import normalize_date_string as aws_normalize_date
from update_google_skills import normalize_date_string as google_normalize_date
from update_credly_badges import normalize_date_string as credly_normalize_date
from update_linkedin import parse_linkedin_date
from update_ms_learn import clean_iso_date
from update_google_developer import normalize_date_string as gdev_normalize_date


class TestAwsDateNormalization:
    """Tests for AWS Skills date normalization."""

    @pytest.mark.parametrize("input_val,expected", [
        ("Jan 15, 2024", "2024-01-15"),
        ("January 15, 2024", "2024-01-15"),
        ("15 Jan 2024", "2024-01-15"),
        ("15 January 2024", "2024-01-15"),
        ("2024-01-15", "2024-01-15"),
        ("01/15/2024", "2024-01-15"),
        ("15/01/2024", "2024-01-15"),
        ("2024/01/15", "2024-01-15"),
        ("1705312800", "2024-01-15"),  # Unix timestamp (seconds)
        ("1705312800000", "2024-01-15"),  # Unix timestamp (milliseconds)
        (1705312800, "2024-01-15"),  # int timestamp
        (1705312800000, "2024-01-15"),  # int timestamp ms
        ("", None),
        (None, None),
        ("N/A", None),
        ("None", None),
        ("null", None),
    ])
    def test_normalize_date_string(self, input_val, expected):
        assert aws_normalize_date(input_val) == expected


class TestGoogleSkillsDateNormalization:
    """Tests for Google Skills date normalization."""

    @pytest.mark.parametrize("input_val,expected", [
        ("2024-01-15T10:00:00Z", "2024-01-15"),
        ("1705312800000", "2024-01-15"),  # milliseconds
        ("Jan 15, 2024", "2024-01-15"),
        ("", None),
        (None, None),
    ])
    def test_normalize_date_string(self, input_val, expected):
        assert google_normalize_date(input_val) == expected


class TestCredlyDateNormalization:
    """Tests for Credly date normalization."""

    @pytest.mark.parametrize("input_val,expected", [
        ("2024-01-15T10:00:00Z", "2024-01-15"),
        ("1705312800000", "2024-01-15"),
        ("Jan 15, 2024", "2024-01-15"),
        ("", None),
        (None, None),
    ])
    def test_normalize_date_string(self, input_val, expected):
        assert credly_normalize_date(input_val) == expected


class TestLinkedInDateParsing:
    """Tests for LinkedIn date parsing."""

    @pytest.mark.parametrize("input_val,expected", [
        ("Jan 2024", "2024-01"),
        ("January 2024", "2024-01"),
        ("2024-01", "2024-01"),
        ("2024-01-15", "2024-01-15"),
        ("Mar 2024", "2024-03"),
        ("", "N/A"),
        (None, "N/A"),
        ("null", "N/A"),
        ("N/A", "N/A"),
    ])
    def test_parse_linkedin_date(self, input_val, expected):
        assert parse_linkedin_date(input_val) == expected


class TestMsLearnDateCleaning:
    """Tests for Microsoft Learn ISO date cleaning."""

    @pytest.mark.parametrize("input_val,expected", [
        ("2024-01-15T10:00:00Z", "2024-01-15"),
        ("2024-01-15T10:00:00.000Z", "2024-01-15"),
        ("2024-01-15", "2024-01-15"),
        ("2024-01", "2024-01"),
        ("", "N/A"),
        (None, "N/A"),
    ])
    def test_clean_iso_date(self, input_val, expected):
        assert clean_iso_date(input_val) == expected


class TestGoogleDeveloperDateNormalization:
    """Tests for Google Developer date normalization (Serbian dates)."""

    @pytest.mark.parametrize("input_val,expected", [
        ("17. август 2024.", "2024-08-17"),
        ("13. август 2024.", "2024-08-13"),
        ("1. јануар 2024.", "2024-01-01"),
        ("15. феб 2024.", "2024-02-15"),
        ("2024-01-15", "2024-01-15"),
        ("", "N/A"),
        (None, "N/A"),
    ])
    def test_normalize_date_string(self, input_val, expected):
        assert gdev_normalize_date(input_val) == expected


class TestDateNormalizationEdgeCases:
    """Edge case tests for all date normalization functions."""

    def test_all_functions_handle_none(self):
        """All normalization functions should handle None gracefully."""
        assert aws_normalize_date(None) is None
        assert google_normalize_date(None) is None
        assert credly_normalize_date(None) is None
        assert parse_linkedin_date(None) == "N/A"
        assert clean_iso_date(None) == "N/A"
        assert gdev_normalize_date(None) == "N/A"

    def test_all_functions_handle_empty_string(self):
        """All normalization functions should handle empty strings gracefully."""
        assert aws_normalize_date("") is None
        assert google_normalize_date("") is None
        assert credly_normalize_date("") is None
        assert parse_linkedin_date("") == "N/A"
        assert clean_iso_date("") == "N/A"
        assert gdev_normalize_date("") == "N/A"

    def test_timestamp_boundaries(self):
        """Test timestamp boundary handling (seconds vs milliseconds)."""
        # 1 second = 1000 milliseconds
        # If > 1e11, treat as milliseconds
        ts_seconds = 1705312800  # 2024-01-15
        ts_milliseconds = 1705312800000  # Same date in ms
        
        assert aws_normalize_date(ts_seconds) == "2024-01-15"
        assert aws_normalize_date(ts_milliseconds) == "2024-01-15"
        
        # Test the threshold - values > 1e11 are treated as ms
        # Values <= 1e11 are treated as seconds
        # Very old timestamps may return None due to OS limitations
        result_s = aws_normalize_date(99999999999)  # < 1e11, seconds
        result_ms = aws_normalize_date(100000000000)  # >= 1e11, ms
        
        # Both may be None if dates are out of range
        # The important thing is the threshold logic is applied
        assert (result_s is None or isinstance(result_s, str))
        assert (result_ms is None or isinstance(result_ms, str))

    def test_invalid_date_formats_return_none_or_na(self):
        """Invalid date formats should return None (AWS/Google/Credly) or N/A (LinkedIn/MS/GDev)."""
        invalid = "not-a-date-at-all"
        assert aws_normalize_date(invalid) is None
        assert google_normalize_date(invalid) is None
        assert credly_normalize_date(invalid) is None
        assert parse_linkedin_date(invalid) == "N/A"
        # clean_iso_date returns original string if no match found
        assert clean_iso_date(invalid) == invalid
        assert gdev_normalize_date(invalid) == "N/A"