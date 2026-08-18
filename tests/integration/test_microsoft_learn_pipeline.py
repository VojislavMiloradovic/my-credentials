"""
Integration tests for Microsoft Learn pipeline (update_ms_learn.py).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_ms_learn import (
    MARKER_END,
    MARKER_START,
    MSAchievementModel,
    MSVerifiableCredentialModel,
    clean_iso_date,
    clean_uid,
    execute_data_loss_guard,
    format_num,
    format_verify_url,
    get_stored_archive_baseline_count,
    main,
    parse_date,
    resolve_level,
)


class TestMsLearnHelpers:
    """Tests for Microsoft Learn helper functions."""

    def test_format_num(self):
        assert format_num(1000) == "1,000"
        assert format_num(1000000) == "1,000,000"
        assert format_num("500") == "500"
        assert format_num(None) == "0"
        assert format_num("invalid") == "invalid"

    @pytest.mark.parametrize("input_url,expected", [
        ("learn.azure-fundamentals", "https://learn.microsoft.com/en-us/training/paths/azure-fundamentals"),
        ("/training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("https://learn.microsoft.com/training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("https://learn.microsoft.com/en-us/training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("  learn.test-path  ", "https://learn.microsoft.com/en-us/training/paths/test-path"),
        ("learn.path program/", "https://learn.microsoft.com/en-us/training/paths/path"),
        ("", ""),
        (None, ""),
    ])
    def test_format_verify_url(self, input_url, expected):
        assert format_verify_url(input_url) == expected

    def test_clean_uid(self):
        assert clean_uid("applied-skill.abc-def") == "Abc Def"
        assert clean_uid("learn.wwl.xyz-test") == "Xyz Test"
        assert clean_uid("simple") == "Simple"
        assert clean_uid(None) == ""
        assert clean_uid("") == ""

    @pytest.mark.parametrize("input_date,expected", [
        ("2024-01-15T10:00:00Z", "2024-01-15"),
        ("2024-01-15", "2024-01-15"),
        ("2024-01", "2024-01"),
        ("", "N/A"),
        (None, "N/A"),
    ])
    def test_clean_iso_date(self, input_date, expected):
        assert clean_iso_date(input_date) == expected

    def test_parse_date(self):
        dt = parse_date({"grantedOn": "2024-01-15T10:00:00Z"})
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.tzinfo is not None
        
        dt2 = parse_date({"date": "2024-02-20"})
        assert dt2.year == 2024
        assert dt2.month == 2
        assert dt2.day == 20
        
        dt3 = parse_date({})
        assert dt3 == datetime.min.replace(tzinfo=UTC)

    def test_resolve_level(self):
        xp_profile = {"level": {"levelNumber": 10}}
        xp_data = {}
        assert resolve_level(xp_profile, xp_data, 0) == "10"
        
        _ = {"totalXp": 6000000}
        assert resolve_level({}, {}, 6000000) == "20"
        
        assert resolve_level({}, {}, 0) == "20"


class TestMsLearnModels:
    """Tests for Microsoft Learn Pydantic models."""

    def test_ms_achievement_model_valid(self):
        ach = MSAchievementModel(
            id="ACH001",
            title="Test Achievement",
            category="module",
            grantedOn="2024-01-15",
            url="learn.test",
        )
        assert ach.id == "ACH001"
        assert ach.category == "module"

    def test_ms_achievement_model_date_coercion(self):
        ach = MSAchievementModel(id="test", grantedOn="2024-01-15T10:00:00Z")
        assert ach.grantedOn == "2024-01-15"

    def test_ms_achievement_model_category_default(self):
        ach = MSAchievementModel(id="test")
        assert ach.category == "module"

    def test_ms_verifiable_credential_model_valid(self):
        cred = MSVerifiableCredentialModel(
            credentialId="CRED001",
            sourceUid="applied-skill.abc",
            awardedOn="2024-02-01",
            credentialStatus="Active",
        )
        assert cred.credentialId == "CRED001"
        assert cred.awardedOn == "2024-02-01"

    def test_ms_verifiable_credential_model_defaults(self):
        cred = MSVerifiableCredentialModel()
        assert cred.credentialId == "N/A"
        assert cred.credentialStatus == "Active"


class TestMsLearnLossGuard:
    """Tests for Microsoft Learn loss guard functions."""

    def test_get_stored_archive_baseline_count_no_file(self, temp_dir):
        with patch("update_ms_learn.ARCHIVE_MONOLITH", str(temp_dir / "nonexistent.md")):
            count = get_stored_archive_baseline_count()
            assert count == 0

    def test_get_stored_archive_baseline_count_from_monolith(self, temp_dir):
        monolith = temp_dir / "microsoft-learn-complete.md"
        monolith.write_text("""# Header

