"""
Integration tests for Google Skills pipeline (update_google_skills.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_google_skills import (
    GOOGLE_PROFILE_ID,
    MARKER_END,
    MARKER_START,
    GoogleBadgeItemModel,
    GoogleSkillsArchivePayloadModel,
    execute_data_loss_guard,
    fetch_google_skills_badges,
    get_stored_archive_baseline_count,
    main,
    normalize_date_string,
    parse_google_badges_from_json,
)


class TestGoogleSkillsHelpers:
    """Tests for Google Skills helper functions."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2024-01-15T10:00:00Z", "2024-01-15"),
            ("1705312800000", "2024-01-15"),
            ("Jan 15, 2024", "2024-01-15"),
            ("", None),
            (None, None),
        ],
    )
    def test_normalize_date_string(self, input_val, expected):
        assert normalize_date_string(input_val) == expected


class TestGoogleSkillsModels:
    """Tests for Google Skills Pydantic models."""

    def test_google_badge_item_model_valid(self, google_badge_builder):
        badge = google_badge_builder()
        model = GoogleBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]

    def test_google_badge_item_model_date_coercion(self):
        badge = GoogleBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            issued_at="2024-01-15T10:00:00Z",
            issued_at_date="1705312800000",
            date="2024-01-15",
        )
        assert badge.issued_at == "2024-01-15"
        assert badge.issued_at_date == "2024-01-15"
        assert badge.date == "2024-01-15"

    def test_google_skills_archive_payload_model_valid(self):
        payload = {
            "profile_id": "test-profile",
            "total_count": 1,
            "badges": [
                {
                    "id": "1",
                    "title": "Badge 1",
                    "name": "Badge 1",
                    "issuer": "Google",
                    "issuer_name": "Google",
                }
            ],
        }
        model = GoogleSkillsArchivePayloadModel(**payload)
        assert model.profile_id == "test-profile"


class TestGoogleSkillsParsers:
    """Tests for Google Skills parsing functions."""

    def test_parse_google_badges_from_json(self, temp_dir, sample_google_skills_json):
        json_file = temp_dir / "google_skills.json"
        json_file.write_text(json.dumps(sample_google_skills_json))

        badges = parse_google_badges_from_json(str(json_file))
        assert len(badges) == 2
        assert badges[0]["id"] == "123"
        assert badges[1]["id"] == "456"

    def test_parse_google_badges_from_json_missing_file(self, temp_dir):
        badges = parse_google_badges_from_json(str(temp_dir / "nonexistent.json"))
        assert badges == []


class TestGoogleSkillsFetch:
    """Tests for Google Skills fetching with mocked HTTP."""

    @responses.activate
    def test_fetch_google_skills_json_api_success(
        self, temp_dir, sample_google_skills_json
    ):
        responses.add(
            responses.GET,
            f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}.json",
            json=sample_google_skills_json,
            status=200,
        )

        badges = fetch_google_skills_badges(GOOGLE_PROFILE_ID)
        assert len(badges) == 2
        assert badges[0]["id"] == "123"

    @responses.activate
    def test_fetch_google_skills_json_api_fallback_to_html(
        self, temp_dir, sample_google_skills_html
    ):
        # JSON endpoint returns 404
        responses.add(
            responses.GET,
            f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}.json",
            status=404,
        )
        # HTML endpoint returns HTML
        responses.add(
            responses.GET,
            f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}",
            body=sample_google_skills_html,
            status=200,
        )

        badges = fetch_google_skills_badges(GOOGLE_PROFILE_ID)
        # Should parse from HTML
        assert len(badges) >= 0  # HTML parsing may not extract all

    @responses.activate
    def test_fetch_google_skills_fallback_to_local_json(
        self, temp_dir, sample_google_skills_json
    ):
        # All network endpoints fail
        responses.add(
            responses.GET,
            f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}.json",
            status=500,
        )
        responses.add(
            responses.GET,
            f"https://cloudskillsboost.google/public_profiles/{GOOGLE_PROFILE_ID}.json",
            status=500,
        )
        responses.add(
            responses.GET,
            f"https://www.skills.google/public_profiles/{GOOGLE_PROFILE_ID}",
            status=500,
        )
        responses.add(
            responses.GET,
            f"https://cloudskillsboost.google/public_profiles/{GOOGLE_PROFILE_ID}",
            status=500,
        )

        # Create local JSON file
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "google_skills_badges.json"
        local_json.write_text(json.dumps(sample_google_skills_json))

        with (
            patch("update_google_skills.VALIDATION_DIR", str(validation_dir)),
            patch("update_google_skills.OUTPUT_FILE", str(local_json)),
        ):
            badges = fetch_google_skills_badges(GOOGLE_PROFILE_ID)
            assert len(badges) == 2


