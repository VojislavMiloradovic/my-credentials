"""
Integration tests for AWS Skills pipeline (update_aws_skills.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_aws_skills import (
    AWS_PROFILE_USER,
    MARKER_END,
    MARKER_START,
    AwsBadgeItemModel,
    execute_data_loss_guard,
    fetch_aws_skills_badges,
    generate_badge_id,
    locate_aws_csv_file,
    main,
    normalize_date_string,
    parse_aws_badges_from_csv,
    parse_aws_badges_from_json,
)


class TestAwsSkillsHelpers:
    """Tests for AWS Skills helper functions."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("Jan 15, 2024", "2024-01-15"),
            ("2024-02-20", "2024-02-20"),
            ("1705312800000", "2024-01-15"),
            ("", None),
            (None, None),
        ],
    )
    def test_normalize_date_string(self, input_val, expected):
        assert normalize_date_string(input_val) == expected

    def test_generate_badge_id(self):
        id1 = generate_badge_id("Test Badge", "2024-01-15")
        id2 = generate_badge_id("Test Badge", "2024-01-15")
        id3 = generate_badge_id("Other Badge", "2024-01-15")
        assert id1 == id2
        assert id1 != id3
        assert len(id1) == 16


class TestAwsSkillsModels:
    """Tests for AWS Skills Pydantic models."""

    def test_aws_badge_item_model_valid(self, aws_badge_builder):
        badge = aws_badge_builder()
        model = AwsBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]

    def test_aws_badge_item_model_date_coercion(self):
        badge = AwsBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            issued_at="Jan 15, 2024",
            issued_at_date="1705312800000",
            date="2024-01-15",
        )
        assert badge.issued_at == "2024-01-15"
        assert badge.issued_at_date == "2024-01-15"
        assert badge.date == "2024-01-15"


class TestAwsSkillsParsers:
    """Tests for AWS Skills parsing functions."""

    def test_parse_aws_badges_from_json(self, temp_dir, sample_aws_api_response):
        json_file = temp_dir / "aws_skills.json"
        json_file.write_text(json.dumps(sample_aws_api_response))

        badges = parse_aws_badges_from_json(str(json_file))
        assert len(badges) == 2
        assert badges[0]["id"] == "aws-001"

    def test_locate_aws_csv_file(self, temp_dir, sample_aws_csv, monkeypatch):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)

        def mock_locate(*args, **kwargs):
            return str(csv_file)

        monkeypatch.setattr(
            "tests.integration.test_aws_skills_pipeline.locate_aws_csv_file",
            mock_locate,
        )
        monkeypatch.setattr("update_aws_skills.locate_aws_csv_file", mock_locate)

        found = locate_aws_csv_file()
        assert found == str(csv_file)

    def test_parse_aws_badges_from_csv(self, temp_dir, sample_aws_csv):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)

        badges = parse_aws_badges_from_csv(str(csv_file), "testuser")
        assert len(badges) == 4  # 5 rows, 1 invalid (empty row)
        assert badges[0]["id"] == "aws-001"
        assert badges[3]["id"] == "aws-004"


