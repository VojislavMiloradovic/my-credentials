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

    @pytest.mark.parametrize("input_val,expected", [
        ("Jan 15, 2024", "2024-01-15"),
        ("2024-02-20", "2024-02-20"),
        ("1705312800000", "2024-01-15"),
        ("", None),
        (None, None),
    ])
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

    def test_locate_aws_csv_file(self, temp_dir, sample_aws_csv):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)
        
        with patch("update_aws_skills.os.path.exists", lambda p: p == str(csv_file)), \
             patch("update_aws_skills.glob.glob", return_value=[]):
            found = locate_aws_csv_file()
            assert found == str(csv_file)

    def test_parse_aws_badges_from_csv(self, temp_dir, sample_aws_csv):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)
        
        badges = parse_aws_badges_from_csv(str(csv_file), "testuser")
        assert len(badges) == 3  # 4 rows, 1 invalid (empty title)
        assert badges[0]["id"] == "aws-001"
        assert badges[2]["id"].startswith("aws-skills-")  # Generated ID


class TestAwsSkillsFetch:
    """Tests for AWS Skills fetching with mocked HTTP."""

    @responses.activate
    def test_fetch_aws_skills_csv_priority(self, temp_dir, sample_aws_csv, sample_aws_api_response):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)
        
        with patch("update_aws_skills.locate_aws_csv_file", return_value=str(csv_file)), \
             patch("update_aws_skills.os.path.exists", lambda p: True):
            badges = fetch_aws_skills_badges(AWS_PROFILE_USER)
            assert len(badges) == 3

    @responses.activate
    def test_fetch_aws_skills_json_fallback(self, temp_dir, sample_aws_api_response):
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        local_json = validation_dir / "aws_skill_badges.json"
        local_json.write_text(json.dumps(sample_aws_api_response))
        
        with patch("update_aws_skills.locate_aws_csv_file", return_value=None), \
             patch("update_aws_skills.os.path.exists", lambda p: p == str(local_json)):
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
        
        with patch("update_aws_skills.locate_aws_csv_file", return_value=None), \
             patch("update_aws_skills.os.path.exists", lambda p: False):
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
        
        with patch("update_aws_skills.ARCHIVE_MONOLITH", str(monolith)), \
             patch("update_aws_skills.VALIDATION_DIR", str(temp_dir)), \
             patch("update_aws_skills.OUTPUT_FILENAME", "aws_skill_badges.json"):
            execute_data_loss_guard(badges, "test.json")


class TestAwsSkillsPipelineIntegration:
    """Integration tests for the full AWS Skills pipeline."""

    def test_main_pipeline_csv_success(self, temp_dir, sample_aws_csv, mock_archiver, mock_loss_guard, mock_retired_rules):
        csv_file = temp_dir / "aws-training-activity.csv"
        csv_file.write_text(sample_aws_csv)
        
        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        
        with patch("update_aws_skills.AWS_CSV_FILE", str(csv_file)), \
             patch("update_aws_skills.README_PATH", str(readme)), \
             patch("update_aws_skills.ARCHIVE_DIR", str(archives_dir)), \
             patch("update_aws_skills.ARCHIVE_MONOLITH", str(archives_dir / "aws-skills-complete.md")), \
             patch("update_aws_skills.VALIDATION_DIR", str(validation_dir)), \
             patch("update_aws_skills.OUTPUT_FILE", str(validation_dir / "aws_skill_badges.json")):
            
            main()
            
            validation_file = validation_dir / "aws_skill_badges.json"
            assert validation_file.exists()
            data = json.loads(validation_file.read_text())
            assert data["profile_user"] == AWS_PROFILE_USER
            assert len(data["badges"]) == 3