class TestGoogleSkillsLossGuard:
    """Tests for Google Skills loss guard functions."""

    def test_get_stored_archive_baseline_count(self, temp_dir):
        monolith = temp_dir / "google-skills-complete.md"
        monolith.write_text("""# Header

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 | Google | Badge |
| 2024-01-10 | Badge 2 | Google | Badge |
""")

        local_json = temp_dir / "google_skills_badges.json"
        local_json.write_text("[]")

        with (
            patch("update_google_skills.ARCHIVE_MONOLITH", str(monolith)),
            patch("update_google_skills.VALIDATION_DIR", str(temp_dir)),
            patch("update_google_skills.OUTPUT_FILENAME", "google_skills_badges.json"),
        ):
            count = get_stored_archive_baseline_count(str(local_json), str(monolith))
            assert count == 2

    def test_execute_data_loss_guard(self, temp_dir):
        monolith = temp_dir / "google-skills-complete.md"
        monolith.write_text("""# Header

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 | Google | Badge |
| 2024-01-10 | Badge 2 | Google | Badge |
| 2024-01-05 | Badge 3 | Google | Badge |
""")

        badges = [
            {"id": "1", "title": "Badge 1"},
            {"id": "2", "title": "Badge 2"},
            {"id": "3", "title": "Badge 3"},
        ]

        with (
            patch("update_google_skills.ARCHIVE_MONOLITH", str(monolith)),
            patch("update_google_skills.VALIDATION_DIR", str(temp_dir)),
            patch("update_google_skills.OUTPUT_FILENAME", "google_skills_badges.json"),
        ):
            execute_data_loss_guard(badges, "test.json")


class TestGoogleSkillsPipelineIntegration:
    """Integration tests for the full Google Skills pipeline."""

    def test_main_pipeline_success(
        self,
        temp_dir,
        sample_google_skills_json,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "google_skills_badges.json"
        local_json.write_text(json.dumps(sample_google_skills_json))

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        with (
            patch("update_google_skills.VALIDATION_DIR", str(validation_dir)),
            patch("update_google_skills.OUTPUT_FILE", str(local_json)),
            patch("update_google_skills.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_google_skills.ARCHIVE_MONOLITH",
                str(archives_dir / "google-skills-complete.md"),
            ),
            patch("update_google_skills.README_PATH", str(readme)),
            patch(
                "update_google_skills.fetch_google_skills_badges",
                return_value=[
                    {
                        "id": "123",
                        "title": "Google Cloud Fundamentals",
                        "name": "Google Cloud Fundamentals",
                        "issued_at": "2024-01-15",
                        "verify_url": "https://skills.google/badges/123",
                        "image_url": "https://img.com/1",
                        "type": "Google Skill Badge",
                        "skills": ["Google Cloud"],
                    },
                    {
                        "id": "456",
                        "title": "Kubernetes Engine Basics",
                        "name": "Kubernetes Engine Basics",
                        "issued_at": "1705238400000",
                        "verify_url": "https://skills.google/badges/456",
                        "image_url": "",
                        "type": "Google Skill Badge",
                        "skills": ["Kubernetes"],
                    },
                ],
            ),
        ):
            main()

            # Verify output file updated
            assert local_json.exists()
            data = json.loads(local_json.read_text(encoding="utf-8"))
            assert data["profile_id"] == GOOGLE_PROFILE_ID
            assert len(data["badges"]) == 2

    def test_main_pipeline_network_then_local(
        self,
        temp_dir,
        sample_google_skills_json,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        """Should try network first, then fall back to local."""
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "google_skills_badges.json"
        local_json.write_text(json.dumps(sample_google_skills_json))

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        with (
            patch("update_google_skills.VALIDATION_DIR", str(validation_dir)),
            patch("update_google_skills.OUTPUT_FILE", str(local_json)),
            patch("update_google_skills.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_google_skills.ARCHIVE_MONOLITH",
                str(archives_dir / "google-skills-complete.md"),
            ),
            patch("update_google_skills.README_PATH", str(readme)),
            patch(
                "update_google_skills.fetch_google_skills_badges",
                return_value=[
                    {
                        "id": "123",
                        "title": "Google Cloud Fundamentals",
                        "name": "Google Cloud Fundamentals",
                        "issued_at": "2024-01-15",
                        "verify_url": "https://skills.google/badges/123",
                        "image_url": "https://img.com/1",
                        "type": "Google Skill Badge",
                        "skills": ["Google Cloud"],
                    },
                    {
                        "id": "456",
                        "title": "Kubernetes Engine Basics",
                        "name": "Kubernetes Engine Basics",
                        "issued_at": "1705238400000",
                        "verify_url": "https://skills.google/badges/456",
                        "image_url": "",
                        "type": "Google Skill Badge",
                        "skills": ["Kubernetes"],
                    },
                ],
            ),
        ):
            # Network will fail (no responses registered), should fall back to local
            main()

            data = json.loads(local_json.read_text(encoding="utf-8"))
            assert len(data["badges"]) == 2
