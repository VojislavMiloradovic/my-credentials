"""Unit tests for evidence-aware provenance classification and JSON-LD edge cases."""

from unittest.mock import patch

import pytest

from cross_artifact_validator import CrossArtifactValidator, PlatformCounts
from generate_jsonld import (
    clean_str,
    extract_table_data_rows,
    parse_archive_monoliths,
    validate_jsonld,
)
from models.provenance import (
    EvidenceLevel,
    RetrievalMethod,
    VerificationStatus,
    VerificationUrlKind,
    classify_credential_evidence,
    classify_verification_url_kind,
)
from update_aws_skills import AwsBadgeItemModel
from update_credly_badges import CredlyBadgeItemModel
from update_google_developer import GoogleDeveloperBadgeModel
from update_google_skills import GoogleBadgeItemModel
from update_linkedin import LinkedInCertModel
from update_ms_learn import MSAchievementModel, MSVerifiableCredentialModel


class TestEvidenceClassification:
    """Tests for classify_verification_url_kind and classify_credential_evidence."""

    @pytest.mark.parametrize(
        "platform,url,expected_status,expected_evidence,expected_kind",
        [
            (
                "credly",
                "https://www.credly.com/badges/abc-123/public_url",
                VerificationStatus.VERIFIED,
                EvidenceLevel.ISSUER_CREDENTIAL,
                VerificationUrlKind.CREDENTIAL_ASSERTION,
            ),
            (
                "google-skills",
                "https://www.skills.google/public_profiles/user-1/badges/29734400",
                VerificationStatus.VERIFIED,
                EvidenceLevel.ISSUER_CREDENTIAL,
                VerificationUrlKind.CREDENTIAL_ASSERTION,
            ),
            (
                "aws-skills",
                "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.ISSUER_PROFILE,
                VerificationUrlKind.PROFILE_PAGE,
            ),
            (
                "microsoft-learn",
                "https://learn.microsoft.com/en-us/training/modules/example/",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.PLATFORM_ACTIVITY,
                VerificationUrlKind.CATALOG_PAGE,
            ),
            (
                "microsoft-learn",
                None,
                VerificationStatus.UNKNOWN,
                EvidenceLevel.SELF_REPORTED,
                VerificationUrlKind.NONE,
            ),
            (
                "linkedin-certifications",
                "https://www.credly.com/badges/8b535dbd-76db-4713-9e2e-1137abe99da0/linked_in_profile",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.ISSUER_CREDENTIAL,
                VerificationUrlKind.CREDENTIAL_ASSERTION,
            ),
            (
                "linkedin-certifications",
                "https://badger.learning.sap.com/verify/xyz",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.ISSUER_CREDENTIAL,
                VerificationUrlKind.CREDENTIAL_ASSERTION,
            ),
            (
                "linkedin-certifications",
                "https://www.linkedin.com/learning/certificates/abc123",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.PLATFORM_ACTIVITY,
                VerificationUrlKind.CATALOG_PAGE,
            ),
            (
                "linkedin-certifications",
                "https://skillshop.exceedlms.com/profiles/c92f51aa68fc451f9ee992f9e813024b",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.ISSUER_PROFILE,
                VerificationUrlKind.PROFILE_PAGE,
            ),
            (
                "google-developer",
                "https://codelabs.developers.google.com/secure-vibe-coding-with-codemender",
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.PLATFORM_ACTIVITY,
                VerificationUrlKind.CATALOG_PAGE,
            ),
            (
                "google-developer",
                None,
                VerificationStatus.UNVERIFIED,
                EvidenceLevel.ISSUER_PROFILE,
                VerificationUrlKind.NONE,
            ),
        ],
    )
    def test_pragmatic_classification_matrix(
        self, platform, url, expected_status, expected_evidence, expected_kind
    ):
        method = (
            RetrievalMethod.API
            if platform in ("credly", "google-skills", "google-developer")
            else RetrievalMethod.EXPORT
        )
        status, evidence, url_kind = classify_credential_evidence(
            platform, method, url=url
        )
        assert status == expected_status
        assert evidence == expected_evidence
        assert url_kind == expected_kind

    def test_retired_precedence_overrides_url(self):
        status, evidence, url_kind = classify_credential_evidence(
            "credly",
            RetrievalMethod.API,
            url="https://www.credly.com/badges/abc-123/public_url",
            retired=True,
        )
        assert status == VerificationStatus.RETIRED
        assert evidence == EvidenceLevel.ISSUER_CREDENTIAL
        assert url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION

    def test_expired_status_precedence(self):
        status, _, _ = classify_credential_evidence(
            "credly",
            RetrievalMethod.API,
            url="https://www.credly.com/badges/abc-123/public_url",
            credential_status="Expired",
        )
        assert status == VerificationStatus.EXPIRED

    def test_profile_vs_badge_google_skills_url(self):
        assert (
            classify_verification_url_kind(
                "google-skills",
                "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b",
            )
            == VerificationUrlKind.PROFILE_PAGE
        )
        assert (
            classify_verification_url_kind(
                "google-skills",
                "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b/badges/29734400",
            )
            == VerificationUrlKind.CREDENTIAL_ASSERTION
        )


