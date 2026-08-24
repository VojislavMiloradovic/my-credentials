"""
Unit tests for all Pydantic models across providers.
"""

import pytest
from pydantic import ValidationError

# Import all models
from update_aws_skills import AwsBadgeItemModel, AwsSkillsArchivePayloadModel
from update_credly_badges import CredlyArchivePayloadModel, CredlyBadgeItemModel
from update_google_developer import GoogleDeveloperBadgeModel
from update_google_skills import GoogleBadgeItemModel, GoogleSkillsArchivePayloadModel
from update_linkedin import LinkedInCertModel
from update_ms_learn import MSAchievementModel, MSVerifiableCredentialModel


class TestAwsModels:
    """Tests for AWS Skills Pydantic models."""

    def test_aws_badge_item_model_valid(self, aws_badge_builder):
        """Valid AWS badge should pass validation."""
        badge = aws_badge_builder()
        model = AwsBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]
        assert model.skills == ["AWS", "Test"]

    def test_aws_badge_item_model_missing_required(self):
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AwsBadgeItemModel(title="Test")
        assert "id" in str(exc_info.value)

    def test_aws_badge_item_model_empty_title_fails(self):
        """Empty title should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            AwsBadgeItemModel(id="test", title="")
        assert "at least 1 character" in str(exc_info.value)

    def test_aws_badge_item_model_date_coercion(self):
        """Date fields should be coerced to YYYY-MM-DD."""
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

    def test_aws_badge_item_model_skills_deduplication(self):
        """Skills list should be deduplicated."""
        badge = AwsBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            skills=["AWS", "AWS", "Cloud", "Cloud"],
        )
        assert badge.skills == ["AWS", "Cloud"]

    def test_aws_badge_item_model_skills_from_string(self):
        """String skills should be converted to list."""
        badge = AwsBadgeItemModel(id="test", title="Test", name="Test", skills="AWS")
        assert badge.skills == ["AWS"]

    def test_aws_skills_archive_payload_model_valid(self):
        """Valid archive payload should pass validation."""
        payload = {
            "profile_user": "testuser",
            "total_count": 2,
            "badges": [
                {
                    "id": "1",
                    "title": "Badge 1",
                    "name": "Badge 1",
                    "issuer": "AWS",
                    "issuer_name": "AWS",
                },
                {
                    "id": "2",
                    "title": "Badge 2",
                    "name": "Badge 2",
                    "issuer": "AWS",
                    "issuer_name": "AWS",
                },
            ],
        }
        model = AwsSkillsArchivePayloadModel(**payload)
        assert model.total_count == 2
        assert len(model.badges) == 2

    def test_aws_skills_archive_payload_negative_count_fails(self):
        """Negative total_count should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            AwsSkillsArchivePayloadModel(profile_user="test", total_count=-1, badges=[])
        assert "ge=0" in str(exc_info.value) or "greater than or equal to 0" in str(
            exc_info.value
        )


class TestGoogleSkillsModels:
    """Tests for Google Skills Pydantic models."""

    def test_google_badge_item_model_valid(self, google_badge_builder):
        """Valid Google badge should pass validation."""
        badge = google_badge_builder()
        model = GoogleBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]

    def test_google_badge_item_model_missing_required(self):
        """Missing required fields should raise ValidationError."""
        with pytest.raises(ValidationError):
            GoogleBadgeItemModel(title="Test")

    def test_google_badge_item_model_date_coercion(self):
        """Date fields should be coerced to YYYY-MM-DD."""
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
        """Valid archive payload should pass validation."""
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
        assert model.total_count == 1


class TestCredlyModels:
    """Tests for Credly Pydantic models."""

    def test_credly_badge_item_model_valid(self, credly_badge_builder):
        """Valid Credly badge should pass validation."""
        badge = credly_badge_builder()
        model = CredlyBadgeItemModel(**badge)
        assert model.id == badge["id"]
        assert model.title == badge["title"]

    def test_credly_badge_item_model_skills_from_dict(self):
        """Skills from dict objects should extract name/title."""
        badge = CredlyBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            issuer="Test",
            issuer_name="Test",
            skills=[{"name": "Python"}, {"title": "AWS"}, "String Skill"],
        )
        assert badge.skills == ["Python", "AWS", "String Skill"]

    def test_credly_badge_item_model_empty_skills_list(self):
        """Empty skills list should be valid."""
        badge = CredlyBadgeItemModel(
            id="test",
            title="Test",
            name="Test",
            issuer="Test",
            issuer_name="Test",
            skills=[],
        )
        assert badge.skills == []

    def test_credly_archive_payload_model_valid(self):
        """Valid archive payload should pass validation."""
        payload = {
            "credly_user": "testuser",
            "total_count": 1,
            "credentials": [
                {
                    "id": "1",
                    "title": "Badge 1",
                    "name": "Badge 1",
                    "issuer": "Test",
                    "issuer_name": "Test",
                }
            ],
        }
        model = CredlyArchivePayloadModel(**payload)
        assert model.credly_user == "testuser"
        assert model.total_count == 1


