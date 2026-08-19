"""
Integration tests for Credly pipeline (update_credly_badges.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_credly_badges import (
    CREDLY_USER,
    CREDLY_USER_ID,
    MARKER_END,
    MARKER_START,
    CredlyBadgeItemModel,
    fetch_credly_badges,
    fetch_credly_external_badges,
    load_existing_local_badges,
    main,
    merge_badge_datasets,
    normalize_date_string,
    parse_credly_badges_from_json,
)


class TestCredlyHelpers:
    """Tests for Credly helper functions."""

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


class TestCredlyModels:
    """Tests for Credly Pydantic models."""

    def test_credly_badge_item_model_valid(self, credly_badge_builder):
        badge = credly_badge_builder()
        model = CredlyBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]

    def test_credly_badge_item_model_skills_from_dict(self):
        badge = CredlyBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            issuer="Test",
            issuer_name="Test",
            skills=[{"name": "Python"}, {"title": "AWS"}, "String Skill"],
        )
        assert badge.skills == ["Python", "AWS", "String Skill"]


class TestCredlyParsers:
    """Tests for Credly parsing functions."""

    def test_parse_credly_badges_from_json(self, temp_dir, sample_credly_merged):
        json_file = temp_dir / "credly.json"
        json_file.write_text(json.dumps(sample_credly_merged))

        badges = parse_credly_badges_from_json(str(json_file))
        assert len(badges) == 4


class TestCredlyFetch:
    """Tests for Credly fetching with mocked HTTP."""

    @responses.activate
    def test_fetch_credly_badges_pagination(
        self, temp_dir, sample_credly_api_page1, sample_credly_api_page2
    ):
        responses.add(
            responses.GET,
            f"https://www.credly.com/users/{CREDLY_USER}/badges.json?page=1",
            json=sample_credly_api_page1,
            status=200,
        )
        responses.add(
            responses.GET,
            f"https://www.credly.com/users/{CREDLY_USER}/badges.json?page=2",
            json=sample_credly_api_page2,
            status=200,
        )

        badges = fetch_credly_badges(CREDLY_USER)
        assert len(badges) == 3

    @responses.activate
    def test_fetch_credly_external_badges(
        self, temp_dir, sample_credly_external_badges
    ):
        responses.add(
            responses.GET,
            f"https://www.credly.com/api/v1/users/{CREDLY_USER_ID}/external_badges/open_badges/public",
            json=sample_credly_external_badges,
            status=200,
        )

        badges = fetch_credly_external_badges(CREDLY_USER_ID)
        assert len(badges) == 1
        assert badges[0]["type"] == "Credly External Badge"

    @responses.activate
    def test_fetch_credly_handles_api_failure(self, temp_dir):
        responses.add(
            responses.GET,
            f"https://www.credly.com/users/{CREDLY_USER}/badges.json?page=1",
            status=500,
        )

        badges = fetch_credly_badges(CREDLY_USER)
        assert badges is None


class TestCredlyMerge:
    """Tests for badge dataset merging."""

    def test_merge_badge_datasets(self, credly_badge_builder):
        native = [
            credly_badge_builder(id="badge-001", title="Badge 1"),
            credly_badge_builder(id="badge-002", title="Badge 2"),
        ]
        external = [
            credly_badge_builder(
                id="ext-001", title="External 1", type="Credly External Badge"
            ),
        ]

        merged = merge_badge_datasets(native, external)
        assert len(merged) == 3
        ids = {b["id"] for b in merged}
        assert ids == {"badge-001", "badge-002", "ext-001"}

    def test_merge_badge_datasets_deduplicates(self, credly_badge_builder):
        native = [credly_badge_builder(id="badge-001", title="Badge 1")]
        external = [credly_badge_builder(id="badge-001", title="Badge 1 Duplicate")]

        merged = merge_badge_datasets(native, external)
        assert len(merged) == 1


class TestCredlyLocalFallback:
    """Tests for local fallback logic."""

    def test_load_existing_local_badges(self, temp_dir, sample_credly_merged):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "credly_badges.json"
        local_json.write_text(json.dumps(sample_credly_merged))

        with (
            patch("update_credly_badges.VALIDATION_DIR", str(validation_dir)),
            patch("update_credly_badges.OUTPUT_FILENAME", "credly_badges.json"),
            patch(
                "update_credly_badges.OUTPUT_FILE",
                str(validation_dir / "credly_badges.json"),
            ),
        ):
            badges = load_existing_local_badges()
            assert len(badges) == 4


class TestCredlyPipelineIntegration:
    """Integration tests for the full Credly pipeline."""

    def test_main_pipeline_success(
        self,
        temp_dir,
        sample_credly_merged,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "credly_badges.json"
        local_json.write_text(json.dumps(sample_credly_merged))

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        with (
            patch("update_credly_badges.VALIDATION_DIR", str(validation_dir)),
            patch("update_credly_badges.OUTPUT_FILE", str(local_json)),
            patch("update_credly_badges.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_credly_badges.ARCHIVE_MONOLITH",
                str(archives_dir / "credly-complete.md"),
            ),
            patch("update_credly_badges.README_PATH", str(readme)),
            patch("update_credly_badges.fetch_credly_badges", return_value=None),
            patch(
                "update_credly_badges.fetch_credly_external_badges", return_value=None
            ),
        ):
            main()

            # Should retain local data when API fails
            data = json.loads(local_json.read_text())
            assert len(data["badges"]) == 4

    def test_main_pipeline_api_success(
        self,
        temp_dir,
        sample_credly_api_page1,
        sample_credly_api_page2,
        sample_credly_external_badges,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "credly_badges.json"
        local_json.write_text("[]")

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()

        with (
            patch("update_credly_badges.VALIDATION_DIR", str(validation_dir)),
            patch("update_credly_badges.OUTPUT_FILE", str(local_json)),
            patch("update_credly_badges.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_credly_badges.ARCHIVE_MONOLITH",
                str(archives_dir / "credly-complete.md"),
            ),
            patch("update_credly_badges.README_PATH", str(readme)),
            responses.RequestsMock() as rsps,
        ):
            rsps.add(
                responses.GET,
                f"https://www.credly.com/users/{CREDLY_USER}/badges.json?page=1",
                json=sample_credly_api_page1,
                status=200,
            )
            rsps.add(
                responses.GET,
                f"https://www.credly.com/users/{CREDLY_USER}/badges.json?page=2",
                json=sample_credly_api_page2,
                status=200,
            )
            rsps.add(
                responses.GET,
                f"https://www.credly.com/api/v1/users/{CREDLY_USER_ID}/external_badges/open_badges/public",
                json=sample_credly_external_badges,
                status=200,
            )

            main()

            data = json.loads(local_json.read_text())
            assert len(data["badges"]) == 4  # 3 native + 1 external