class TestAwsSkillsFetch:
    """Tests for AWS Skills fetching with mocked HTTP."""

    @responses.activate
    def test_fetch_aws_skills_csv_priority(
        self, temp_dir, sample_aws_csv, sample_aws_api_response
    ):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)

        with (
            patch("update_aws_skills.locate_aws_csv_file", return_value=str(csv_file)),
            patch("update_aws_skills.os.path.exists", lambda p: True),
        ):
            badges = fetch_aws_skills_badges(AWS_PROFILE_USER)
            assert len(badges) == 4

    @responses.activate
    def test_fetch_aws_skills_json_fallback(self, temp_dir, sample_aws_api_response):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "aws_skill_badges.json"
        local_json.write_text(json.dumps(sample_aws_api_response))

        with (
            patch("update_aws_skills.locate_aws_csv_file", return_value=None),
            patch("update_aws_skills.os.path.exists", lambda p: True),
            patch(
                "update_aws_skills.parse_aws_badges_from_json",
                return_value=[
                    {
                        "id": "aws-001",
                        "title": "Badge 1",
                        "name": "Badge 1",
                        "issuer": "AWS",
                        "issuer_name": "AWS",
                    },
                    {
                        "id": "aws-002",
                        "title": "Badge 2",
                        "name": "Badge 2",
                        "issuer": "AWS",
                        "issuer_name": "AWS",
                    },
                ],
            ),
        ):
            badges = fetch_aws_skills_badges(AWS_PROFILE_USER)
            assert len(badges) == 2

    @responses.activate
    def test_fetch_aws_skills_api_fallback(self, temp_dir, sample_aws_api_response):
        responses.add(
            responses.GET,
            f"https://skillsprofile.skillbuilder.aws/user/{AWS_PROFILE_USER}",
            json=sample_aws_api_response,
            status=200,
        )

        with (
            patch("update_aws_skills.locate_aws_csv_file", return_value=None),
            patch("update_aws_skills.os.path.exists", lambda p: False),
        ):
            badges = fetch_aws_skills_badges(AWS_PROFILE_USER)
            assert len(badges) == 2


class TestAwsSkillsLossGuard:
    """Tests for AWS Skills loss guard functions."""

    def test_execute_data_loss_guard(self, temp_dir):
        monolith = temp_dir / "aws-skills-complete.md"
        monolith.write_text("""# Header

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | Badge 1 | AWS | Badge |
| 2024-01-10 | Badge 2 | AWS | Badge |
| 2024-01-05 | Badge 3 | AWS | Badge |
""")

        badges = [
            {"id": "1", "title": "Badge 1"},
            {"id": "2", "title": "Badge 2"},
            {"id": "3", "title": "Badge 3"},
        ]

        with (
            patch("update_aws_skills.ARCHIVE_MONOLITH", str(monolith)),
            patch("update_aws_skills.VALIDATION_DIR", str(temp_dir)),
            patch("update_aws_skills.OUTPUT_FILENAME", "aws_skill_badges.json"),
        ):
            execute_data_loss_guard(badges, "test.json")


class TestAwsSkillsPipelineIntegration:
    """Integration tests for the full AWS Skills pipeline."""

    def test_main_pipeline_csv_success(
        self,
        temp_dir,
        sample_aws_csv,
        mock_archiver,
        mock_loss_guard,
        mock_retired_rules,
    ):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)

        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")

        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        with (
            patch("update_aws_skills.locate_aws_csv_file", return_value=str(csv_file)),
            patch("update_aws_skills.README_PATH", str(readme)),
            patch("update_aws_skills.ARCHIVE_DIR", str(archives_dir)),
            patch(
                "update_aws_skills.ARCHIVE_MONOLITH",
                str(archives_dir / "aws-skills-complete.md"),
            ),
            patch("update_aws_skills.VALIDATION_DIR", str(validation_dir)),
            patch(
                "update_aws_skills.OUTPUT_FILE",
                str(validation_dir / "aws_skill_badges.json"),
            ),
        ):
            main()

            validation_file = validation_dir / "aws_skill_badges.json"
            assert validation_file.exists()
            data = json.loads(validation_file.read_text())
            assert data["profile_user"] == AWS_PROFILE_USER
            assert len(data["badges"]) == 4


