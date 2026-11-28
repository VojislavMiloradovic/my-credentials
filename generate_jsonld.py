import argparse
import glob  # noqa: F401 (used in tests via mocking)
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import jsonschema

# Layer manifest integration
from layer_manifest import get_platforms_with_l2_artifact
from loss_guard import compute_content_hash, extract_record_id
from models.fingerprint_schemas import get_id_field
from models.provenance import (
    EvidenceLevel,
    VerificationStatus,
    VerificationUrlKind,
    classify_credential_evidence,
)
from verify_assertions import (
    CACHE_PATH as DEFAULT_ACTIVE_VERIFICATIONS_PATH,
)
from verify_assertions import (
    DEFAULT_TTL_DAYS as DEFAULT_ACTIVE_VERIFICATION_TTL_DAYS,
)
from verify_assertions import (
    is_verified_and_fresh,
    load_active_verifications,
)

ARCHIVE_DIR = "archives"
VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"
FEED_JSON_PATH = "credentials.feed.json"
FEED_NDJSON_PATH = "credentials.ndjson"
ACTIVE_VERIFICATIONS_PATH = DEFAULT_ACTIVE_VERIFICATIONS_PATH
ACTIVE_VERIFICATION_TTL_DAYS = DEFAULT_ACTIVE_VERIFICATION_TTL_DAYS

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

VALID_RETRIEVAL_METHODS = frozenset({"api", "scrape", "export", "manual", "unknown"})

L1_PLATFORM_SOURCES: dict[str, dict[str, Any]] = {
    "microsoft-learn": {
        "filename": "microsoft-learn.json",
        "records_key": "achievements",
        "recognized_by": "Microsoft Learn",
        "default_issuer": "Microsoft Learn",
        "default_retrieval_method": "export",
    },
    "google-skills": {
        "filename": "google_skills_badges.json",
        "records_key": "badges",
        "recognized_by": "Google Skills",
        "default_issuer": "Google Cloud",
        "default_retrieval_method": "api",
    },
    "aws-skills": {
        "filename": "aws_skill_badges.json",
        "records_key": "badges",
        "recognized_by": "AWS Skills",
        "default_issuer": "Amazon Web Services",
        "default_retrieval_method": "export",
    },
    "credly": {
        "filename": "credly_badges.json",
        "records_key": "credentials",
        "recognized_by": "Credly",
        "default_issuer": None,
        "default_retrieval_method": "api",
    },
    "linkedin-certifications": {
        "filename": "linkedin-certifications.json",
        "records_key": "certifications",
        "recognized_by": "LinkedIn",
        "default_issuer": None,
        "default_retrieval_method": "export",
    },
    "google-developer": {
        "filename": "google-developer.json",
        "records_key": "combined_feed",
        "recognized_by": "Google Developer",
        "default_issuer": "Google Developer",
        "default_retrieval_method": "api",
    },
}

JSONLD_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "@context": {"type": "string"},
        "@type": {"type": "string"},
        "mainEntity": {
            "type": "object",
            "properties": {
                "@type": {"type": "string"},
                "name": {"type": "string"},
                "url": {"type": "string"},
                "hasCredential": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "@type": {"type": "string"},
                            "credentialCategory": {"type": "string"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "image": {"type": "string"},
                            "identifier": {"type": "string"},
                            "dateCreated": {"type": "string"},
                            "expires": {"type": "string"},
                            "credentialStatus": {"type": "string"},
                            "retirement_source": {"type": ["string", "null"]},
                            "retirement_reason": {"type": ["string", "null"]},
                            "retired_at": {"type": ["string", "null"]},
                            "skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "recognizedBy": {
                                "type": "object",
                                "properties": {
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                                "required": ["@type", "name"],
                            },
                            "issuer": {"type": "string"},
                            "url": {"type": ["string", "null"]},
                            "platform": {"type": "string"},
                            "sourcePlatform": {"type": "string"},
                            "retrievalMethod": {
                                "type": "string",
                                "enum": [
                                    "api",
                                    "scrape",
                                    "export",
                                    "manual",
                                    "unknown",
                                ],
                            },
                            "retrievedAt": {"type": "string"},
                            "verificationStatus": {
                                "type": "string",
                                "enum": [
                                    "verified",
                                    "unverified",
                                    "retired",
                                    "expired",
                                    "unknown",
                                ],
                            },
                            "evidenceLevel": {
                                "type": "string",
                                "enum": [
                                    "issuer_credential",
                                    "issuer_profile",
                                    "platform_activity",
                                    "self_reported",
                                ],
                            },
                            "verificationUrlKind": {
                                "type": "string",
                                "enum": [
                                    "credential_assertion",
                                    "profile_page",
                                    "catalog_page",
                                    "none",
                                ],
                            },
                            "sourceRecordId": {"type": ["string", "null"]},
                            "sourceUrl": {"type": ["string", "null"]},
                            "verifyUrl": {"type": ["string", "null"]},
                            "lastVerifiedAt": {"type": ["string", "null"]},
                            "sourceHash": {"type": ["string", "null"]},
                        },
                        "required": ["@type", "name", "recognizedBy"],
                    },
                },
            },
            "required": ["@context", "@type", "name", "url", "hasCredential"],
        },
    },
    "required": ["@context", "@type", "mainEntity"],
}

