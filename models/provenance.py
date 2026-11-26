"""
Provenance metadata models for credential records.

Provides standardized provenance tracking across all credential platforms.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class VerificationStatus(str, Enum):
    """Verification status of a credential record."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    RETIRED = "retired"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class EvidenceLevel(str, Enum):
    """Strength and origin of evidence backing a credential record."""

    ISSUER_CREDENTIAL = "issuer_credential"
    ISSUER_PROFILE = "issuer_profile"
    PLATFORM_ACTIVITY = "platform_activity"
    SELF_REPORTED = "self_reported"


class VerificationUrlKind(str, Enum):
    """Semantic classification of the URL attached to a credential record."""

    CREDENTIAL_ASSERTION = "credential_assertion"
    PROFILE_PAGE = "profile_page"
    CATALOG_PAGE = "catalog_page"
    NONE = "none"


class RetrievalMethod(str, Enum):
    """Method used to retrieve the credential record."""

    API = "api"
    SCRAPE = "scrape"
    EXPORT = "export"
    MANUAL = "manual"
    UNKNOWN = "unknown"


_CREDENTIAL_ASSERTION_PATTERNS = (
    "credly.com/badges/",
    "badger.learning.sap.com/verify/",
    "verify.skilljar.com/",
    "credential.net/",
    "api.accredible.com/",
    "courses.cognitiveclass.ai/certificates/",
    "skillshop.exceedlms.com/student/award/",
    "courses.academy.tigera.io/certificates/",
    "learn.opswatacademy.com/certificate/",
    "learn.nvidia.com/certificates",
    "catalog-education.oracle.com/",
)


def classify_verification_url_kind(
    platform_key: str,
    url: str | None = None,
    verify_url: str | None = None,
) -> VerificationUrlKind:
    """Classify the semantic role of a credential's URL."""
    raw_url = str(verify_url or url or "").strip()
    if not raw_url or raw_url.upper() == "N/A":
        return VerificationUrlKind.NONE

    u = raw_url.lower()
    p = (platform_key or "").strip().lower()

    # 1. Explicit per-credential assertion endpoints
    if any(pattern in u for pattern in _CREDENTIAL_ASSERTION_PATTERNS):
        return VerificationUrlKind.CREDENTIAL_ASSERTION
    if ("skills.google/" in u or "cloudskillsboost.google/" in u) and "/badges/" in u:
        return VerificationUrlKind.CREDENTIAL_ASSERTION
    if "learn.microsoft.com/" in u and (
        "/api/credentials/" in u or "/credentials/" in u
    ):
        return VerificationUrlKind.CREDENTIAL_ASSERTION

    # 2. Explicit profile pages
    if "skillsprofile.skillbuilder.aws/user/" in u:
        return VerificationUrlKind.PROFILE_PAGE
    if "learn.microsoft.com/" in u and "/users/" in u:
        return VerificationUrlKind.PROFILE_PAGE
    if "g.dev/" in u or "developers.google.com/profile/" in u:
        return VerificationUrlKind.PROFILE_PAGE
    if "credly.com/users/" in u:
        return VerificationUrlKind.PROFILE_PAGE
    if "skillshop.exceedlms.com/profiles/" in u:
        return VerificationUrlKind.PROFILE_PAGE
    if (
        "skills.google/public_profiles/" in u
        or "cloudskillsboost.google/public_profiles/" in u
    ) and "/badges/" not in u:
        return VerificationUrlKind.PROFILE_PAGE

    # 3. Explicit catalog / course / activity pages
    if "learn.microsoft.com/" in u and "/training/" in u:
        return VerificationUrlKind.CATALOG_PAGE
    if p == "microsoft-learn" and u.startswith(("learn.", "/training/", "training/")):
        return VerificationUrlKind.CATALOG_PAGE
    if "linkedin.com/learning/certificates/" in u:
        return VerificationUrlKind.CATALOG_PAGE
    if any(
        domain in u
        for domain in (
            "codelabs.developers.google.com/",
            "developers.home.google.com/",
            "web.dev/",
            "developer.android.com/",
            "firebase.google.com/",
        )
    ):
        return VerificationUrlKind.CATALOG_PAGE

    # 4. Platform-level defaults for unrecognized non-empty URLs
    if p in ("credly", "google-skills"):
        return VerificationUrlKind.CREDENTIAL_ASSERTION
    if p == "aws-skills":
        return VerificationUrlKind.PROFILE_PAGE
    return VerificationUrlKind.CATALOG_PAGE


