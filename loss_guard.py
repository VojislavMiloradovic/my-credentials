"""
loss_guard.py
-------------
Content-aware loss guard for credential pipeline integrity verification.

Compares stable record identities and content fingerprints across runs,
not just total counts. Detects record replacement, modification, and
unexpected deletions even when total count remains stable.

Baseline files stored in for_validation/{platform}-baseline.json
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("loss_guard")

VALIDATION_DIR = os.getenv("VALIDATION_DIR", "for_validation")


def get_baseline_path(platform: str, stream_id: str | None = None) -> str:
    """
    Get the baseline file path for a platform, optionally with a stream identifier.

    Args:
        platform: Platform identifier (e.g., "google-developer")
        stream_id: Optional stream identifier (e.g., "public_badges", "detailed_learnings", "combined")

    Returns:
        Path to the baseline file
    """
    if stream_id:
        filename = f"{platform}-{stream_id}-baseline.json"
    else:
        filename = f"{platform}-baseline.json"
    return os.path.join(VALIDATION_DIR, filename)


# ==============================================================================
# DATA CLASSES
# ==============================================================================


@dataclass
class DiffReport:
    """Detailed comparison report between baseline and incoming dataset."""

    platform: str
    old_count: int
    new_count: int
    retained_count: int  # Records with matching ID + identical hash
    modified_count: int  # Same ID, different hash (content changed)
    added_count: int  # New IDs not in baseline
    removed_count: int  # Old IDs not in incoming
    retention_rate: float  # retained / old_count
    modification_rate: float  # modified / old_count
    integrity_score: float  # Composite health metric (0.0 - 1.0)
    details: dict  # Per-record diffs for audit

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecordFingerprint:
    """Stable identity + content hash for a single record."""

    record_id: str
    content_hash: str
    platform: str
    timestamp: str  # ISO format when fingerprint was created


# ==============================================================================
# CORE FUNCTIONS
# ==============================================================================


def compute_content_hash(record: dict, id_field: str) -> str:
    """
    Compute stable content hash for a record, excluding the ID field itself
    and any volatile fields that change on every export (e.g., version, _ts).
    """
    # Fields that should NOT contribute to content hash (volatile metadata)
    VOLATILE_FIELDS = {
        "version",
        "_ts",
        "partitionKey",
        "userId",
        "docsId",
        "instanceId",
        "labUrl",
        "createdAt",
        "expiresAt",
        "estimatedReadyAt",
        "sessionEndDate",
        "startTime",
        "endTime",
        "milestoneEligible",
        "locale",
        "source",
        "imageUrl",
        "image_url",
        "verified",
        "typeId",
        "sourceId",
        "id",
        "name",  # name is alias for title, not content
        "issuer_name",
        "issued_at",
        "issued_at_date",
        "date",
        "url",  # date aliases
        "verification_type",  # alias for type
        "skills",  # can vary in ordering but not semantic content
        "retired",
        "retirement_reason",
        "retired_at",  # schema addition fields, not content change
        # Provenance fields (added for Phase 1-3) - not content changes
        "source_platform",
        "source_record_id",
        "source_url",
        "verify_url",
        "retrieved_at",
        "last_verified_at",
        "verification_status",
        "source_hash",
        "retrieval_method",
    }

    # Create a normalized copy for hashing
    normalized = {}
    for k, v in record.items():
        if k in VOLATILE_FIELDS:
            continue
        if k == id_field:
            continue
        # Normalize lists/dicts for stable hashing
        if isinstance(v, list):
            normalized[k] = sorted([str(item) for item in v])
        elif isinstance(v, dict):
            normalized[k] = {sk: sv for sk, sv in sorted(v.items())}
        else:
            normalized[k] = v

    # Stable JSON serialization
    content_str = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(content_str.encode("utf-8")).hexdigest()[:32]


def extract_record_id(record: dict, id_field: str, platform: str) -> str:
    """
    Extract stable record ID from record dict.
    Falls back to content-based hash if primary ID field missing.
    """
    # Try primary ID field
    record_id = record.get(id_field)
    if record_id:
        return str(record_id)

    # Platform-specific fallbacks
    if platform == "microsoft-learn":
        # For achievements: use 'id' field (e.g., EG94SBRP)
        # For credentials: use 'credentialId'
        return str(
            record.get("id")
            or record.get("credentialId")
            or record.get("sourceUid")
            or ""
        )
    elif platform == "google-skills":
        return str(record.get("id") or record.get("badge_id") or "")
    elif platform in ("aws-skills", "credly"):
        return str(record.get("id") or "")
    elif platform == "linkedin-certifications":
        # LinkedIn uses license number + name hash
        license_num = record.get("license", "")
        name = record.get("name", "")
        if license_num:
            return f"linkedin-{license_num}"
        return f"linkedin-{hashlib.sha256(name.encode()).hexdigest()[:16]}"
    elif platform == "google-developer":
        # No native ID - use title + date hash
        title = record.get("title", "")
        date = record.get("date", "")
        return f"gdev-{hashlib.sha256(f'{title}{date}'.encode()).hexdigest()[:16]}"

    # Generic fallback: hash of all non-volatile fields
    fallback_content = json.dumps(
        {k: v for k, v in record.items() if k not in {"version", "_ts"}}, sort_keys=True
    )
    return f"auto-{hashlib.sha256(fallback_content.encode()).hexdigest()[:16]}"


def build_fingerprint_index(
    records: list[dict], id_field: str, platform: str
) -> dict[str, RecordFingerprint]:
    """
    Build a fingerprint index from a list of records.
    Returns dict: {record_id: RecordFingerprint}
    """
    index = {}
    timestamp = datetime.now(UTC).isoformat()

    for record in records:
        record_id = extract_record_id(record, id_field, platform)
        if not record_id:
            logger.warning(
                f"⚠️ [{platform}] Skipping record with no identifiable ID: "
                f"{record.get('title', 'unknown')}"
            )
            continue

        content_hash = compute_content_hash(record, id_field)
        index[record_id] = RecordFingerprint(
            record_id=record_id,
            content_hash=content_hash,
            platform=platform,
            timestamp=timestamp,
        )

    return index


def load_baseline(
    platform: str, stream_id: str | None = None
) -> dict[str, RecordFingerprint] | None:
    """
    Load baseline fingerprint index from for_validation/{platform}-baseline.json.
    Returns None if no baseline exists (first run).

    Args:
        platform: Platform identifier (e.g., "google-developer")
        stream_id: Optional stream identifier for per-stream baselines
    """
    baseline_path = get_baseline_path(platform, stream_id)

    if not os.path.exists(baseline_path):
        stream_suffix = f" ({stream_id})" if stream_id else ""
        logger.info(
            f"📦 [{platform}{stream_suffix}] No baseline found at {baseline_path} — first run."
        )
        return None

    try:
        with open(baseline_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate baseline structure
        if not isinstance(data, dict) or "fingerprints" not in data:
            logger.warning(
                f"⚠️ [{platform}] Baseline format invalid, treating as first run."
            )
            return None

        # Reconstruct RecordFingerprint objects
        index = {}
        for rid, fp_data in data["fingerprints"].items():
            index[rid] = RecordFingerprint(**fp_data)

        stream_suffix = f" ({stream_id})" if stream_id else ""
        logger.info(
            f"📂 [{platform}{stream_suffix}] Loaded baseline: {len(index)} records from {baseline_path}"
        )
        return index

    except (json.JSONDecodeError, OSError, TypeError) as e:
        logger.warning(
            f"⚠️ [{platform}] Failed to load baseline ({e}), treating as first run."
        )
        return None


def save_baseline(
    platform: str,
    fingerprint_index: dict[str, RecordFingerprint],
    stream_id: str | None = None,
) -> bool:
    """
    Atomically save fingerprint index as new baseline.
    Returns True on success.

    Args:
        platform: Platform identifier (e.g., "google-developer")
        fingerprint_index: Dictionary of record fingerprints
        stream_id: Optional stream identifier for per-stream baselines
    """
    baseline_path = get_baseline_path(platform, stream_id)
    temp_path = baseline_path + ".tmp"

    try:
        # Ensure validation directory exists
        os.makedirs(VALIDATION_DIR, exist_ok=True)

        # Prepare serializable data
        data = {
            "platform": platform,
            "stream_id": stream_id,
            "record_count": len(fingerprint_index),
            "created_at": datetime.now(UTC).isoformat(),
            "fingerprints": {rid: asdict(fp) for rid, fp in fingerprint_index.items()},
        }

        # Atomic write: write to temp, then rename
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Windows-safe atomic replace: remove destination first if it exists
        try:
            os.replace(temp_path, baseline_path)
        except OSError:
            # Windows: destination may be read-only or locked, try removing first
            if os.path.exists(baseline_path):
                os.remove(baseline_path)
            os.replace(temp_path, baseline_path)

        stream_suffix = f" ({stream_id})" if stream_id else ""
        logger.info(
            f"💾 [{platform}{stream_suffix}] Baseline updated: {len(fingerprint_index)} records → {baseline_path}"
        )
        return True

    except OSError as e:
        logger.error(f"❌ [{platform}] Failed to save baseline: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def compare_fingerprints(
    baseline: dict[str, RecordFingerprint] | None,
    incoming: dict[str, RecordFingerprint],
    platform: str,
) -> DiffReport:
    """
    Compare baseline vs incoming fingerprints and generate DiffReport.
    """
    if baseline is None:
        # First run - everything is "added", nothing retained/modified/removed
        return DiffReport(
            platform=platform,
            old_count=0,
            new_count=len(incoming),
            retained_count=0,
            modified_count=0,
            added_count=len(incoming),
            removed_count=0,
            retention_rate=1.0,  # N/A, but set to 1.0 for first run
            modification_rate=0.0,
            integrity_score=1.0,
            details={
                "note": "First run - baseline established",
                "added_ids": list(incoming.keys()),
            },
        )

    baseline_ids = set(baseline.keys())
    incoming_ids = set(incoming.keys())

    # Categorize records
    common_ids = baseline_ids & incoming_ids
    added_ids = incoming_ids - baseline_ids
    removed_ids = baseline_ids - incoming_ids

    retained_count = 0
    modified_count = 0
    modified_details = []

    for rid in common_ids:
        if baseline[rid].content_hash == incoming[rid].content_hash:
            retained_count += 1
        else:
            modified_count += 1
            modified_details.append(
                {
                    "id": rid,
                    "old_hash": baseline[rid].content_hash,
                    "new_hash": incoming[rid].content_hash,
                }
            )

    old_count = len(baseline_ids)
    new_count = len(incoming_ids)

    retention_rate = retained_count / old_count if old_count > 0 else 1.0
    modification_rate = modified_count / old_count if old_count > 0 else 0.0

    # Integrity score: weighted composite
    # - High retention = good
    # - Low modification = good
    # - Low removal = good
    # - Penalize unexpected additions (could be spam/injection)
    removal_rate = len(removed_ids) / old_count if old_count > 0 else 0.0
    addition_rate = len(added_ids) / new_count if new_count > 0 else 0.0

    integrity_score = (
        0.4 * retention_rate
        + 0.2 * (1.0 - modification_rate)
        + 0.2 * (1.0 - removal_rate)
        + 0.2 * (1.0 - min(addition_rate, 1.0))  # Cap addition penalty
    )

    return DiffReport(
        platform=platform,
        old_count=old_count,
        new_count=new_count,
        retained_count=retained_count,
        modified_count=modified_count,
        added_count=len(added_ids),
        removed_count=len(removed_ids),
        retention_rate=retention_rate,
        modification_rate=modification_rate,
        integrity_score=integrity_score,
        details={
            "added_ids": sorted(added_ids),
            "removed_ids": sorted(removed_ids),
            "modified_ids": [m["id"] for m in modified_details],
            "modified_details": modified_details,
        },
    )


def log_diff_report(report: DiffReport) -> None:
    """Log detailed DiffReport in GitHub Actions friendly format."""
    p = report.platform

    logger.info(
        f"🛡️ Loss Guard [{p}]: Baseline={report.old_count:,} | Incoming={report.new_count:,}"
    )
    logger.info(
        f"   Retained: {report.retained_count:,} ({report.retention_rate:.1%}) | "
        f"Modified: {report.modified_count:,} ({report.modification_rate:.1%}) | "
        f"Added: {report.added_count:,} | Removed: {report.removed_count:,}"
    )
    logger.info(f"   Integrity Score: {report.integrity_score:.3f}")

    # Log details for audit trail
    if report.details.get("added_ids"):
        added_preview = report.details["added_ids"][:10]
        suffix = "..." if len(report.details["added_ids"]) > 10 else ""
        logger.info(
            f"   ➕ Added ({len(report.details['added_ids'])}): {added_preview}{suffix}"
        )
    if report.details.get("removed_ids"):
        removed_preview = report.details["removed_ids"][:10]
        suffix = "..." if len(report.details["removed_ids"]) > 10 else ""
        logger.warning(
            f"   ➖ Removed ({len(report.details['removed_ids'])}): {removed_preview}{suffix}"
        )
    if report.details.get("modified_ids"):
        modified_preview = report.details["modified_ids"][:10]
        suffix = "..." if len(report.details["modified_ids"]) > 10 else ""
        logger.warning(
            f"   🔄 Modified ({len(report.details['modified_ids'])}): {modified_preview}{suffix}"
        )


# ==============================================================================
# GUARD THRESHOLDS & ENFORCEMENT
# ==============================================================================


class PipelineDataLossAnomaly(Exception):
    """Raised when dataset fails integrity thresholds."""


# DEFAULT THRESHOLDS - can be overridden per platform
DEFAULT_THRESHOLDS = {
    "min_retention_rate": 0.85,  # Must retain at least 85% of old records
    "max_modification_rate": 0.30,  # Flag if >30% of retained records changed content
    "max_removal_rate": 0.15,  # Flag if >15% of old records removed
    "min_integrity_score": 0.70,  # Composite score must exceed 0.70
}

# Per-platform overrides (can be tuned based on expected churn)
PLATFORM_THRESHOLDS = {
    "microsoft-learn": {
        "min_retention_rate": 0.90,  # MS Learn data very stable
        "max_modification_rate": 0.10,  # Content rarely changes
        "max_removal_rate": 0.05,  # Almost no deletions expected
        "min_integrity_score": 0.85,
    },
    "google-skills": {
        "min_retention_rate": 0.85,
        "max_modification_rate": 0.20,
        "max_removal_rate": 0.10,
        "min_integrity_score": 0.75,
    },
    "aws-skills": {
        "min_retention_rate": 0.85,
        "max_modification_rate": 0.25,
        "max_removal_rate": 0.15,
        "min_integrity_score": 0.70,
    },
    "credly": {
        "min_retention_rate": 0.85,
        "max_modification_rate": 0.20,
        "max_removal_rate": 0.10,
        "min_integrity_score": 0.75,
    },
    "linkedin-certifications": {
        "min_retention_rate": 0.85,
        "max_modification_rate": 0.30,
        "max_removal_rate": 0.15,
        "min_integrity_score": 0.70,
    },
    "google-developer": {
        "min_retention_rate": 0.80,  # Local text parsing less stable
        "max_modification_rate": 0.30,
        "max_removal_rate": 0.20,
        "min_integrity_score": 0.65,
    },
}


def execute_content_loss_guard(
    new_records: list[dict],
    platform: str,
    id_field: str = "id",
    thresholds: dict | None = None,
    fail_on_warn: bool = True,  # SET TO False TO DISABLE FAILURES (comment out raise lines)
    stream_id: str | None = None,  # Optional stream identifier for per-stream baselines
) -> DiffReport:
    """
    Main entry point: validates incoming records against baseline.

    Args:
        new_records: List of validated record dicts from pipeline
        platform: Platform identifier (e.g., "microsoft-learn")
        id_field: Primary ID field name in record dicts
        thresholds: Optional override for threshold dict
        fail_on_warn: If True, raise on threshold violations. SET False to log only.
        stream_id: Optional stream identifier for per-stream baselines (e.g., "public_badges", "detailed_learnings")

    Returns:
        DiffReport with detailed comparison results

    Raises:
        PipelineDataLossAnomaly: If thresholds exceeded and fail_on_warn=True
    """
    stream_suffix = f" ({stream_id})" if stream_id else ""
    logger.info(f"🛡️ [{platform}{stream_suffix}] Starting content-aware loss guard...")

    # Merge thresholds: defaults + platform-specific + explicit override
    effective_thresholds = {**DEFAULT_THRESHOLDS}
    effective_thresholds.update(PLATFORM_THRESHOLDS.get(platform, {}))
    if thresholds:
        effective_thresholds.update(thresholds)

    # Build fingerprint index for incoming records
    incoming_index = build_fingerprint_index(new_records, id_field, platform)
    logger.info(f"   Fingerprinted {len(incoming_index)} incoming records")

    # Load baseline
    baseline_index = load_baseline(platform, stream_id)

    # Compare
    report = compare_fingerprints(baseline_index, incoming_index, platform)

    # Log detailed report
    log_diff_report(report)

    # Evaluate thresholds
    violations = []
    warnings = []

    if report.old_count > 0:  # Skip threshold checks on first run
        if report.retention_rate < effective_thresholds["min_retention_rate"]:
            violations.append(
                f"Retention rate {report.retention_rate:.1%} below threshold "
                f"{effective_thresholds['min_retention_rate']:.0%}"
            )

        if report.modification_rate > effective_thresholds["max_modification_rate"]:
            violations.append(
                f"Modification rate {report.modification_rate:.1%} exceeds threshold "
                f"{effective_thresholds['max_modification_rate']:.0%}"
            )

        removal_rate = report.removed_count / report.old_count
        if removal_rate > effective_thresholds["max_removal_rate"]:
            warnings.append(
                f"Removal rate {removal_rate:.1%} exceeds threshold "
                f"{effective_thresholds['max_removal_rate']:.0%}"
            )

        if report.integrity_score < effective_thresholds["min_integrity_score"]:
            violations.append(
                f"Integrity score {report.integrity_score:.3f} below threshold "
                f"{effective_thresholds['min_integrity_score']:.2f}"
            )

    # Log violations/warnings
    for v in violations:
        logger.error(f"❌ [{platform}{stream_suffix}] THRESHOLD VIOLATION: {v}")
    for w in warnings:
        logger.warning(f"⚠️ [{platform}{stream_suffix}] THRESHOLD WARNING: {w}")

    # Determine outcome
    has_violations = len(violations) > 0
    has_warnings = len(warnings) > 0

    if has_violations:
        msg = f"[{platform}{stream_suffix}] Content integrity check FAILED: {'; '.join(violations)}"
        if fail_on_warn:
            logger.error(f"🚫 {msg} — Pipeline terminated.")
            raise PipelineDataLossAnomaly(msg)
        else:
            logger.warning(f"⚠️ {msg} — Continuing (fail_on_warn=False).")

    if has_warnings and not has_violations:
        msg = f"[{platform}{stream_suffix}] Content integrity WARNINGS: {'; '.join(warnings)}"
        if fail_on_warn:
            logger.error(f"🚫 {msg} — Pipeline terminated (warn treated as fail).")
            raise PipelineDataLossAnomaly(msg)
        else:
            logger.warning(f"⚠️ {msg} — Continuing (fail_on_warn=False).")

    if not has_violations and not has_warnings:
        logger.info(f"✅ [{platform}{stream_suffix}] Content integrity check PASSED.")

    # On success (or if not failing), update baseline
    if not has_violations or not fail_on_warn:
        if save_baseline(platform, incoming_index, stream_id):
            logger.info(
                f"💾 [{platform}{stream_suffix}] Baseline persisted for next run."
            )
        else:
            logger.error(f"❌ [{platform}{stream_suffix}] Failed to persist baseline!")

    return report
