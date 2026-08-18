"""
Unit tests for retired credential handling (load_retired_rules, mark_retired).
"""

import json
from unittest.mock import patch

import pytest


class TestLoadRetiredRules:
    """Tests for load_retired_rules function."""

    def test_load_retired_rules_no_file(self, temp_dir):
        """Should return empty list when file doesn't exist."""
        from update_aws_skills import load_retired_rules

        with patch(
            "update_aws_skills.RETIRED_URLS_FILE", str(temp_dir / "nonexistent.json")
        ):
            result = load_retired_rules("aws-skills")
            assert result == []

    def test_load_retired_rules_empty_platform(self, temp_dir):
        """Should return empty list when platform not in file."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"other-platform": [{"id": "test"}]}))

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert result == []

    def test_load_retired_rules_legacy_string_format(self, temp_dir):
        """Should handle legacy string array format."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {"aws-skills": ["https://example.com/1", "https://example.com/2"]}
            )
        )

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert len(result) == 2
            assert result[0]["id"] == "https://example.com/1"
            assert result[0]["match_type"] == "url"
            assert result[0]["url"] == "https://example.com/1"

    def test_load_retired_rules_structured_format(self, temp_dir):
        """Should handle structured rule objects."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "aws-skills": [
                        {
                            "id": "aws-001",
                            "match_type": "id",
                            "url": "https://example.com/1",
                            "reason": "Retired by AWS",
                            "retired_at": "2024-01-01",
                        }
                    ]
                }
            )
        )

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert len(result) == 1
            assert result[0]["id"] == "aws-001"
            assert result[0]["reason"] == "Retired by AWS"
            assert result[0]["retired_at"] == "2024-01-01"

    def test_load_retired_rules_mixed_format(self, temp_dir):
        """Should handle mixed legacy and structured formats."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "aws-skills": [
                        "https://example.com/1",  # Legacy string
                        {"id": "aws-002", "url": "https://example.com/2"},  # Structured
                    ]
                }
            )
        )

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert len(result) == 2

    def test_load_retired_rules_invalid_json(self, temp_dir):
        """Should return empty list and log warning for invalid JSON."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text("invalid json")

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert result == []

    def test_load_retired_rules_missing_id_skipped(self, temp_dir):
        """Should skip entries without id field."""
        from update_aws_skills import load_retired_rules

        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "aws-skills": [
                        {"url": "https://example.com/1"},  # Missing id
                        {"id": "aws-001", "url": "https://example.com/2"},
                    ]
                }
            )
        )

        with patch("update_aws_skills.RETIRED_URLS_FILE", str(retired_file)):
            result = load_retired_rules("aws-skills")
            assert len(result) == 1
            assert result[0]["id"] == "aws-001"


class TestMarkRetired:
    """Tests for mark_retired function."""

    def test_mark_retired_no_rules(self):
        """Should return (count, 0) when no rules."""
        from update_aws_skills import mark_retired

        items = [{"id": "1", "title": "Badge 1"}, {"id": "2", "title": "Badge 2"}]
        total, marked = mark_retired(items, [])
        assert total == 2
        assert marked == 0

    def test_mark_retired_by_id(self):
        """Should mark items matching rule ID."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "verify_url": "https://example.com/1"},
            {"id": "2", "title": "Badge 2", "verify_url": "https://example.com/2"},
        ]
        rules = [{"id": "1", "match_type": "id", "url": "https://example.com/1"}]

        total, marked = mark_retired(items, rules)
        assert total == 2
        assert marked == 1
        assert items[0]["retired"] is True
        assert items[1].get("retired", False) is False

    def test_mark_retired_by_url(self):
        """Should mark items matching rule URL."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "verify_url": "https://example.com/1"},
            {"id": "2", "title": "Badge 2", "verify_url": "https://example.com/2"},
        ]
        rules = [{"id": "rule-1", "match_type": "url", "url": "https://example.com/1"}]

        _, marked = mark_retired(items, rules)
        assert marked == 1
        assert items[0]["retired"] is True

    def test_mark_retired_skips_already_retired(self):
        """Should skip items already marked as retired."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "retired": True},
            {"id": "2", "title": "Badge 2", "retired": False},
        ]
        rules = [{"id": "1", "match_type": "id"}]

        _, marked = mark_retired(items, rules)
        assert marked == 0  # First already retired, second doesn't match

    def test_mark_retired_adds_metadata(self):
        """Should add retirement_reason and retired_at metadata."""
        from update_aws_skills import mark_retired

        items = [{"id": "1", "title": "Badge 1"}]
        rules = [
            {
                "id": "1",
                "reason": "Content retired",
                "retired_at": "2024-01-01",
            }
        ]

        _, marked = mark_retired(items, rules)
        assert marked == 1
        assert items[0]["retirement_reason"] == "Content retired"
        assert items[0]["retired_at"] == "2024-01-01"

    def test_mark_retired_custom_url_field(self):
        """Should use custom url_field parameter."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "sourceUid": "uid-1"},
            {"id": "2", "title": "Badge 2", "sourceUid": "uid-2"},
        ]
        rules = [{"id": "uid-1", "match_type": "url"}]

        _, marked = mark_retired(items, rules, url_field="sourceUid")
        assert marked == 1
        assert items[0]["retired"] is True

    def test_mark_retired_custom_id_fields(self):
        """Should use custom id_fields parameter."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "credentialId": "cred-1"},
            {"id": "2", "title": "Badge 2", "credentialId": "cred-2"},
        ]
        rules = [{"id": "cred-1", "match_type": "id"}]

        _, marked = mark_retired(items, rules, id_fields=["credentialId"])
        assert marked == 1
        assert items[0]["retired"] is True

    def test_mark_retired_url_field_as_list(self):
        """Should handle url_field as list of fields to try."""
        from update_ms_learn import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "url": None, "learningPathUid": "lp-1"},
            {
                "id": "2",
                "title": "Badge 2",
                "url": "https://example.com/2",
                "learningPathUid": None,
            },
        ]
        rules = [{"id": "lp-1", "match_type": "url"}]

        _, marked = mark_retired(items, rules, url_field=["url", "learningPathUid"])
        assert marked == 1
        assert items[0]["retired"] is True

    def test_mark_retired_normalize_url(self):
        """Should use normalize_url function when provided."""
        from update_ms_learn import mark_retired

        items = [
            {"id": "1", "title": "Badge 1", "url": "learn.retired-path"},
        ]
        rules = [
            {
                "id": "https://learn.microsoft.com/en-us/training/paths/retired-path",
                "match_type": "url",
            }
        ]

        def normalize_url(raw):
            if raw.startswith("learn."):
                return f"https://learn.microsoft.com/en-us/training/paths/{raw[6:]}"
            return raw

        _, marked = mark_retired(items, rules, normalize_url=normalize_url)
        assert marked == 1
        assert items[0]["retired"] is True

    def test_mark_retired_multiple_rules(self):
        """Should match against multiple rules."""
        from update_aws_skills import mark_retired

        items = [
            {"id": "1", "title": "Badge 1"},
            {"id": "2", "title": "Badge 2"},
            {"id": "3", "title": "Badge 3"},
        ]
        rules = [
            {"id": "1", "match_type": "id"},
            {"id": "3", "match_type": "id"},
        ]

        _, marked = mark_retired(items, rules)
        assert marked == 2
        assert items[0]["retired"] is True
        assert items[1].get("retired", False) is False
        assert items[2]["retired"] is True