def classify_credential_evidence(
    platform_key: str,
    retrieval_method: RetrievalMethod | str | None = None,
    *,
    url: str | None = None,
    verify_url: str | None = None,
    retired: bool = False,
    credential_status: str | None = None,
) -> tuple[VerificationStatus, EvidenceLevel, VerificationUrlKind]:
    """
    Determine pragmatic VerificationStatus, EvidenceLevel, and VerificationUrlKind
    from platform origin, retrieval method, URL semantics, and retirement state.
    """
    p = (platform_key or "").strip().lower()
    method_str = (
        retrieval_method.value
        if isinstance(retrieval_method, RetrievalMethod)
        else str(retrieval_method or "unknown").strip().lower()
    )
    raw_url = str(verify_url or url or "").strip()
    u = raw_url.lower()

    url_kind = classify_verification_url_kind(p, url=url, verify_url=verify_url)

    # Determine evidence level
    if url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION:
        evidence_level = EvidenceLevel.ISSUER_CREDENTIAL
    elif url_kind == VerificationUrlKind.PROFILE_PAGE:
        evidence_level = EvidenceLevel.ISSUER_PROFILE
    elif url_kind == VerificationUrlKind.CATALOG_PAGE:
        if (
            p == "linkedin-certifications"
            and "linkedin.com/learning/certificates/" not in u
        ):
            evidence_level = EvidenceLevel.SELF_REPORTED
        else:
            evidence_level = EvidenceLevel.PLATFORM_ACTIVITY
    else:
        # VerificationUrlKind.NONE
        if p == "google-developer":
            evidence_level = EvidenceLevel.ISSUER_PROFILE
        else:
            evidence_level = EvidenceLevel.SELF_REPORTED

    # Determine pragmatic verificationStatus
    if retired:
        status = VerificationStatus.RETIRED
    elif credential_status and credential_status.strip().lower() in (
        "expired",
        "revoked",
    ):
        status = VerificationStatus.EXPIRED
    elif (
        evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
        and url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION
        and method_str in ("api", "scrape")
    ):
        status = VerificationStatus.VERIFIED
    elif (
        url_kind != VerificationUrlKind.NONE
        or evidence_level != EvidenceLevel.SELF_REPORTED
    ):
        status = VerificationStatus.UNVERIFIED
    else:
        status = VerificationStatus.UNKNOWN

    return status, evidence_level, url_kind


class ProvenanceBase(BaseModel):
    """
    Standard provenance metadata for all credential records.

    Tracks the origin, retrieval, and verification history of a credential record
    to ensure auditability and enable staleness detection.
    """

    source_platform: str = Field(
        ...,
        description="Platform identifier (e.g., 'google-developer', 'microsoft-learn')",
    )
    source_record_id: str | None = Field(
        None,
        description="Stable ID from source platform (e.g., badge ID, achievement ID)",
    )
    source_url: str | None = Field(None, description="Canonical URL on source platform")
    verify_url: str | None = Field(None, description="Independent verification URL")
    retrieved_at: datetime = Field(
        ...,
        description="When this record was retrieved from the source platform (no default - must be set by pipeline at fetch time)",
    )
    last_verified_at: datetime | None = Field(
        None, description="When this record was last independently verified"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNKNOWN,
        description="Current verification status of the credential",
    )
    evidence_level: EvidenceLevel = Field(
        default=EvidenceLevel.SELF_REPORTED,
        description="Strength/origin of evidence backing the credential",
    )
    verification_url_kind: VerificationUrlKind = Field(
        default=VerificationUrlKind.NONE,
        description="Semantic kind of the attached URL",
    )
    source_hash: str | None = Field(
        None,
        description="Content hash for deduplication/integrity (excludes provenance fields)",
    )
    retrieval_method: RetrievalMethod = Field(
        default=RetrievalMethod.UNKNOWN, description="How the record was retrieved"
    )
    # Retirement metadata fields
    retirement_source: str | None = Field(
        None,
        description="Source of retirement information (e.g., 'source_csv', 'registry', 'auto')",
    )
    retirement_reason: str | None = Field(
        None,
        description="Reason for retirement (e.g., 'Source CSV Status=Retired', 'Registry-matched', 'Auto-detected')",
    )
    retired_at: str | None = Field(
        None,
        description="Date when the credential was retired (ISO format YYYY-MM-DD)",
    )

    def model_post_init(self, __context: Any, /) -> None:
        """Ensure timestamps are timezone-aware."""
        if self.retrieved_at.tzinfo is None:
            self.retrieved_at = self.retrieved_at.replace(tzinfo=UTC)
        if self.last_verified_at and self.last_verified_at.tzinfo is None:
            self.last_verified_at = self.last_verified_at.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def _auto_classify_provenance(self) -> "ProvenanceBase":
        """Auto-populate verification_status, evidence_level, and verification_url_kind when omitted."""
        url_val = getattr(self, "url", None) or self.source_url
        verify_url_val = self.verify_url
        retired_val = bool(getattr(self, "retired", False))
        cred_status_val = getattr(self, "credentialStatus", None)

        status, evidence_level, url_kind = classify_credential_evidence(
            self.source_platform,
            self.retrieval_method,
            url=url_val,
            verify_url=verify_url_val,
            retired=retired_val,
            credential_status=cred_status_val,
        )

        if "evidence_level" not in self.model_fields_set:
            self.evidence_level = evidence_level
        if "verification_url_kind" not in self.model_fields_set:
            self.verification_url_kind = url_kind
        if "verification_status" not in self.model_fields_set:
            self.verification_status = status

        return self

    def compute_verification_status(
        self, retired: bool = False, credential_status: str | None = None
    ) -> VerificationStatus:
        """Determine verification status from record state."""
        url_val = getattr(self, "url", None) or self.source_url
        status, _, _ = classify_credential_evidence(
            self.source_platform,
            self.retrieval_method,
            url=url_val,
            verify_url=self.verify_url,
            retired=retired,
            credential_status=credential_status,
        )
        return status
