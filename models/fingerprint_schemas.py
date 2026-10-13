"""
Provider-specific fingerprint schemas for content loss guard.

Each schema declares the fields that constitute the semantic identity of a credential
for a given platform. These fields are hashed to detect content changes while
excluding volatile metadata (retrieval timestamps, provenance, etc.).

Schema version is tracked in baseline files to enable safe migration.
"""

from typing import Any

# Current fingerprint schema version. Increment when any schema changes.
CURRENT_FINGERPRINT_SCHEMA_VERSION = 2

# Type alias for schema definition
FingerprintSchema = dict[str, Any]

# Per-platform fingerprint schemas
# Each schema specifies:
#   - fields: list of field names to include in the content hash
#   - canonical_issuer: optional fixed issuer name for platforms without issuer field
#   - id_field: the field used as stable record ID (or "id_strategy" for custom)
FINGERPRINT_SCHEMAS: dict[str, FingerprintSchema] = {
    "microsoft-learn": {
        "fields": [
            "title",
            "grantedOn",
            "category",
            "verify_url",
            "retired",
        ],
        "canonical_issuer": "Microsoft",
        "id_field": "id",
    },
    "credly": {
        "fields": [
            "title",
            "date",
            "issuer_name",
            "type",
            "verify_url",
            "retired",
        ],
        "id_field": "id",
    },
    "aws-skills": {
        "fields": [
            "title",
            "date",
            "issuer_name",
            "type",
            "verify_url",
            "retired",
        ],
        "id_field": "id",
    },
    "google-skills": {
        "fields": [
            "title",
            "date",
            "issuer_name",
            "type",
            "verify_url",
            "retired",
        ],
        "id_field": "id",
    },
    "linkedin-certifications": {
        "fields": [
            "title",
            "issued",
            "authority",
            "verify_url",
            "retired",
        ],
        "id_field": "license",
    },
    "google-developer": {
        "fields": [
            "title",
            "description",
            "source",
            "retired",
        ],
        "canonical_issuer": "Google",
        "id_strategy": "title_date_hash",
    },
}


def get_schema(platform: str) -> FingerprintSchema | None:
    """
    Get fingerprint schema for a platform.

    Args:
        platform: Platform identifier (e.g., "microsoft-learn")

    Returns:
        Schema dict or None if platform not configured
    """
    return FINGERPRINT_SCHEMAS.get(platform)


def get_canonical_issuer(platform: str) -> str | None:
    """
    Get canonical issuer name for a platform.

    Args:
        platform: Platform identifier

    Returns:
        Canonical issuer string or None if not defined
    """
    schema = FINGERPRINT_SCHEMAS.get(platform)
    if schema:
        return schema.get("canonical_issuer")
    return None


def get_id_field(platform: str) -> str | None:
    """
    Get the ID field name for a platform.

    Args:
        platform: Platform identifier

    Returns:
        ID field name or None if custom strategy used
    """
    schema = FINGERPRINT_SCHEMAS.get(platform)
    if schema:
        return schema.get("id_field")
    return None


def get_id_strategy(platform: str) -> str | None:
    """
    Get custom ID strategy for a platform.

    Args:
        platform: Platform identifier

    Returns:
        Strategy name or None if standard id_field used
    """
    schema = FINGERPRINT_SCHEMAS.get(platform)
    if schema:
        return schema.get("id_strategy")
    return None