class TestPydanticAutoClassification:
    """Tests that L1 Pydantic models automatically populate evidence fields."""

    def test_aws_badge_auto_classified_unverified(self):
        model = AwsBadgeItemModel(
            id="aws-1",
            title="AWS Course",
            name="AWS Course",
            verify_url="https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic",
        )
        assert model.verification_status == VerificationStatus.UNVERIFIED
        assert model.evidence_level == EvidenceLevel.ISSUER_PROFILE
        assert model.verification_url_kind == VerificationUrlKind.PROFILE_PAGE

    def test_credly_badge_auto_classified_verified(self):
        model = CredlyBadgeItemModel(
            id="credly-1",
            title="Badge",
            name="Badge",
            issuer="IBM",
            issuer_name="IBM",
            verify_url="https://www.credly.com/badges/123/public_url",
        )
        assert model.verification_status == VerificationStatus.VERIFIED
        assert model.evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
        assert model.verification_url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION

    def test_google_skills_badge_auto_classified_verified(self):
        model = GoogleBadgeItemModel(
            id="gs-1",
            title="GCP Badge",
            name="GCP Badge",
            verify_url="https://www.skills.google/public_profiles/abc/badges/123",
        )
        assert model.verification_status == VerificationStatus.VERIFIED
        assert model.evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
        assert model.verification_url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION

    def test_ms_achievement_auto_classified_unverified_and_unknown(self):
        with_url = MSAchievementModel(id="ms-1", url="learn.module-1")
        assert with_url.verification_status == VerificationStatus.UNVERIFIED
        assert with_url.evidence_level == EvidenceLevel.PLATFORM_ACTIVITY
        assert with_url.verification_url_kind == VerificationUrlKind.CATALOG_PAGE

        without_url = MSAchievementModel(id="ms-2", url=None)
        assert without_url.verification_status == VerificationStatus.UNKNOWN
        assert without_url.evidence_level == EvidenceLevel.SELF_REPORTED
        assert without_url.verification_url_kind == VerificationUrlKind.NONE

    def test_ms_verifiable_credential_retired_or_expired(self):
        retired_vc = MSVerifiableCredentialModel(
            credentialStatus="Active", retired=True
        )
        assert retired_vc.verification_status == VerificationStatus.RETIRED

        expired_vc = MSVerifiableCredentialModel(credentialStatus="Expired")
        assert expired_vc.verification_status == VerificationStatus.EXPIRED

    def test_linkedin_external_vs_learning_auto_classified(self):
        ext = LinkedInCertModel(
            name="SAP Badge",
            authority="SAP",
            url="https://badger.learning.sap.com/verify/123",
        )
        assert ext.verification_status == VerificationStatus.UNVERIFIED
        assert ext.evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
        assert ext.verification_url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION

        learning = LinkedInCertModel(
            name="Course",
            authority="LinkedIn",
            url="https://www.linkedin.com/learning/certificates/abc",
        )
        assert learning.verification_status == VerificationStatus.UNVERIFIED
        assert learning.evidence_level == EvidenceLevel.PLATFORM_ACTIVITY
        assert learning.verification_url_kind == VerificationUrlKind.CATALOG_PAGE

    def test_google_developer_codelab_and_rpc_badge(self):
        codelab = GoogleDeveloperBadgeModel(
            title="Codelab",
            description="Verified Google Developer learning activity. URL: https://codelabs.developers.google.com/foo",
            source="local_mhtml",
            url="https://codelabs.developers.google.com/foo",
        )
        assert codelab.verification_status == VerificationStatus.UNVERIFIED
        assert codelab.evidence_level == EvidenceLevel.PLATFORM_ACTIVITY
        assert codelab.verification_url_kind == VerificationUrlKind.CATALOG_PAGE

        rpc_badge = GoogleDeveloperBadgeModel(
            title="GDG Belgrade",
            description="Official Google Developer platform achievement (Community: gdg belgrade).",
            source="public_rpc",
        )
        assert rpc_badge.verification_status == VerificationStatus.UNVERIFIED
        assert rpc_badge.evidence_level == EvidenceLevel.ISSUER_PROFILE
        assert rpc_badge.verification_url_kind == VerificationUrlKind.NONE


