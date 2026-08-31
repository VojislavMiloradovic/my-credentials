"""
Provenance metadata models for credential records.

Provides standardized provenance tracking across all credential platforms.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Verification status of a credential record."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    RETIRED = "retired"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class RetrievalMethod(str, Enum):
    """Method used to retrieve the credential record."""

    API = "api"
    SCRAPE = "scrape"
    EXPORT = "export"
    MANUAL = "manual"
    UNKNOWN = "unknown"


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
        default_factory=lambda: datetime.now(UTC),
        description="When this record was retrieved from the source platform",
    )
    last_verified_at: datetime | None = Field(
        None, description="When this record was last independently verified"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNKNOWN,
        description="Current verification status of the credential",
    )
    source_hash: str | None = Field(
        None,
        description="Content hash for deduplication/integrity (excludes provenance fields)",
    )
    retrieval_method: RetrievalMethod = Field(
        default=RetrievalMethod.UNKNOWN, description="How the record was retrieved"
    )

    def model_post_init(self, __context: Any) -> None:
        """Ensure timestamps are timezone-aware."""
        if self.retrieved_at.tzinfo is None:
            self.retrieved_at = self.retrieved_at.replace(tzinfo=UTC)
        if self.last_verified_at and self.last_verified_at.tzinfo is None:
            self.last_verified_at = self.last_verified_at.replace(tzinfo=UTC)

    def compute_verification_status(
        self, retired: bool = False, credential_status: str | None = None
    ) -> VerificationStatus:
        """Determine verification status from record state."""
        if retired:
            return VerificationStatus.RETIRED
        if credential_status:
            status_lower = credential_status.lower()
            if status_lower in ("expired", "revoked"):
                return VerificationStatus.EXPIRED
            if status_lower in ("active", "valid", "verified"):
                return VerificationStatus.VERIFIED
        if self.verify_url:
            return VerificationStatus.VERIFIED
        return VerificationStatus.UNKNOWN
