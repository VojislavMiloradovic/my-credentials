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
        monolith.write_text(
            """# Complete Test Platform Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 [WARN] *Content retired* | Test Issuer | Badge |
""",
            encoding="utf-8",
        )

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
                "@context": "https://schema.org",
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
    """Tests for main JSON-LD and compact feed generation."""

    def test_main_generates_jsonld(self, temp_dir, mock_loss_guard):
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
            patch("generate_jsonld.VALIDATION_DIR", str(temp_dir / "missing_l1")),
            patch("generate_jsonld.README_PATH", str(readme)),
            patch("generate_jsonld.JSONLD_PATH", str(temp_dir / "credentials.jsonld")),
            patch(
                "generate_jsonld.FEED_JSON_PATH",
                str(temp_dir / "credentials.feed.json"),
            ),
            patch(
                "generate_jsonld.FEED_NDJSON_PATH", str(temp_dir / "credentials.ndjson")
            ),
        ):
            main()

            output = temp_dir / "credentials.jsonld"
            assert output.exists()
            data = json.loads(output.read_text(encoding="utf-8"))
            assert data["@context"] == "https://schema.org"
            assert data["@type"] == "ProfilePage"
            assert len(data["mainEntity"]["hasCredential"]) == 1
            assert (temp_dir / "credentials.feed.json").exists()
            assert (temp_dir / "credentials.ndjson").exists()

    def test_main_prefers_l1_normalized_and_emits_compact_feeds(
        self, temp_dir, mock_loss_guard
    ):
        val_dir = temp_dir / "for_validation"
        val_dir.mkdir()
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        # Put sentinel archive that should NOT be used when L1 exists
        (archives_dir / "sentinel-complete.md").write_text(
            "| Date Earned | Credential Name | Issuer | Verification Type |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| 2020-01-01 | Sentinel From Markdown | Markdown | Badge |\n",
            encoding="utf-8",
        )

        # Populate L1 records for credly & aws-skills & microsoft-learn
        (val_dir / "credly_badges.json").write_text(
            json.dumps(
                {
                    "platform": "credly",
                    "retrieved_at": "2026-11-01T10:00:00+00:00",
                    "credentials": [
                        {
                            "id": "credly-abc-123",
                            "title": "AWS Certified DevOps Engineer",
                            "issuer_name": "Amazon Web Services",
                            "type": "Certification",
                            "date": "2026-10-31T02:40:58+00:00",
                            "verify_url": "https://www.credly.com/badges/credly-abc-123/public_url",
                            "image_url": "https://images.credly.com/badge.png",
                            "skills": ["AWS", "DevOps"],
                            "retrieval_method": "api",
                            "retrieved_at": "2026-11-01T09:59:00+00:00",
                            "retired": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (val_dir / "aws_skill_badges.json").write_text(
            json.dumps(
                {
                    "platform": "aws-skills",
                    "retrieved_at": "2026-11-01T10:05:00+00:00",
                    "badges": [
                        {
                            "id": "aws-ret-1",
                            "title": "Legacy AWS Course",
                            "issuer_name": "Amazon Web Services",
                            "type": "Course",
                            "date": "2024-05-01",
                            "verify_url": "https://skillbuilder.aws/learn/course/1",
                            "retired": True,
                            "retirement_source": "source_csv",
                            "retirement_reason": "Status=Retired",
                            "retired_at": "2026-09-06",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (val_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "platform": "microsoft-learn",
                    "achievements": [
                        {
                            "uid": "ms-mod-1",
                            "id": "ms-mod-1",
                            "title": "Implement Azure Storage",
                            "category": "module",
                            "grantedOn": "2026-10-15T12:00:00+00:00",
                            "url": "/training/modules/implement-azure-storage/",
                            "retired": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        active_verifications = temp_dir / "active_verifications.json"
        active_verifications.write_text(
            json.dumps(
                {
                    "https://www.credly.com/badges/credly-abc-123/public_url": {
                        "alive": True,
                        "last_verified_at": "2024-06-14T12:00:00+00:00",
                        "http_status": 200,
                        "method": "HEAD",
                    }
                }
            ),
            encoding="utf-8",
        )

        readme = temp_dir / "README.md"
        readme.write_text("Test README", encoding="utf-8")

        jsonld_path = temp_dir / "credentials.jsonld"
        feed_json_path = temp_dir / "credentials.feed.json"
        feed_ndjson_path = temp_dir / "credentials.ndjson"

        with (
            patch("generate_jsonld.VALIDATION_DIR", str(val_dir)),
            patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)),
            patch("generate_jsonld.README_PATH", str(readme)),
            patch("generate_jsonld.JSONLD_PATH", str(jsonld_path)),
            patch("generate_jsonld.FEED_JSON_PATH", str(feed_json_path)),
            patch("generate_jsonld.FEED_NDJSON_PATH", str(feed_ndjson_path)),
            patch(
                "generate_jsonld.ACTIVE_VERIFICATIONS_PATH",
                str(active_verifications),
            ),
        ):
            main()

        payload = json.loads(jsonld_path.read_text(encoding="utf-8"))
        creds = payload["mainEntity"]["hasCredential"]
        assert len(creds) == 3
        names = {c["name"] for c in creds}
        assert "Sentinel From Markdown" not in names

        by_plat = {c["platform"]: c for c in creds}
        credly_item = by_plat["credly"]
        assert credly_item["sourceRecordId"] == "credly-abc-123"
        assert credly_item["sourceHash"]
        assert credly_item["dateCreated"] == "2026-10-31T02:40:58+00:00"
        assert credly_item["retrievedAt"] == "2026-11-01T09:59:00+00:00"
        assert credly_item["lastVerifiedAt"] == "2024-06-14T12:00:00+00:00"
        assert credly_item["verificationStatus"] == "verified"
        assert credly_item["skills"] == ["AWS", "DevOps"]
        assert credly_item["issuer"] == "Amazon Web Services"

        aws_item = by_plat["aws-skills"]
        assert aws_item["credentialStatus"] == "Retired"
        assert aws_item["retirement_source"] == "source_csv"
        assert aws_item["retirement_reason"] == "Status=Retired"
        assert aws_item["retired_at"] == "2026-09-06"
        assert aws_item["sourceHash"]

        ms_item = by_plat["microsoft-learn"]
        assert ms_item["url"].startswith(
            "https://learn.microsoft.com/en-us/training/modules/"
        )

        feed_data = json.loads(feed_json_path.read_text(encoding="utf-8"))
        assert feed_data["totalCount"] == 3
        assert feed_data["countsByPlatform"] == {
            "aws-skills": 1,
            "credly": 1,
            "microsoft-learn": 1,
        }
        assert len(feed_data["credentials"]) == 3
        assert all(
            c.get("sourceRecordId") and c.get("sourceHash")
            for c in feed_data["credentials"]
        )

        ndjson_lines = [
            json.loads(line)
            for line in feed_ndjson_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(ndjson_lines) == 3
        assert {item["sourceHash"] for item in ndjson_lines} == {
            c["sourceHash"] for c in creds
        }
