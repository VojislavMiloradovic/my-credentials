"""
Integration tests for Google Developer pipeline (update_google_developer.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_google_developer import (
    MARKER_END,
    MARKER_START,
    GoogleDeveloperBadgeModel,
    analyze_badge_list,
    execute_data_loss_guard,
    fetch_gdev_badges_rpc,
    find_badges_in_matrix,
    main,
    normalize_date_string,
    parse_local_learnings_txt,
)


class TestGoogleDeveloperHelpers:
    """Tests for Google Developer helper functions."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("17. august 2024.", "2024-08-17"),
            ("13. august 2024.", "2024-08-13"),
            ("1. januar 2024.", "2024-01-01"),
            ("15. feb 2024.", "2024-02-15"),
            ("2024-01-15", "2024-01-15"),
            ("", "N/A"),
            (None, "N/A"),
        ],
    )
    def test_normalize_date_string(self, input_val, expected):
        assert normalize_date_string(input_val) == expected


class TestGoogleDeveloperModels:
    """Tests for Google Developer Pydantic models."""

    def test_google_developer_badge_model_valid(self, gdev_badge_builder):
        badge = gdev_badge_builder()
        model = GoogleDeveloperBadgeModel(**badge)
        assert model.title == badge["title"]
        assert model.description == badge["description"]

    def test_google_developer_badge_model_date_coercion(self):
        badge = GoogleDeveloperBadgeModel(
            title="Test",
            description="Test",
            date="17. august 2024.",
        )
        assert badge.date == "2024-08-17"


class TestGoogleDeveloperParsers:
    """Tests for Google Developer parsing functions."""

    def test_parse_local_learnings_txt(
        self, temp_dir, sample_google_developer_learnings
    ):
        learnings_file = temp_dir / "google_learnings.txt"
        learnings_file.write_text(sample_google_developer_learnings)

        with patch("update_google_developer.LEARNINGS_TXT_PATH", str(learnings_file)):
            learnings = parse_local_learnings_txt()
            assert len(learnings) == 3
            assert (
                learnings[0]["title"]
                == "Setup Basic OpenTelemetry Plugin in gRPC Python"
            )
            assert learnings[0]["date"] == "2024-08-17"
            assert learnings[0]["source"] == "local_txt"

    def test_parse_local_learnings_txt_missing_file(self, temp_dir):
        with patch(
            "update_google_developer.LEARNINGS_TXT_PATH",
            str(temp_dir / "nonexistent.txt"),
        ):
            learnings = parse_local_learnings_txt()
            assert learnings == []

    def test_analyze_badge_list(self):
        parsed_badges = []
        data = [["/awards/badges/test-badge", 1705312800]]

        result = analyze_badge_list(data, parsed_badges)
        assert result is True
        assert len(parsed_badges) == 1
        assert parsed_badges[0]["title"] == "Test Badge"
        assert parsed_badges[0]["date"] == "2024-01-15"

    def test_find_badges_in_matrix(self):
        parsed_badges = []
        matrix = [
            [["/awards/badges/badge-1", 1705312800]],
            {"key": [["/awards/pathways/path-1", 1705399200]]},
        ]

        find_badges_in_matrix(matrix, parsed_badges)
        assert len(parsed_badges) == 2


class TestGoogleDeveloperFetch:
    """Tests for Google Developer RPC fetching."""

    @responses.activate
    def test_fetch_gdev_badges_rpc_success(self, sample_google_developer_rpc):
        responses.add(
            responses.POST,
            "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute",
            body=sample_google_developer_rpc,
            status=200,
        )

        badges = fetch_gdev_badges_rpc()
        assert len(badges) >= 2

    @responses.activate
    def test_fetch_gdev_badges_rpc_failure(self):
        responses.add(
            responses.POST,
            "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute",
            status=500,
        )

        badges = fetch_gdev_badges_rpc()
        assert badges == []


class TestGoogleDeveloperLossGuard:
    """Tests for Google Developer loss guard functions."""

    def test_execute_data_loss_guard(self, temp_dir):
        monolith = temp_dir / "google-developer-complete.md"
        monolith.write_text("""# Header

| Date Earned | Title | Description |
| :---: | :--- | :--- |
| 2024-01-15 | Badge 1 | Description 1 |
| 2024-01-10 | Badge 2 | Description 2 |
""")

        badges = [
            {"title": "Badge 1", "date": "2024-01-15", "description": "Description 1"},
            {"title": "Badge 2", "date": "2024-01-10", "description": "Description 2"},
        ]

        with patch("update_google_developer.ARCHIVE_MONOLITH", str(monolith)):
            execute_data_loss_guard(badges)


class TestGoogleDeveloperPipelineIntegration:
    """Integration tests for the full Google Developer pipeline."""

    def test_main_pipeline_success(
        self,
        temp_dir,
        sample_google_developer_rpc,
        sample_google_developer_learnings,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        learnings_file = temp_dir / "google_learnings.txt"
        learnings_file.write_text(sample_google_developer_learnings)

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        with (
            patch("update_google_developer.LEARNINGS_TXT_PATH", str(learnings_file)),
            patch("update_google_developer.README_PATH", str(readme)),
            patch("update_google_developer.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_google_developer.ARCHIVE_MONOLITH",
                str(archives_dir / "google-developer-complete.md"),
            ),
            patch("update_google_developer.VALIDATION_DIR", str(validation_dir)),
            responses.RequestsMock() as rsps,
        ):
            rsps.add(
                responses.POST,
                "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute",
                body=sample_google_developer_rpc,
                status=200,
            )

            main()

            validation_file = validation_dir / "google-developer.json"
            assert validation_file.exists()
            data = json.loads(validation_file.read_text())
            assert data["platform"] == "google-developer"
            assert "combined_feed" in data
            assert len(data["combined_feed"]) >= 3

    def test_main_pipeline_deduplicates(
        self,
        temp_dir,
        sample_google_developer_rpc,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        """Should deduplicate public badges against local text items."""
        learnings_content = """Setup Basic OpenTelemetry Plugin in gRPC Python
17. august 2024.
Учење
check_circle_outline You have this badge!
"""
        learnings_file = temp_dir / "google_learnings.txt"
        learnings_file.write_text(learnings_content)

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        with (
            patch("update_google_developer.LEARNINGS_TXT_PATH", str(learnings_file)),
            patch("update_google_developer.README_PATH", str(readme)),
            patch("update_google_developer.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_google_developer.ARCHIVE_MONOLITH",
                str(archives_dir / "google-developer-complete.md"),
            ),
            patch("update_google_developer.VALIDATION_DIR", str(validation_dir)),
            responses.RequestsMock() as rsps,
        ):
            rsps.add(
                responses.POST,
                "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute",
                body=sample_google_developer_rpc,
                status=200,
            )

            main()

            validation_file = validation_dir / "google-developer.json"
            data = json.loads(validation_file.read_text())
            titles = [b["title"] for b in data["combined_feed"]]
            assert titles.count("Setup Basic OpenTelemetry Plugin in gRPC Python") == 1