| Achievement Title | Category | Date Earned | Verification Link |
| :--- | :--- | :--- | :--- |
| Badge 1 | Module | 2024-01-15 | [Verify](url) |
| Badge 2 | Module | 2024-01-10 | [Verify](url) |
""")
        
        with patch("update_ms_learn.ARCHIVE_MONOLITH", str(monolith)):
            count = get_stored_archive_baseline_count()
            assert count == 2

    def test_execute_data_loss_guard_pass(self, temp_dir):
        """Should pass when count is within threshold."""
        monolith = temp_dir / "microsoft-learn-complete.md"
        monolith.write_text("""# Header

| Achievement Title | Category | Date Earned | Verification Link |
| :--- | :--- | :--- | :--- |
| Badge 1 | Module | 2024-01-15 | [Verify](url) |
| Badge 2 | Module | 2024-01-10 | [Verify](url) |
| Badge 3 | Module | 2024-01-05 | [Verify](url) |
""")
        
        achievements = [
            {"id": "1", "title": "Badge 1"},
            {"id": "2", "title": "Badge 2"},
            {"id": "3", "title": "Badge 3"},
        ]
        
        with patch("update_ms_learn.ARCHIVE_MONOLITH", str(monolith)):
            # Should not raise
            execute_data_loss_guard(achievements)

    def test_execute_data_loss_guard_fail_zero_incoming(self, temp_dir):
        """Should fail when incoming is zero but baseline exists."""
        monolith = temp_dir / "microsoft-learn-complete.md"
        monolith.write_text("""# Header

| Achievement Title | Category | Date Earned | Verification Link |
| :--- | :--- | :--- | :--- |
| Badge 1 | Module | 2024-01-15 | [Verify](url) |
""")
        
        with patch("update_ms_learn.ARCHIVE_MONOLITH", str(monolith)):
            with pytest.raises(Exception) as exc_info:
                execute_data_loss_guard([])
            assert "CRITICAL ANOMALY" in str(exc_info.value)

    def test_execute_data_loss_guard_fail_threshold(self, temp_dir):
        """Should fail when drop exceeds 15%."""
        monolith = temp_dir / "microsoft-learn-complete.md"
        monolith.write_text("""# Header

