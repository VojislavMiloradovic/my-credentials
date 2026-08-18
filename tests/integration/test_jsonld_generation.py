"""
Integration tests for JSON-LD generation (generate_jsonld.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from generate_jsonld import (
    MARKER_END,
    MARKER_START,
    clean_str,
    cleanup_readme,
    extract_table_data_rows,
    main,
    parse_archive_monoliths,
    validate_jsonld,
)


class TestJsonLdHelpers:
    """Tests for JSON-LD helper functions."""

    def test_clean_str(self):
        assert clean_str("**Bold**") == "Bold"
        assert clean_str("_Italic_") == "Italic"
        assert clean_str("`Code`") == "Code"
        assert clean_str("Normal") == "Normal"
        assert clean_str("") == ""
        assert clean_str(None) == ""

    def test_extract_table_data_rows(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| :--- | :--- |",
            "| Cell 1 | Cell 2 |",
            "| Cell 3 | Cell 4 |",
            "Not a table",
        ]
        rows = extract_table_data_rows(lines)
        assert len(rows) == 2
        assert rows[0][0] == ["header 1", "header 2"]
        assert rows[0][1] == ["Cell 1", "Cell 2"]
        assert rows[1][1] == ["Cell 3", "Cell 4"]

    def test_extract_table_data_rows_empty(self):
        rows = extract_table_data_rows([])
        assert rows == []

    def test_extract_table_data_rows_no_separator(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| Cell 1 | Cell 2 |",
        ]
        rows = extract_table_data_rows(lines)
        assert rows == []


class TestJsonLdParsing:
    """Tests for archive monolith parsing."""

    def test_parse_archive_monoliths_basic(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        monolith = archives_dir / "test-platform-complete.md"
        monolith.write_text("""# Complete Test Platform Archive

This document represents a unified list of 2 records.

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | [Badge 1](https://example.com/1) | Test Issuer | Badge |
| 2024-01-10 | Badge 2 | Test Issuer | Badge |
""")

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            credentials = parse_archive_monoliths()
            assert len(credentials) == 2
            assert credentials[0]["name"] == "Badge 1"
            assert credentials[0]["url"] == "https://example.com/1"
            assert credentials[1]["name"] == "Badge 2"
            assert "url" not in credentials[1] or credentials[1].get("url") is None

    def test_parse_archive_monoliths_with_images(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        monolith = archives_dir / "test-platform-complete.md"
        monolith.write_text("""# Complete Test Platform Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | ![Image](https://img.com/1) [Badge 1](https://example.com/1) | Test Issuer | Badge |
""")

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            credentials = parse_archive_monoliths()
            assert len(credentials) == 1
            assert credentials[0]["image"] == "https://img.com/1"

    def test_parse_archive_monoliths_with_credential_id(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        monolith = archives_dir / "test-platform-complete.md"
        monolith.write_text("""# Complete Test Platform Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | **Badge 1** Credential ID: `ABC123` | Test Issuer | Badge |
""")

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            credentials = parse_archive_monoliths()
            assert len(credentials) == 1
            assert credentials[0]["identifier"] == "ABC123"

    def test_parse_archive_monoliths_retired(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        monolith = archives_dir / "test-platform-complete.md"
        monolith.write_text("""# Complete Test Platform Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 ⚠️ *Content retired* | Test Issuer | Badge |
""", encoding="utf-8")

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            credentials = parse_archive_monoliths()
            assert len(credentials) == 1
            assert credentials[0]["credentialStatus"] == "Retired"

    def test_parse_archive_monoliths_no_archive_dir(self, temp_dir):
        with patch("generate_jsonld.ARCHIVE_DIR", str(temp_dir / "nonexistent")):
            credentials = parse_archive_monoliths()
            assert credentials == []


class TestJsonLdValidation:
    """Tests for JSON-LD schema validation."""

    def test_validate_jsonld_valid(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "ProfilePage",
            "mainEntity": {
                "@type": "Person",
                "name": "Test",
                "url": "https://example.com",
                "hasCredential": [
                    {
                        "@type": "EducationalOccupationalCredential",
                        "credentialCategory": "Badge",
                        "name": "Test Badge",
                        "recognizedBy": {
                            "@type": "Organization",
                            "name": "Test Issuer",
                        },
                    }
                ],
            },
        }
        # Should not raise
        validate_jsonld(payload)

    def test_validate_jsonld_invalid_missing_context(self):
        payload = {
            "@type": "ProfilePage",
            "mainEntity": {"@type": "Person", "name": "Test", "hasCredential": []},
        }
        with pytest.raises(SystemExit) as exc_info:
            validate_jsonld(payload)
        assert exc_info.value.code == 1


class TestJsonLdCleanup:
    """Tests for README cleanup."""

    def test_cleanup_readme_removes_markers(self, temp_dir):
        readme = temp_dir / "README.md"
        readme.write_text(
            f"Before\n{MARKER_START}\nScript content\n{MARKER_END}\nAfter"
        )

        with patch("generate_jsonld.README_PATH", str(readme)):
            cleanup_readme()

        content = readme.read_text()
        assert "Script content" not in content
        assert "Before" in content
        assert "After" in content

    def test_cleanup_readme_fixes_encoding(self, temp_dir):
        readme = temp_dir / "README.md"
        readme.write_text("Vojislav Miloradović", encoding="utf-8")  # Fixed encoding

        with patch("generate_jsonld.README_PATH", str(readme)):
            cleanup_readme()

        content = readme.read_text(encoding="utf-8")
        assert "Vojislav Miloradović" in content


class TestJsonLdMain:
    """Tests for main JSON-LD generation."""

    def test_main_generates_jsonld(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        monolith = archives_dir / "test-platform-complete.md"
        monolith.write_text("""# Complete Test Platform Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 | Test Issuer | Badge |
""")

        readme = temp_dir / "README.md"
        readme.write_text("Test README")

        with (
            patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)),
            patch("generate_jsonld.README_PATH", str(readme)),
            patch("generate_jsonld.JSONLD_PATH", str(temp_dir / "credentials.jsonld")),
        ):
            main()

            output = temp_dir / "credentials.jsonld"
            assert output.exists()
            data = json.loads(output.read_text())
            assert data["@context"] == "https://schema.org"
            assert data["@type"] == "ProfilePage"
            assert len(data["mainEntity"]["hasCredential"]) == 1