class TestLinkedInModels:
    """Tests for LinkedIn Pydantic models."""

    def test_linkedin_cert_model_valid(self, linkedin_cert_builder):
        """Valid LinkedIn cert should pass validation."""
        cert = linkedin_cert_builder()
        model = LinkedInCertModel(**cert)
        assert model.name == cert["name"]
        assert model.authority == cert["authority"]

    def test_linkedin_cert_model_date_coercion(self):
        """Date field should be coerced by parse_linkedin_date."""
        cert = LinkedInCertModel(
            name="Test",
            authority="Test",
            issued="Jan 2024",
        )
        assert cert.issued == "2024-01"

    def test_linkedin_cert_model_defaults(self):
        """Optional fields should have defaults."""
        cert = LinkedInCertModel(name="Test", authority="Test")
        assert cert.issued == "N/A"
        assert cert.url == ""
        assert cert.license == ""
        assert cert.original_order == 0
        assert cert.retired is False


class TestMsLearnModels:
    """Tests for Microsoft Learn Pydantic models."""

    def test_ms_achievement_model_valid(self, ms_achievement_builder):
        """Valid MS achievement should pass validation."""
        ach = ms_achievement_builder()
        model = MSAchievementModel(**ach)
        assert model.id == ach["id"]
        assert model.title == ach["title"]

    def test_ms_achievement_model_category_coercion(self):
        """Category should be stripped and default to 'module'."""
        ach = MSAchievementModel(id="test", category="  trophy  ")
        assert ach.category == "trophy"

        ach2 = MSAchievementModel(id="test")
        assert ach2.category == "module"

    def test_ms_achievement_model_date_coercion(self):
        """GrantedOn should be cleaned to YYYY-MM-DD."""
        ach = MSAchievementModel(id="test", grantedOn="2024-01-15T10:00:00Z")
        assert ach.grantedOn == "2024-01-15"

    def test_ms_verifiable_credential_model_valid(self):
        """Valid verifiable credential should pass validation."""
        cred = MSVerifiableCredentialModel(
            credentialId="CRED001",
            sourceUid="applied-skill.abc",
            awardedOn="2024-02-01",
            credentialStatus="Active",
        )
        assert cred.credentialId == "CRED001"
        assert cred.awardedOn == "2024-02-01"

    def test_ms_verifiable_credential_model_defaults(self):
        """Optional fields should have defaults."""
        cred = MSVerifiableCredentialModel()
        assert cred.credentialId == "N/A"
        assert cred.sourceUid == ""
        assert cred.awardedOn == "N/A"
        assert cred.credentialStatus == "Active"
        assert cred.retired is False


class TestGoogleDeveloperModels:
    """Tests for Google Developer Pydantic models."""

    def test_google_developer_badge_model_valid(self, gdev_badge_builder):
        """Valid GDev badge should pass validation."""
        badge = gdev_badge_builder()
        model = GoogleDeveloperBadgeModel(**badge)
        assert model.title == badge["title"]
        assert model.description == badge["description"]

    def test_google_developer_badge_model_date_coercion(self):
        """Date should be normalized including Serbian format (Cyrillic)."""
        badge = GoogleDeveloperBadgeModel(
            title="Test",
            description="Test",
            date="17. август 2024.",
        )
        assert badge.date == "2024-08-17"

    def test_google_developer_badge_model_defaults(self):
        """Optional fields should have defaults."""
        badge = GoogleDeveloperBadgeModel(title="Test", description="Test")
        assert badge.date == "N/A"
        assert badge.source == "public"
        assert badge.retired is False


class TestModelSerialization:
    """Tests for model serialization (model_dump)."""

    def test_aws_badge_model_dump(self, aws_badge_builder):
        """AWS badge model should serialize correctly."""
        badge = aws_badge_builder()
        model = AwsBadgeItemModel(**badge)
        dumped = model.model_dump()
        assert dumped["id"] == badge["id"]
        assert dumped["title"] == badge["title"]
        assert "issued_at" in dumped

    def test_google_badge_model_dump(self, google_badge_builder):
        """Google badge model should serialize correctly."""
        badge = google_badge_builder()
        model = GoogleBadgeItemModel(**badge)
        dumped = model.model_dump()
        assert dumped["id"] == badge["id"]

    def test_credly_badge_model_dump(self, credly_badge_builder):
        """Credly badge model should serialize correctly."""
        badge = credly_badge_builder()
        model = CredlyBadgeItemModel(**badge)
        dumped = model.model_dump()
        assert dumped["id"] == badge["id"]

    def test_linkedin_cert_model_dump(self, linkedin_cert_builder):
        """LinkedIn cert model should serialize correctly."""
        cert = linkedin_cert_builder()
        model = LinkedInCertModel(**cert)
        dumped = model.model_dump()
        assert dumped["name"] == cert["name"]

    def test_ms_achievement_model_dump(self, ms_achievement_builder):
        """MS achievement model should serialize correctly."""
        ach = ms_achievement_builder()
        model = MSAchievementModel(**ach)
        dumped = model.model_dump()
        assert dumped["id"] == ach["id"]

    def test_gdev_badge_model_dump(self, gdev_badge_builder):
        """GDev badge model should serialize correctly."""
        badge = gdev_badge_builder()
        model = GoogleDeveloperBadgeModel(**badge)
        dumped = model.model_dump()
        assert dumped["title"] == badge["title"]