class TestMarkRetiredCrossPlatform:
    """Tests for mark_retired across different provider implementations."""

    @pytest.mark.parametrize(
        "provider_module",
        [
            "update_aws_skills",
            "update_google_skills",
            "update_credly_badges",
            "update_linkedin",
            "update_google_developer",
        ],
    )
    def test_mark_retired_imports(self, provider_module):
        """Each provider should have mark_retired function."""
        module = __import__(provider_module, fromlist=["mark_retired"])
        assert hasattr(module, "mark_retired")
        assert callable(module.mark_retired)

    def test_load_retired_rules_imports(self):
        """Each provider should have load_retired_rules function."""
        for module_name in [
            "update_aws_skills",
            "update_google_skills",
            "update_credly_badges",
            "update_linkedin",
            "update_google_developer",
            "update_ms_learn",
        ]:
            module = __import__(module_name, fromlist=["load_retired_rules"])
            assert hasattr(module, "load_retired_rules")
            assert callable(module.load_retired_rules)


class TestRetiredRulesFileStructure:
    """Tests for retired_urls.json structure validation."""

    def test_retired_urls_json_valid(self):
        """The actual retired_urls.json should be valid JSON."""
        import os

        if os.path.exists("retired_urls.json"):
            with open("retired_urls.json", "r") as f:
                data = json.load(f)

            # Should have all platform keys
            expected_platforms = [
                "microsoft-learn",
                "google-skills",
                "aws-skills",
                "credly",
                "linkedin-certifications",
                "google-developer",
            ]
            for platform in expected_platforms:
                assert platform in data
                assert isinstance(data[platform], list)

            # Each entry should be valid
            for platform, entries in data.items():
                for entry in entries:
                    if isinstance(entry, dict):
                        assert "id" in entry