| Achievement Title | Category | Date Earned | Verification Link |
| :--- | :--- | :--- | :--- |
| Badge 1 | Module | 2024-01-15 | [Verify](url) |
| Badge 2 | Module | 2024-01-10 | [Verify](url) |
| Badge 3 | Module | 2024-01-05 | [Verify](url) |
| Badge 4 | Module | 2024-01-01 | [Verify](url) |
| Badge 5 | Module | 2023-12-20 | [Verify](url) |
""")
        
        # Only 3 badges = 40% drop > 15% threshold
        achievements = [
            {"id": "1", "title": "Badge 1"},
            {"id": "2", "title": "Badge 2"},
            {"id": "3", "title": "Badge 3"},
        ]
        
        with patch("update_ms_learn.ARCHIVE_MONOLITH", str(monolith)):
            with pytest.raises(Exception) as exc_info:
                execute_data_loss_guard(achievements)
            assert "CRITICAL ANOMALY" in str(exc_info.value)


class TestMsLearnPipelineIntegration:
    """Integration tests for the full Microsoft Learn pipeline."""

    def test_main_pipeline_success(self, temp_dir, sample_ms_learn_json, mock_archiver, mock_loss_guard, mock_retired_rules):
        """Full pipeline should succeed with valid data."""
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        json_file = data_dir / "microsoft-learn.json"
        json_file.write_text(json.dumps(sample_ms_learn_json))
        
        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        
        with patch("update_ms_learn.JSON_PATH", str(json_file)), \
             patch("update_ms_learn.README_PATH", str(readme)), \
             patch("update_ms_learn.ARCHIVE_DIR", str(archives_dir)), \
             patch("update_ms_learn.ARCHIVE_MONOLITH", str(archives_dir / "microsoft-learn-complete.md")), \
             patch("update_ms_learn.VALIDATION_DIR", str(validation_dir)):
            
            # Run main
            main()
            
            # Verify validation file created
            validation_file = validation_dir / "microsoft-learn.json"
            assert validation_file.exists()
            data = json.loads(validation_file.read_text())
            assert data["platform"] == "microsoft-learn"
            assert "achievements" in data
            assert "verifiable_credentials" in data

    def test_main_pipeline_handles_retired_propagation(self, temp_dir, sample_ms_learn_json, mock_archiver, mock_loss_guard):
        """Should propagate retired status from learning paths to achievements."""
        # Add a retired learning path
        sample_ms_learn_json["Progress"]["learningPathPasses"][0]["retired"] = True
        sample_ms_learn_json["Progress"]["learningPathPasses"][0]["url"] = "learn.retired-path"
        
        # Add achievement matching that learning path
        sample_ms_learn_json["XP"]["achievements"].append({
            "id": "ACH004",
            "title": "Retired Path Achievement",
            "category": "module",
            "grantedOn": "2024-01-15",
            "url": "learn.retired-path",
        })
        
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        json_file = data_dir / "microsoft-learn.json"
        json_file.write_text(json.dumps(sample_ms_learn_json))
        
        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        
        with patch("update_ms_learn.JSON_PATH", str(json_file)), \
             patch("update_ms_learn.README_PATH", str(readme)), \
             patch("update_ms_learn.ARCHIVE_DIR", str(archives_dir)), \
             patch("update_ms_learn.ARCHIVE_MONOLITH", str(archives_dir / "microsoft-learn-complete.md")), \
             patch("update_ms_learn.VALIDATION_DIR", str(validation_dir)):
            
            main()
            
            # Check validation file has retired propagation
            validation_file = validation_dir / "microsoft-learn.json"
            data = json.loads(validation_file.read_text())
            
            # Find the propagated achievement
            ach = next((a for a in data["achievements"] if a["id"] == "ACH004"), None)
            assert ach is not None
            assert ach["retired"] is True

    def test_main_pipeline_missing_json_exits(self, temp_dir, mock_archiver, mock_loss_guard):
        """Should exit with error when JSON file not found."""
        with patch("update_ms_learn.JSON_PATH", str(temp_dir / "nonexistent.json")):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_main_pipeline_invalid_json_exits(self, temp_dir, mock_archiver, mock_loss_guard):
        """Should exit with error when JSON is invalid."""
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        json_file = data_dir / "microsoft-learn.json"
        json_file.write_text("invalid json")
        
        with patch("update_ms_learn.JSON_PATH", str(json_file)):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1


class TestMsLearnValidationOutput:
    """Tests for validation output structure."""

    def test_validation_output_structure(self, temp_dir, sample_ms_learn_json, mock_archiver, mock_loss_guard, mock_retired_rules):
        """Validation output should have expected structure."""
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        json_file = data_dir / "microsoft-learn.json"
        json_file.write_text(json.dumps(sample_ms_learn_json))
        
        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        
        with patch("update_ms_learn.JSON_PATH", str(json_file)), \
             patch("update_ms_learn.README_PATH", str(readme)), \
             patch("update_ms_learn.ARCHIVE_DIR", str(archives_dir)), \
             patch("update_ms_learn.ARCHIVE_MONOLITH", str(archives_dir / "microsoft-learn-complete.md")), \
             patch("update_ms_learn.VALIDATION_DIR", str(validation_dir)):
            
            main()
            
            validation_file = validation_dir / "microsoft-learn.json"
            data = json.loads(validation_file.read_text())
            
            # Check required fields
            assert data["platform"] == "microsoft-learn"
            assert "total_achievements" in data
            assert "total_learning_paths" in data
            assert "total_modules" in data
            assert "total_completed_units" in data
            assert "achievements" in data
            assert "learning_paths" in data
            assert "modules" in data
            assert "completed_units" in data
            assert "verifiable_credentials" in data
            
            # Check achievements have retired field
            for ach in data["achievements"]:
                assert "retired" in ach