class TestJsonLdParserFixes:
    """Tests for JSON-LD parser fixes and schema enforcement."""

    def test_deprecated_nested_brackets_url_preserved(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        (archives_dir / "google-skills-complete.md").write_text(
            "# Complete Google Skills Credentials Archive\n\n"
            "| Date Earned | Credential Name | Issuer | Verification Type |\n"
            "| :---: | :--- | :--- | :---: |\n"
            "| 2026-08-17 | [[DEPRECATED] Vibe Coding for Beginners](https://www.skills.google/public_profiles/u1/badges/26909457) | Google Cloud | Google Skill Badge |\n",
            encoding="utf-8",
        )

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            creds = parse_archive_monoliths()

        assert len(creds) == 1
        assert creds[0]["name"] == "[DEPRECATED] Vibe Coding for Beginners"
        assert (
            creds[0]["url"]
            == "https://www.skills.google/public_profiles/u1/badges/26909457"
        )
        assert (
            creds[0]["verifyUrl"]
            == "https://www.skills.google/public_profiles/u1/badges/26909457"
        )
        assert creds[0]["verificationStatus"] == "verified"
        assert creds[0]["evidenceLevel"] == "issuer_credential"
        assert creds[0]["verificationUrlKind"] == "credential_assertion"

    def test_aws_escaped_pipe_and_retired_precedence(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        (archives_dir / "aws-skills-complete.md").write_text(
            "# Complete AWS Skill Builder Archive\n\n"
            "| Date Earned | Credential Name | Issuer | Verification Type |\n"
            "| :---: | :--- | :--- | :---: |\n"
            r"| 2026-10-18 | [Build RAG \| Databases for AI](https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic) | Amazon Web Services | Digital course |"
            + "\n"
            "| 2024-05-01 | [Old Course](https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic) | Amazon Web Services | Digital course [WARN] *Content retired* |\n",
            encoding="utf-8",
        )

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            creds = parse_archive_monoliths()

        assert len(creds) == 2
        active, retired = creds[0], creds[1]

        assert active["name"] == "Build RAG | Databases for AI"
        assert (
            active["url"]
            == "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic"
        )
        assert (
            active["sourceUrl"]
            == "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic"
        )
        assert active["verifyUrl"] is None
        assert active["verificationStatus"] == "unverified"
        assert active["evidenceLevel"] == "issuer_profile"
        assert active["verificationUrlKind"] == "profile_page"

        assert retired["credentialStatus"] == "Retired"
        assert retired["verificationStatus"] == "retired"
        assert retired["verifyUrl"] is None

    def test_google_developer_plain_url_and_rpc_badge(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        (archives_dir / "google-developer-complete.md").write_text(
            "# Complete Google Developer Archive\n\n"
            "| Date Earned | Title | Description |\n"
            "| :---: | :--- | :--- |\n"
            "| 2026-11-18 | **Codelab Task** | Verified Google Developer learning activity. URL: https://codelabs.developers.google.com/task-1 |\n"
            "| 2026-06-05 | **GDG Belgrade** | Official Google Developer platform achievement (Community: gdg belgrade). |\n",
            encoding="utf-8",
        )

        with patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)):
            creds = parse_archive_monoliths()

        assert len(creds) == 2
        codelab, rpc_badge = creds[0], creds[1]

        assert codelab["url"] == "https://codelabs.developers.google.com/task-1"
        assert codelab["sourceUrl"] == "https://codelabs.developers.google.com/task-1"
        assert codelab["verifyUrl"] is None
        assert codelab["verificationStatus"] == "unverified"
        assert codelab["evidenceLevel"] == "platform_activity"
        assert codelab["verificationUrlKind"] == "catalog_page"

        assert "url" not in rpc_badge
        assert rpc_badge["sourceUrl"] is None
        assert rpc_badge["verifyUrl"] is None
        assert rpc_badge["verificationStatus"] == "unverified"
        assert rpc_badge["evidenceLevel"] == "issuer_profile"
        assert rpc_badge["verificationUrlKind"] == "none"

    def test_extract_table_data_rows_preserves_escaped_pipes(self):
        lines = [
            "| Title | Issuer |",
            "| :--- | :--- |",
            r"| Part A \| Part B | AWS |",
        ]
        rows = extract_table_data_rows(lines)
        assert len(rows) == 1
        assert rows[0][1] == [r"Part A \| Part B", "AWS"]
        assert clean_str(rows[0][1][0]) == "Part A | Part B"

    def test_jsonld_schema_rejects_invalid_evidence_level(self):
        bad_payload = {
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
                        "name": "Badge",
                        "recognizedBy": {"@type": "Organization", "name": "Credly"},
                        "evidenceLevel": "invalid_level",
                    }
                ],
            },
        }
        with pytest.raises(SystemExit) as exc_info:
            validate_jsonld(bad_payload)
        assert exc_info.value.code == 1

    def test_cross_artifact_validator_provenance_check(self):
        validator = CrossArtifactValidator(strict=True, warn_mode=False)
        counts = PlatformCounts(platform="credly")
        credentials = [
            {
                "platform": "credly",
                "sourcePlatform": "credly",
                "retrievalMethod": "api",
                "retrievedAt": "2026-11-26T00:00:00+00:00",
                "verificationStatus": "verified",
                "evidenceLevel": "issuer_credential",
                "verificationUrlKind": "credential_assertion",
                "sourceUrl": "https://www.credly.com/badges/1/public_url",
                "verifyUrl": "https://www.credly.com/badges/1/public_url",
                "lastVerifiedAt": None,
                "sourceHash": None,
                "recognizedBy": {"@type": "Organization", "name": "Credly"},
            }
        ]
        validator._validate_jsonld_provenance("credly", credentials, counts)
        assert len(validator.results) == 0
        assert counts.provenance_evidence_level == "issuer_credential"
        assert counts.provenance_verification_url_kind == "credential_assertion"