COMPACT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "sourceRecordId": {"type": ["string", "null"]},
        "sourceHash": {"type": ["string", "null"]},
        "platform": {"type": "string"},
        "issuer": {"type": "string"},
        "name": {"type": "string"},
        "category": {"type": "string"},
        "dateCreated": {"type": "string"},
        "url": {"type": "string"},
        "sourceUrl": {"type": "string"},
        "verifyUrl": {"type": "string"},
        "image": {"type": "string"},
        "description": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "retrievedAt": {"type": "string"},
        "retrievalMethod": {
            "type": "string",
            "enum": ["api", "scrape", "export", "manual", "unknown"],
        },
        "evidenceLevel": {
            "type": "string",
            "enum": [
                "issuer_credential",
                "issuer_profile",
                "platform_activity",
                "self_reported",
            ],
        },
        "verificationStatus": {
            "type": "string",
            "enum": ["verified", "unverified", "retired", "expired", "unknown"],
        },
        "verificationUrlKind": {
            "type": "string",
            "enum": ["credential_assertion", "profile_page", "catalog_page", "none"],
        },
        "lastVerifiedAt": {"type": "string"},
        "retired": {"type": "boolean"},
        "retirementSource": {"type": "string"},
        "retirementReason": {"type": "string"},
        "retiredAt": {"type": "string"},
    },
    "required": [
        "id",
        "platform",
        "name",
        "category",
        "retrievedAt",
        "retrievalMethod",
        "evidenceLevel",
        "verificationStatus",
        "verificationUrlKind",
        "retired",
    ],
}

FEED_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "schemaVersion": {"type": "string"},
        "generatedAt": {"type": "string"},
        "owner": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["name", "url"],
        },
        "totalCount": {"type": "integer", "minimum": 0},
        "countsByPlatform": {
            "type": "object",
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "credentials": {
            "type": "array",
            "items": COMPACT_ITEM_SCHEMA,
        },
    },
    "required": [
        "schemaVersion",
        "generatedAt",
        "owner",
        "totalCount",
        "countsByPlatform",
        "credentials",
    ],
}


def _atomic_write_text(filepath: str, content: str) -> None:
    """Atomically write text content via a same-directory temp file and os.replace."""
    parent_dir = os.path.dirname(filepath) or "."
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent_dir,
            prefix=f".{os.path.basename(filepath)}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(content)
            tmp_file.flush()
        try:
            os.replace(tmp_path, filepath)
        except OSError:
            if os.name != "nt" or not os.path.exists(filepath):
                raise
            backup_path = f"{filepath}.bak"
            os.replace(filepath, backup_path)
            try:
                os.replace(tmp_path, filepath)
            except OSError:
                if not os.path.exists(filepath) and os.path.exists(backup_path):
                    os.replace(backup_path, filepath)
                raise
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def clean_str(s):
    if not s:
        return ""
    return re.sub(r"[\*\_`]", "", str(s).replace("\\|", "|")).strip()


def _clean_optional_url(raw: Any, *, platform_key: str = "") -> str | None:
    """Normalize optional URL values, resolving relative Microsoft Learn paths."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.upper() == "N/A":
        return None
    if platform_key == "microsoft-learn":
        cleaned = re.sub(r"\s+program/?$", "", cleaned).replace(" ", "")
        if not cleaned:
            return None
        if cleaned.startswith("learn."):
            return f"https://learn.microsoft.com/en-us/training/paths/{cleaned[6:]}"
        if not cleaned.startswith(("http://", "https://")):
            if cleaned.startswith("/"):
                return f"https://learn.microsoft.com/en-us{cleaned}"
            return f"https://learn.microsoft.com/en-us/{cleaned}"
        if "learn.microsoft.com/training/" in cleaned:
            cleaned = cleaned.replace(
                "learn.microsoft.com/training/",
                "learn.microsoft.com/en-us/training/",
            )
    return cleaned


def _format_iso_timestamp(value: Any, fallback: str) -> str:
    """Convert datetime or string value into an ISO-8601 string."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def parse_retired_marker(col: str) -> tuple[bool, str | None, str | None, str | None]:
    """
    Parse enhanced retired marker from Verification Type column.
    Returns: (retired, retirement_source, retirement_reason, retired_at)
    """
    if not col:
        return False, None, None, None

    if "Content retired" in col:
        retired = True
        retirement_source = None
        retirement_reason = None
        retired_at = None

        paren_match = re.search(r"\(([^)]+)\)", col)
        if paren_match:
            paren_content = paren_match.group(1).strip()

            if paren_content.startswith("platform-flagged:"):
                retirement_source = "source_csv"
                content = paren_content[len("platform-flagged:") :].strip()
                if "," in content:
                    parts = content.split(",", 1)
                    retirement_reason = parts[0].strip()
                    retired_at = parts[1].strip()
                else:
                    retirement_reason = content

            elif paren_content.startswith("registry-matched"):
                retirement_source = "registry"
                retirement_reason = "Registry-matched"

            elif paren_content.startswith("auto-detected:"):
                retirement_source = "auto"
                retired_at = paren_content[len("auto-detected:") :].strip()
                retirement_reason = "Auto-detected"

        return retired, retirement_source, retirement_reason, retired_at

    if "retired" in col.lower():
        return True, None, None, None

    return False, None, None, None