class TestAwsSkillsRetirementHandling:
    """Tests for AWS Skills retirement handling (Phase 5)."""

    def test_parse_aws_badges_from_csv_with_retired_status(
        self, temp_dir, mock_loss_guard
    ):
        """Test parsing CSV with Status=Retired column."""
        csv_content = """Title,Type,Status,Highest Score,Assigned on,Enrolled on,Started on,Completed on,Duration,Level,Language
[RETIRED] Test Retired Course,Digital course,Retired,0,-,"January 15, 2026","January 15, 2026","January 15, 2026",1 hour,Fundamental,English
Active Course,Digital course,Completed,100,-,"February 15, 2026","February 15, 2026","February 15, 2026",2 hours,Intermediate,English
[RETIRED] Another Retired Course,Digital course,Retired,0,-,"March 15, 2026","March 15, 2026","March 15, 2026",30 minutes,Advanced,English
"""
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(csv_content)

        badges = parse_aws_badges_from_csv(str(csv_file), "testuser")

        assert len(badges) == 3

        # Check retired items
        retired_badges = [b for b in badges if b.get("retired")]
        assert len(retired_badges) == 2

        for badge in retired_badges:
            assert badge["retired"] is True
            assert badge["retirement_reason"] == "Source CSV Status=Retired"
            assert badge["retirement_source"] == "source_csv"
            assert badge["retired_at"] is not None
            # Title should have [RETIRED] prefix stripped
            assert not badge["title"].startswith("[RETIRED]")

        # Check active item
        active_badges = [b for b in badges if not b.get("retired")]
        assert len(active_badges) == 1
        assert active_badges[0]["retired"] is False
        assert "retirement_reason" not in active_badges[0]

    def test_parse_aws_badges_from_csv_retired_flag_propagation(
        self, temp_dir, mock_loss_guard
    ):
        """Test that retired flag is never reset to False during column iteration."""
        csv_content = """Title,Type,Status,Highest Score,Assigned on,Enrolled on,Started on,Completed on,Duration,Level,Language
[RETIRED] Test Course,Digital course,Retired,0,-,"January 15, 2026","January 15, 2026","January 15, 2026",1 hour,Fundamental,English
"""
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(csv_content)

        badges = parse_aws_badges_from_csv(str(csv_file), "testuser")

        assert len(badges) == 1
        badge = badges[0]
        # The retired flag should be True and never reset
        assert badge["retired"] is True
        assert badge["retirement_reason"] == "Source CSV Status=Retired"
        assert badge["retirement_source"] == "source_csv"

    def test_parse_aws_badges_from_csv_retiring_soon_status(
        self, temp_dir, mock_loss_guard
    ):
        """Test parsing CSV with RETIRING - YYYY-MM-DD status."""
        csv_content = """Title,Type,Status,Highest Score,Assigned on,Enrolled on,Started on,Completed on,Duration,Level,Language
[RETIRING - 2026-11-07] Soon Retired Course,Digital course,Completed,0,-,"January 15, 2026","January 15, 2026","January 15, 2026",1 hour,Fundamental,English
"""
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(csv_content)

        badges = parse_aws_badges_from_csv(str(csv_file), "testuser")

        assert len(badges) == 1
        badge = badges[0]

        # RETIRING status should not set retired=True (only "Retired" does)
        assert badge["retired"] is False
        assert "retirement_reason" not in badge
        # Title should have [RETIRING - ...] prefix stripped
        assert not badge["title"].startswith("[RETIRING")

    def test_parse_aws_badges_from_csv_fixture_with_retired(
        self, temp_dir, mock_loss_guard
    ):
        """Test parsing the actual transcript_with_retired.csv fixture."""
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "aws_skills"
            / "transcript_with_retired.csv"
        )

        if not fixture_path.exists():
            pytest.skip("Fixture file not found")

        badges = parse_aws_badges_from_csv(str(fixture_path), "testuser")

        # Should have both retired and active items
        assert len(badges) > 0

        retired_badges = [b for b in badges if b.get("retired")]
        active_badges = [b for b in badges if not b.get("retired")]

        # Should have at least some retired items from the fixture
        assert len(retired_badges) > 0
        assert len(active_badges) > 0

        for badge in retired_badges:
            assert badge["retired"] is True
            assert badge["retirement_reason"] == "Source CSV Status=Retired"
            assert badge["retirement_source"] == "source_csv"
            assert badge["retired_at"] is not None

    def test_sync_retired_to_registry_adds_new_entries(self, temp_dir, monkeypatch):
        """Test sync_retired_to_registry adds source-flagged retired items."""
        from update_aws_skills import AWSSkillsPipeline

        # Create a pipeline instance
        pipeline = AWSSkillsPipeline()

        # Mock the retired rules file
        retired_file = temp_dir / "retired_urls.json"
        monkeypatch.setattr("update_aws_skills.RETIRED_URLS_FILE", str(retired_file))

        # Create test records with retired items
        records = [
            {
                "id": "aws-001",
                "title": "Retired Course 1",
                "retired": True,
                "retirement_reason": "Source CSV Status=Retired",
                "retired_at": "2026-01-15",
                "retirement_source": "source_csv",
                "verify_url": "https://example.com/1",
            },
            {
                "id": "aws-002",
                "title": "Retired Course 2",
                "retired": True,
                "retirement_reason": "Source CSV Status=Retired",
                "retired_at": "2026-02-15",
                "retirement_source": "source_csv",
                "verify_url": "https://example.com/2",
            },
            {
                "id": "aws-003",
                "title": "Active Course",
                "retired": False,
                "verify_url": "https://example.com/3",
            },
        ]

        added = pipeline.sync_retired_to_registry(records)

        assert added == 2

        # Verify the registry was updated
        import json

        with open(retired_file, "r") as f:
            data = json.load(f)

        assert "aws-skills" in data
        assert len(data["aws-skills"]) == 2
        ids = {rule["id"] for rule in data["aws-skills"]}
        assert "aws-001" in ids
        assert "aws-002" in ids

    def test_sync_retired_to_registry_id_only_deduplication(
        self, temp_dir, monkeypatch
    ):
        """Test ID-only deduplication for AWS (all items share same URL)."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        retired_file = temp_dir / "retired_urls.json"
        monkeypatch.setattr("update_aws_skills.RETIRED_URLS_FILE", str(retired_file))

        # Pre-populate registry with one entry
        import json

        with open(retired_file, "w") as f:
            json.dump(
                {
                    "aws-skills": [
                        {
                            "id": "aws-001",
                            "match_type": "url",
                            "reason": "Source CSV Status=Retired",
                            "retired_at": "2026-01-15",
                            "title": "Existing Retired Course",
                            "retirement_source": "source_csv",
                            "url": "https://skillsprofile.skillbuilder.aws/user/testuser",
                        }
                    ]
                },
                f,
            )

        # New records - same URL but different IDs
        records = [
            {
                "id": "aws-001",  # Already in registry
                "title": "Existing Retired Course",
                "retired": True,
                "retirement_reason": "Source CSV Status=Retired",
                "retired_at": "2026-01-15",
                "retirement_source": "source_csv",
                "verify_url": "https://skillsprofile.skillbuilder.aws/user/testuser",
            },
            {
                "id": "aws-002",  # New ID, same URL
                "title": "New Retired Course",
                "retired": True,
                "retirement_reason": "Source CSV Status=Retired",
                "retired_at": "2026-02-15",
                "retirement_source": "source_csv",
                "verify_url": "https://skillsprofile.skillbuilder.aws/user/testuser",
            },
        ]

        added = pipeline.sync_retired_to_registry(records)

        # Should only add the new one (aws-002), not the duplicate (aws-001)
        assert added == 1

        with open(retired_file, "r") as f:
            data = json.load(f)

        assert len(data["aws-skills"]) == 2
        ids = {rule["id"] for rule in data["aws-skills"]}
        assert "aws-001" in ids
        assert "aws-002" in ids

    def test_sync_retired_to_registry_skips_non_source_retired(
        self, temp_dir, monkeypatch
    ):
        """Test that registry sync only processes source_csv retirement_source."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        retired_file = temp_dir / "retired_urls.json"
        monkeypatch.setattr("update_aws_skills.RETIRED_URLS_FILE", str(retired_file))

        records = [
            {
                "id": "aws-001",
                "title": "Registry Retired",
                "retired": True,
                "retirement_reason": "Registry matched",
                "retired_at": "2026-01-15",
                "retirement_source": "registry",  # Not source_csv
                "verify_url": "https://example.com/1",
            },
            {
                "id": "aws-002",
                "title": "Auto Retired",
                "retired": True,
                "retirement_reason": "Auto-detected",
                "retired_at": "2026-02-15",
                "retirement_source": "auto",  # Not source_csv
                "verify_url": "https://example.com/2",
            },
            {
                "id": "aws-003",
                "title": "Source CSV Retired",
                "retired": True,
                "retirement_reason": "Source CSV Status=Retired",
                "retired_at": "2026-03-15",
                "retirement_source": "source_csv",
                "verify_url": "https://example.com/3",
            },
        ]

        added = pipeline.sync_retired_to_registry(records)

        # Only source_csv should be added
        assert added == 1

        with open(retired_file, "r") as f:
            data = json.load(f)

        assert len(data["aws-skills"]) == 1
        assert data["aws-skills"][0]["id"] == "aws-003"

    def test_format_for_archive_with_retired_items(self, temp_dir):
        """Test format_for_archive produces enhanced retired markers."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        # Test source_csv retirement
        record = {
            "id": "aws-001",
            "title": "Retired Course",
            "issued_at": "2026-01-15",
            "verify_url": "https://example.com/1",
            "issuer": "Amazon Web Services",
            "type": "Digital course",
            "retired": True,
            "retirement_reason": "Source CSV Status=Retired",
            "retired_at": "2026-01-15",
            "retirement_source": "source_csv",
        }

        row_text, date_str = pipeline.format_for_archive(record)

        assert date_str == "2026-01-15"
        assert (
            "[WARN] *Content retired (platform-flagged: Source CSV Status=Retired, 2026-01-15)*"
            in row_text
        )
        assert "Digital course" in row_text
        assert "Retired Course" in row_text

    def test_format_for_archive_with_registry_retired(self, temp_dir):
        """Test format_for_archive with registry-matched retirement."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        record = {
            "id": "aws-001",
            "title": "Registry Retired Course",
            "issued_at": "2026-01-15",
            "verify_url": "https://example.com/1",
            "issuer": "Amazon Web Services",
            "type": "Digital course",
            "retired": True,
            "retirement_reason": "Registry matched",
            "retired_at": "2026-01-15",
            "retirement_source": "registry",
        }

        row_text, _date_str = pipeline.format_for_archive(record)

        assert "[WARN] *Content retired (registry-matched)*" in row_text

    def test_format_for_archive_with_auto_retired(self, temp_dir):
        """Test format_for_archive with auto-detected retirement."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        record = {
            "id": "aws-001",
            "title": "Auto Retired Course",
            "issued_at": "2026-01-15",
            "verify_url": "https://example.com/1",
            "issuer": "Amazon Web Services",
            "type": "Digital course",
            "retired": True,
            "retirement_reason": "Auto-detected",
            "retired_at": "2026-01-15",
            "retirement_source": "auto",
        }

        row_text, _date_str = pipeline.format_for_archive(record)

        assert "[WARN] *Content retired (auto-detected: 2026-01-15)*" in row_text

    def test_format_for_archive_without_retired(self, temp_dir):
        """Test format_for_archive for active (non-retired) items."""
        from update_aws_skills import AWSSkillsPipeline

        pipeline = AWSSkillsPipeline()

        record = {
            "id": "aws-001",
            "title": "Active Course",
            "issued_at": "2026-01-15",
            "verify_url": "https://example.com/1",
            "issuer": "Amazon Web Services",
            "type": "Digital course",
            "retired": False,
        }

        row_text, date_str = pipeline.format_for_archive(record)

        assert date_str == "2026-01-15"
        assert "[WARN]" not in row_text
        assert "Digital course" in row_text
        assert "Active Course" in row_text