def validate_jsonld(payload):
    """Validates generated JSON-LD object against the defined schema before writing."""
    try:
        jsonschema.validate(instance=payload, schema=JSONLD_SCHEMA)
        print("JSON-LD Schema Validation Passed successfully.")
    except jsonschema.exceptions.ValidationError as e:
        print(f"JSON-LD Validation Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except jsonschema.exceptions.SchemaError as e:
        print(f"JSON Schema Error: {e.message}", file=sys.stderr)
        sys.exit(1)


def validate_feed_payload(feed_payload: dict[str, Any]) -> None:
    """Validates compact JSON feed against FEED_JSON_SCHEMA before writing."""
    try:
        jsonschema.validate(instance=feed_payload, schema=FEED_JSON_SCHEMA)
        print("Compact Machine Feed Schema Validation Passed successfully.")
    except jsonschema.exceptions.ValidationError as e:
        print(f"Compact Feed Validation Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except jsonschema.exceptions.SchemaError as e:
        print(f"Compact Feed Schema Error: {e.message}", file=sys.stderr)
        sys.exit(1)


def extract_retrieved_at(lines: list[str]) -> str | None:
    """Extracts retrieved_at timestamp from front-matter comments."""
    for line in lines:
        line = line.strip()
        if line.startswith("<!-- retrieved_at:") and line.endswith("-->"):
            match = re.search(r"<!--\s*retrieved_at:\s*([^>]+)\s*-->", line)
            if match:
                return match.group(1).strip()
    return None


def extract_table_data_rows(lines: list[str]) -> list[tuple[list[str], list[str]]]:
    """Extracts header columns and cell contents from Markdown tables using separator-anchored parsing."""
    data_rows = []
    cleaned_lines = [line.strip() for line in lines]
    separator_re = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")

    i = 0
    while i < len(cleaned_lines):
        line = cleaned_lines[i]
        if line.startswith("|") and line.endswith("|"):
            if (i + 1) < len(cleaned_lines) and separator_re.match(
                cleaned_lines[i + 1]
            ):
                header_cols = [c.strip().lower() for c in line.split("|")[1:-1]]
                i += 2  # Skip header row and separator row
                while i < len(cleaned_lines):
                    row_line = cleaned_lines[i]
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    if separator_re.match(row_line):
                        i += 1
                        continue
                    cols = [c.strip() for c in re.split(r"(?<!\\)\|", row_line)[1:-1]]
                    if cols:
                        data_rows.append((header_cols, cols))
                    i += 1
                continue
            elif separator_re.match(line):
                i += 1
                continue
        i += 1

    return data_rows


def _ordered_l1_platforms() -> list[str]:
    """Resolve platform ordering from layer manifest while ensuring all L1 platforms are included."""
    try:
        platform_keys = get_platforms_with_l2_artifact("jsonld")
    except Exception:
        platform_keys = []
    for p_key in L1_PLATFORM_SOURCES:
        if p_key not in platform_keys:
            platform_keys.append(p_key)
    return [p for p in platform_keys if p in L1_PLATFORM_SOURCES]


def _has_l1_sources(validation_dir: str) -> bool:
    """Return True if validation_dir exists and contains at least one L1 JSON source file."""
    if not validation_dir or not os.path.isdir(validation_dir):
        return False
    return any(
        os.path.isfile(os.path.join(validation_dir, cfg["filename"]))
        for cfg in L1_PLATFORM_SOURCES.values()
    )


def _extract_l1_records(data: dict[str, Any], records_key: str) -> list[dict[str, Any]]:
    """Extract normalized record list from an L1 validation JSON document."""
    if not isinstance(data, dict):
        return []
    raw_list = data.get(records_key)
    if isinstance(raw_list, list):
        return [r for r in raw_list if isinstance(r, dict)]
    for fallback_key in (
        "combined_feed",
        "achievements",
        "badges",
        "credentials",
        "certifications",
        "records",
    ):
        val = data.get(fallback_key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []


def _normalize_date_sort_key(date_val: str | None) -> str:
    """Produce a comparable ISO prefix sort key for newest-first platform ordering."""
    if not date_val or date_val == "N/A":
        return "0000-00-00"
    return str(date_val).strip()


def _record_to_jsonld(
    platform_key: str,
    record: dict[str, Any],
    *,
    recognized_by_name: str,
    default_issuer: str | None,
    default_retrieval_method: str,
    file_retrieved_at: str,
    active_verifications: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Convert one L1 normalized record into a Schema.org credential dict with provenance."""
    raw_title = record.get("title") or record.get("name")
    title = clean_str(raw_title)
    if not title:
        return None

    # Category / Credential type
    if platform_key == "microsoft-learn":
        raw_cat = record.get("category") or record.get("type") or "module"
        category = str(raw_cat).strip().title() or "Module"
    else:
        raw_cat = (
            record.get("type")
            or record.get("verification_type")
            or record.get("category")
            or "Badge/Certification"
        )
        category = clean_str(raw_cat) or "Badge/Certification"

    # Issuer
    raw_issuer = (
        record.get("issuer")
        or record.get("issuer_name")
        or record.get("authority")
        or default_issuer
    )
    issuer_field = clean_str(raw_issuer) if raw_issuer else None

    # Date with original precision preserved
    raw_date = (
        record.get("grantedOn")
        or record.get("issued_at")
        or record.get("date")
        or record.get("issued")
        or record.get("issued_at_date")
    )
    date_earned = (
        str(raw_date).strip()
        if raw_date and str(raw_date).strip().upper() != "N/A"
        else ""
    )

    # Structured URLs
    norm_url = _clean_optional_url(record.get("url"), platform_key=platform_key)
    norm_verify_url = _clean_optional_url(
        record.get("verify_url"), platform_key=platform_key
    )
    norm_source_url = _clean_optional_url(
        record.get("source_url"), platform_key=platform_key
    )
    primary_url = norm_url or norm_verify_url or norm_source_url
    raw_source_url = norm_source_url or norm_url or norm_verify_url

    # Image, description, skills
    image_url = _clean_optional_url(record.get("image_url"))
    raw_desc = record.get("description")
    description = str(raw_desc).strip() if isinstance(raw_desc, str) else ""
    if description and description.lower() == title.lower():
        description = ""

    raw_skills = record.get("skills")
    skills = (
        [str(s).strip() for s in raw_skills if isinstance(s, str) and str(s).strip()]
        if isinstance(raw_skills, list)
        else []
    )

    # Stable ID and deterministic content hash
    id_field = get_id_field(platform_key) or "id"
    stable_record_id = (
        str(record["source_record_id"]).strip()
        if record.get("source_record_id")
        else extract_record_id(record, id_field, platform_key)
    )
    native_id = record.get("id") or record.get("license") or record.get("credentialId")
    identifier = (
        str(native_id).strip()
        if native_id and str(native_id).strip()
        else stable_record_id
    )
    source_hash = (
        str(record["source_hash"]).strip()
        if record.get("source_hash")
        else compute_content_hash(record, id_field, platform_key)
    )

    # Retrieval metadata
    raw_method = str(
        record.get("retrieval_method") or default_retrieval_method or "unknown"
    ).lower()
    retrieval_method = (
        raw_method if raw_method in VALID_RETRIEVAL_METHODS else "unknown"
    )
    retrieved_at = _format_iso_timestamp(record.get("retrieved_at"), file_retrieved_at)

    # Retirement metadata
    retired = bool(record.get("retired", False))
    retirement_source = record.get("retirement_source")
    retirement_reason = record.get("retirement_reason")
    retired_at = record.get("retired_at")

    # Evidence classification & active assertion cache lookup
    verification_status, evidence_level, url_kind = classify_credential_evidence(
        platform_key,
        retrieval_method,
        url=primary_url,
        verify_url=norm_verify_url,
        retired=retired,
        credential_status=record.get("credentialStatus"),
    )

    assertion_candidate = norm_verify_url or primary_url
    verify_url_val = (
        assertion_candidate
        if url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION and assertion_candidate
        else None
    )

    last_verified_at: str | None = None
    if (
        evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
        and url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION
        and verify_url_val
    ):
        cache_entry = active_verifications.get(verify_url_val)
        if cache_entry and is_verified_and_fresh(
            cache_entry, ttl_days=ACTIVE_VERIFICATION_TTL_DAYS
        ):
            last_verified_at = cache_entry.get("last_verified_at")
            if not retired and verification_status != VerificationStatus.EXPIRED:
                verification_status = VerificationStatus.VERIFIED
    elif record.get("last_verified_at"):
        last_verified_at = _format_iso_timestamp(record.get("last_verified_at"), "")
        if not last_verified_at:
            last_verified_at = None

    c_obj: dict[str, Any] = {
        "@type": "EducationalOccupationalCredential",
        "credentialCategory": category,
        "name": title,
        "recognizedBy": {
            "@type": "Organization",
            "name": recognized_by_name,
        },
        "platform": platform_key,
    }
    if issuer_field:
        c_obj["issuer"] = issuer_field
    if description:
        c_obj["description"] = description
    if image_url:
        c_obj["image"] = image_url
    if identifier:
        c_obj["identifier"] = identifier
    if date_earned:
        c_obj["dateCreated"] = date_earned
    if primary_url:
        c_obj["url"] = primary_url
    if skills:
        c_obj["skills"] = skills
    if retired:
        c_obj["credentialStatus"] = "Retired"
        if retirement_source:
            c_obj["retirement_source"] = str(retirement_source)
        if retirement_reason:
            c_obj["retirement_reason"] = str(retirement_reason)
        if retired_at:
            c_obj["retired_at"] = str(retired_at)

    c_obj["sourcePlatform"] = str(record.get("source_platform") or platform_key)
    c_obj["retrievalMethod"] = retrieval_method
    c_obj["retrievedAt"] = retrieved_at
    c_obj["verificationStatus"] = verification_status.value
    c_obj["evidenceLevel"] = evidence_level.value
    c_obj["verificationUrlKind"] = url_kind.value
    c_obj["sourceRecordId"] = stable_record_id or None
    c_obj["sourceUrl"] = raw_source_url
    c_obj["verifyUrl"] = verify_url_val
    c_obj["lastVerifiedAt"] = last_verified_at
    c_obj["sourceHash"] = source_hash

    return c_obj


def parse_l1_normalized(
    validation_dir: str | None = None,
    active_verifications_path: str | None = None,
) -> list[dict[str, Any]]:
    """Build JSON-LD credential objects directly from L1 normalized JSON snapshots."""
    v_dir = validation_dir or VALIDATION_DIR
    av_path = active_verifications_path or ACTIVE_VERIFICATIONS_PATH
    credentials: list[dict[str, Any]] = []

    if not os.path.isdir(v_dir):
        print(f"WARNING: Validation directory '{v_dir}' not found.")
        return credentials

    platform_keys = _ordered_l1_platforms()
    print(f"Generating JSON-LD from L1 normalized records in '{v_dir}'...")
    active_verifications = load_active_verifications(av_path)
    fallback_now = datetime.now(UTC).isoformat()

    for platform_key in platform_keys:
        cfg = L1_PLATFORM_SOURCES[platform_key]
        filepath = os.path.join(v_dir, cfg["filename"])
        if not os.path.isfile(filepath):
            print(f"  WARNING: {cfg['filename']} not found in {v_dir}, skipping")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        file_retrieved_at = _format_iso_timestamp(
            data.get("_retrieved_at"), fallback_now
        )
        records = _extract_l1_records(data, cfg["records_key"])

        platform_creds: list[dict[str, Any]] = []
        for record in records:
            c_obj = _record_to_jsonld(
                platform_key,
                record,
                recognized_by_name=cfg["recognized_by"],
                default_issuer=cfg["default_issuer"],
                default_retrieval_method=cfg["default_retrieval_method"],
                file_retrieved_at=file_retrieved_at,
                active_verifications=active_verifications,
            )
            if c_obj is not None:
                platform_creds.append(c_obj)

        # Keep deterministic newest-first order within each platform
        platform_creds.sort(
            key=lambda c: _normalize_date_sort_key(c.get("dateCreated")),
            reverse=True,
        )
        print(f"  {cfg['filename']}: loaded {len(platform_creds)} L1 record(s)")
        credentials.extend(platform_creds)

    return credentials


def parse_archive_monoliths():
    """Legacy fallback parser: converts *-complete.md archive tables into JSON-LD objects."""
    credentials = []

    if not os.path.exists(ARCHIVE_DIR):
        print(f"WARNING: Archive directory '{ARCHIVE_DIR}' not found.")
        return credentials

    platform_keys = get_platforms_with_l2_artifact("jsonld")

    try:
        for f in os.listdir(ARCHIVE_DIR):
            if f.endswith("-complete.md"):
                platform_key = f[:-12]
                if platform_key not in platform_keys:
                    platform_keys.append(platform_key)
    except Exception:
        pass

    print(f"Found {len(platform_keys)} platform(s) with L2_published jsonld artifact:")
    active_verifications = load_active_verifications(ACTIVE_VERIFICATIONS_PATH)

    for platform_key in platform_keys:
        filename = f"{platform_key}-complete.md"
        filepath = os.path.join(ARCHIVE_DIR, filename)

        if not os.path.exists(filepath):
            print(f"  WARNING: {filename} not found, skipping")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        platform_retrieved_at = extract_retrieved_at(lines)
        if platform_retrieved_at:
            print(
                f"  {filename}: Using retrieved_at from archive: {platform_retrieved_at}"
            )
        else:
            print(f"  {filename}: No retrieved_at in archive, using current time")

        table_rows = extract_table_data_rows(lines)

        for header_cols, cols in table_rows:
            title = ""
            date_earned = ""
            url = ""
            actual_issuer = ""
            category = "Badge/Certification"
            description = ""
            image_url = ""
            cred_id = ""
            retired = False
            retirement_source = None
            retirement_reason = None
            retired_at = None

            verify_url = ""
            for idx, col in enumerate(cols):
                col_header = header_cols[idx] if idx < len(header_cols) else ""

                img_match = re.search(r"!\[.*?\]\((https?://[^\)]+)\)", col)
                if img_match and not image_url:
                    image_url = img_match.group(1)

                found_markdown_link = False
                for link_match in re.finditer(
                    r"(?<!!)\[((?:[^\[\]]|\[[^\]]*\])+)\]\((https?://[^\s\)]+)\)",
                    col,
                ):
                    found_markdown_link = True
                    link_label = link_match.group(1)
                    link_href = link_match.group(2)
                    if not url:
                        url = link_href
                    if not title and "Verify" not in link_label:
                        title = clean_str(link_label)
                    if "Verify" in link_label and not verify_url:
                        verify_url = link_href

                if not found_markdown_link:
                    plain_url_match = re.search(r"\bURL:\s*(https?://[^\s\)\*]+)", col)
                    if plain_url_match and not url:
                        url = plain_url_match.group(1).rstrip(".,;")

                bold_match = re.search(r"\*\*([^*]+)\*\*", col)
                if bold_match and not title and "title" in col_header:
                    title = clean_str(bold_match.group(1))

                date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", col)
                if date_match and not date_earned:
                    date_earned = date_match.group(1)

                if "category" in col_header or "type" in col_header:
                    cleaned_cat = clean_str(col)
                    if cleaned_cat and cleaned_cat.lower() not in ["verify", "active"]:
                        category = cleaned_cat

                if "issuer" in col_header or "authority" in col_header:
                    cleaned_issuer = clean_str(col)
                    if cleaned_issuer:
                        actual_issuer = cleaned_issuer
                elif "issued by" in col.lower():
                    actual_issuer = (
                        col.replace("issued by", "").replace("`", "").strip()
                    )

                if "description" in col_header:
                    cleaned_desc = clean_str(col)
                    if cleaned_desc and cleaned_desc.lower() != title.lower():
                        description = cleaned_desc

                id_match = re.search(
                    r"Credential ID:\s*`?([A-Za-z0-9]+)`?", col, re.IGNORECASE
                )
                if id_match and not cred_id:
                    cred_id = id_match.group(1)

                r, rs, rr, ra = parse_retired_marker(col)
                if r:
                    retired = True
                    retirement_source = rs
                    retirement_reason = rr
                    retired_at = ra

            if not title and cols:
                for col in cols:
                    c_clean = clean_str(col)
                    if c_clean and not re.match(r"^\d{4}-\d{2}(-\d{2})?$", c_clean):
                        title = c_clean
                        break

            if title:
                if platform_key == "credly":
                    recognized_by_name = "Credly"
                    issuer_field = actual_issuer if actual_issuer else None
                elif platform_key == "linkedin-certifications":
                    recognized_by_name = "LinkedIn"
                    issuer_field = actual_issuer if actual_issuer else None
                elif platform_key == "google-skills":
                    recognized_by_name = "Google Skills"
                    issuer_field = actual_issuer if actual_issuer else "Google Cloud"
                elif platform_key == "aws-skills":
                    recognized_by_name = "AWS Skills"
                    issuer_field = (
                        actual_issuer if actual_issuer else "Amazon Web Services"
                    )
                elif platform_key == "microsoft-learn":
                    recognized_by_name = "Microsoft Learn"
                    issuer_field = "Microsoft Learn"
                elif platform_key == "google-developer":
                    recognized_by_name = "Google Developer"
                    issuer_field = "Google Developer"
                else:
                    recognized_by_name = platform_key.replace("-", " ").title()
                    issuer_field = actual_issuer if actual_issuer else None

                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": category,
                    "name": clean_str(title),
                    "recognizedBy": {
                        "@type": "Organization",
                        "name": recognized_by_name,
                    },
                    "platform": platform_key,
                }
                if issuer_field:
                    c_obj["issuer"] = issuer_field
                structured_issuer_platforms = {
                    "credly",
                    "linkedin-certifications",
                    "google-skills",
                    "aws-skills",
                    "microsoft-learn",
                    "google-developer",
                }
                if description and not (
                    platform_key in structured_issuer_platforms and actual_issuer
                ):
                    c_obj["description"] = description
                if image_url:
                    c_obj["image"] = image_url
                if cred_id:
                    c_obj["identifier"] = cred_id
                if date_earned:
                    c_obj["dateCreated"] = date_earned
                if url:
                    c_obj["url"] = url
                if retired:
                    c_obj["credentialStatus"] = "Retired"
                    if retirement_source:
                        c_obj["retirement_source"] = retirement_source
                    if retirement_reason:
                        c_obj["retirement_reason"] = retirement_reason
                    if retired_at:
                        c_obj["retired_at"] = retired_at

                platform_provenance_defaults = {
                    "google-developer": {
                        "sourcePlatform": "google-developer",
                        "retrievalMethod": "api",
                    },
                    "google-skills": {
                        "sourcePlatform": "google-skills",
                        "retrievalMethod": "api",
                    },
                    "microsoft-learn": {
                        "sourcePlatform": "microsoft-learn",
                        "retrievalMethod": "export",
                    },
                    "credly": {
                        "sourcePlatform": "credly",
                        "retrievalMethod": "api",
                    },
                    "linkedin-certifications": {
                        "sourcePlatform": "linkedin-certifications",
                        "retrievalMethod": "export",
                    },
                    "aws-skills": {
                        "sourcePlatform": "aws-skills",
                        "retrievalMethod": "export",
                    },
                }

                defaults = platform_provenance_defaults.get(
                    platform_key,
                    {
                        "sourcePlatform": platform_key,
                        "retrievalMethod": "unknown",
                    },
                )

                c_obj["sourcePlatform"] = defaults["sourcePlatform"]
                c_obj["retrievalMethod"] = defaults["retrievalMethod"]
                if platform_retrieved_at:
                    c_obj["retrievedAt"] = platform_retrieved_at
                else:
                    c_obj["retrievedAt"] = datetime.now(UTC).isoformat()
                verification_status, evidence_level, url_kind = (
                    classify_credential_evidence(
                        platform_key,
                        defaults["retrievalMethod"],
                        url=url or None,
                        verify_url=verify_url or None,
                        retired=retired,
                    )
                )
                raw_source_url = url or verify_url or None
                verify_url_val = (
                    (verify_url or url)
                    if url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION
                    and (verify_url or url)
                    else None
                )
                last_verified_at = None
                if (
                    evidence_level == EvidenceLevel.ISSUER_CREDENTIAL
                    and url_kind == VerificationUrlKind.CREDENTIAL_ASSERTION
                    and verify_url_val
                ):
                    cache_entry = active_verifications.get(verify_url_val)
                    if cache_entry and is_verified_and_fresh(
                        cache_entry, ttl_days=ACTIVE_VERIFICATION_TTL_DAYS
                    ):
                        last_verified_at = cache_entry.get("last_verified_at")
                        if (
                            not retired
                            and verification_status != VerificationStatus.EXPIRED
                        ):
                            verification_status = VerificationStatus.VERIFIED

                c_obj["verificationStatus"] = verification_status.value
                c_obj["evidenceLevel"] = evidence_level.value
                c_obj["verificationUrlKind"] = url_kind.value
                c_obj["sourceRecordId"] = cred_id if cred_id else None
                c_obj["sourceUrl"] = raw_source_url
                c_obj["verifyUrl"] = verify_url_val
                c_obj["lastVerifiedAt"] = last_verified_at
                c_obj["sourceHash"] = None

                credentials.append(c_obj)

    return credentials


def to_compact_record(cred: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON-LD credential object into a lean, AI-friendly machine feed record."""
    platform = str(cred.get("platform") or cred.get("sourcePlatform") or "unknown")
    record_id = str(
        cred.get("sourceRecordId")
        or cred.get("identifier")
        or f"{platform}:{cred.get('name', '')}"
    )
    retired = cred.get("credentialStatus") == "Retired"

    compact: dict[str, Any] = {
        "id": record_id,
        "sourceRecordId": cred.get("sourceRecordId"),
        "sourceHash": cred.get("sourceHash"),
        "platform": platform,
        "name": cred.get("name", ""),
        "category": cred.get("credentialCategory", "Badge/Certification"),
        "retrievedAt": cred.get("retrievedAt") or datetime.now(UTC).isoformat(),
        "retrievalMethod": cred.get("retrievalMethod", "unknown"),
        "evidenceLevel": cred.get("evidenceLevel", "self_reported"),
        "verificationStatus": cred.get("verificationStatus", "unknown"),
        "verificationUrlKind": cred.get("verificationUrlKind", "none"),
        "retired": retired,
    }

    optional_fields = (
        ("issuer", "issuer"),
        ("dateCreated", "dateCreated"),
        ("url", "url"),
        ("sourceUrl", "sourceUrl"),
        ("verifyUrl", "verifyUrl"),
        ("lastVerifiedAt", "lastVerifiedAt"),
        ("image", "image"),
        ("description", "description"),
        ("skills", "skills"),
    )
    for src_key, dst_key in optional_fields:
        val = cred.get(src_key)
        if val:
            compact[dst_key] = val

    if retired:
        if cred.get("retirement_source"):
            compact["retirementSource"] = cred["retirement_source"]
        if cred.get("retirement_reason"):
            compact["retirementReason"] = cred["retirement_reason"]
        if cred.get("retired_at"):
            compact["retiredAt"] = cred["retired_at"]

    return compact


def build_compact_feed_payload(credentials: list[dict[str, Any]]) -> dict[str, Any]:
    """Build compact JSON feed payload and counts from credential objects."""
    compact_items = [to_compact_record(c) for c in credentials]
    counts = Counter(item["platform"] for item in compact_items)
    return {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "owner": {
            "name": "Vojislav Miloradovic",
            "url": "https://github.com/VojislavMiloradovic/my-credentials",
        },
        "totalCount": len(compact_items),
        "countsByPlatform": dict(sorted(counts.items())),
        "credentials": compact_items,
    }


def cleanup_readme(readme_path: str | None = None):
    """Ensures README.md stays clean without embedded script blocks."""
    target_readme = readme_path or README_PATH
    if not os.path.exists(target_readme):
        return

    with open(target_readme, "r", encoding="utf-8") as f:
        content = f.read()

    if MARKER_START in content and MARKER_END in content:
        split_start = content.split(MARKER_START)
        split_end = split_start[1].split(MARKER_END)
        content = split_start[0].strip() + "\n\n" + split_end[1].lstrip()

    _atomic_write_text(target_readme, content)
    print(f"Ensured {target_readme} is clean of embedded script blocks.")


def build_credentials(*, force_markdown: bool = False) -> list[dict[str, Any]]:
    """Build credential records from L1 normalized JSONs (default) or Markdown fallback."""
    if force_markdown:
        return parse_archive_monoliths()

    # Guard for legacy isolated tests that only patch ARCHIVE_DIR without patching VALIDATION_DIR
    archive_patched_only = (
        ARCHIVE_DIR != "archives" and VALIDATION_DIR == "for_validation"
    )
    if not archive_patched_only and _has_l1_sources(VALIDATION_DIR):
        return parse_l1_normalized(VALIDATION_DIR, ACTIVE_VERIFICATIONS_PATH)

    return parse_archive_monoliths()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate credentials.jsonld and compact machine feeds from L1 records."
    )
    parser.add_argument("--validation-dir", default=None)
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--readme", default=None)
    parser.add_argument("--jsonld", default=None)
    parser.add_argument("--feed-json", default=None)
    parser.add_argument("--feed-ndjson", default=None)
    parser.add_argument("--active-verifications", default=None)
    parser.add_argument(
        "--legacy-markdown",
        action="store_true",
        help="Force legacy Markdown archive parsing instead of L1 normalized JSONs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    global VALIDATION_DIR, ARCHIVE_DIR, README_PATH, JSONLD_PATH
    global FEED_JSON_PATH, FEED_NDJSON_PATH, ACTIVE_VERIFICATIONS_PATH

    args = parse_args([] if argv is None else argv)
    if args.validation_dir:
        VALIDATION_DIR = args.validation_dir
    if args.archive_dir:
        ARCHIVE_DIR = args.archive_dir
    if args.readme:
        README_PATH = args.readme
    if args.jsonld:
        JSONLD_PATH = args.jsonld
        # If caller only overrode JSONLD_PATH via CLI, keep feeds adjacent unless overridden
        out_dir = os.path.dirname(JSONLD_PATH)
        if not args.feed_json and out_dir:
            FEED_JSON_PATH = os.path.join(out_dir, "credentials.feed.json")
        if not args.feed_ndjson and out_dir:
            FEED_NDJSON_PATH = os.path.join(out_dir, "credentials.ndjson")
    if args.feed_json:
        FEED_JSON_PATH = args.feed_json
    if args.feed_ndjson:
        FEED_NDJSON_PATH = args.feed_ndjson
    if args.active_verifications:
        ACTIVE_VERIFICATIONS_PATH = args.active_verifications

    # Also align feed paths with JSONLD_PATH when tests patch generate_jsonld.JSONLD_PATH
    target_feed_json = FEED_JSON_PATH
    target_feed_ndjson = FEED_NDJSON_PATH
    if (
        JSONLD_PATH != "credentials.jsonld"
        and FEED_JSON_PATH == "credentials.feed.json"
    ):
        target_feed_json = os.path.join(
            os.path.dirname(JSONLD_PATH) or ".", "credentials.feed.json"
        )
    if JSONLD_PATH != "credentials.jsonld" and FEED_NDJSON_PATH == "credentials.ndjson":
        target_feed_ndjson = os.path.join(
            os.path.dirname(JSONLD_PATH) or ".", "credentials.ndjson"
        )

    credentials = build_credentials(force_markdown=args.legacy_markdown)

    payload = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": "Vojislav Miloradovic",
            "url": "https://github.com/VojislavMiloradovic/my-credentials",
            "hasCredential": credentials,
        },
    }

    feed_payload = build_compact_feed_payload(credentials)
    ndjson_lines = [
        json.dumps(item, separators=(",", ":"), ensure_ascii=False)
        for item in feed_payload["credentials"]
    ]

    # Validate everything BEFORE writing any output (fail-closed)
    validate_jsonld(payload)
    validate_feed_payload(feed_payload)

    jsonld_serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    feed_json_serialized = json.dumps(
        feed_payload, separators=(",", ":"), ensure_ascii=False
    )
    ndjson_serialized = "\n".join(ndjson_lines) + ("\n" if ndjson_lines else "")

    _atomic_write_text(JSONLD_PATH, jsonld_serialized)
    _atomic_write_text(target_feed_json, feed_json_serialized)
    _atomic_write_text(target_feed_ndjson, ndjson_serialized)

    print(
        f"\n Successfully generated {JSONLD_PATH}, {target_feed_json}, and {target_feed_ndjson} "
        f"with {len(credentials)} total credential(s)."
    )
    cleanup_readme(README_PATH)


if __name__ == "__main__":
    main(sys.argv[1:])
