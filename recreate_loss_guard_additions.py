# ==============================================================================
# PROVIDER CONFIGURATION & ORCHESTRATION
# ==============================================================================

# Per-platform configuration for loss guard orchestration
# Keys: platform name, baseline_sources (list), id_field, threshold, streams, fail_on_warn
PROVIDER_CONFIG = {
    "microsoft-learn": {
        "id_field": "id",
        "baseline_sources": ["monolith"],  # Uses monolith markdown only
        "threshold": 0.15,
        "fail_on_warn": True,
    },
    "credly": {
        "id_field": "id",
        "baseline_sources": ["json", "monolith"],  # Checks JSON file then monolith
        "threshold": 0.15,
        "fail_on_warn": True,
    },
    "aws-skills": {
        "id_field": "id",
        "baseline_sources": ["json", "monolith"],
        "threshold": 0.15,
        "fail_on_warn": True,
    },
    "google-skills": {
        "id_field": "id",
        "baseline_sources": ["json", "monolith"],
        "threshold": 0.15,
        "fail_on_warn": True,
    },
    "linkedin-certifications": {
        "id_field": "license",
        "baseline_sources": ["monolith"],
        "threshold": 0.15,
        "fail_on_warn": True,
    },
    "google-developer": {
        "id_field": "title",
        "baseline_sources": ["monolith"],
        "threshold": 0.15,
        "fail_on_warn": False,  # Warns instead of failing (MHTML migration)
        "streams": ["public_badges", "detailed_learnings", "combined"],
    },
}


def get_stored_archive_baseline_count(
    platform: str,
    json_path: str | None = None,
    monolith_path: str | None = None,
) -> int:
    """
    Get baseline record count from stored archive sources.

    Args:
        platform: Platform identifier
        json_path: Path to L1_normalized JSON file (e.g., for_validation/credly_badges.json)
        monolith_path: Path to L2_published monolith markdown (e.g., archives/credly-complete.md)

    Returns:
        Baseline record count, or 0 if no baseline found
    """
    config = PROVIDER_CONFIG.get(platform, {})
    sources = config.get("baseline_sources", ["monolith"])

    # Try JSON source first (if configured and path provided)
    if "json" in sources and json_path and os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = (
                    data.get("total_count", len(data.get("credentials", [])))
                    if isinstance(data, dict)
                    else len(data)
                )
                if count > 0:
                    logger.info(f"📊 [{platform}] Baseline count from JSON: {count:,}")
                    return count
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    # Fall back to monolith markdown
    if "monolith" in sources and monolith_path and os.path.exists(monolith_path):
        try:
            with open(monolith_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Find table rows (lines starting with |)
            table_rows = [l for l in lines if l.strip().startswith("|")]

            if not table_rows:
                return 0

            # Find the separator row (contains :--- or ---)
            separator_idx = -1
            for i, row in enumerate(table_rows):
                if ":---" in row or (row.count("---") >= 2 and not any(h in row.lower() for h in ["title", "achievement", "badge", "credential", "certification"])):
                    separator_idx = i
                    break

            # Data rows are AFTER the separator
            if separator_idx >= 0 and separator_idx + 1 < len(table_rows):
                data_rows = table_rows[separator_idx + 1:]
            elif separator_idx == -1:
                # No separator found - assume first row is header, rest are data
                data_rows = table_rows[1:] if len(table_rows) > 1 else []
            else:
                data_rows = []

            if data_rows:
                count = len(data_rows)
                logger.info(f"📊 [{platform}] Baseline count from monolith: {count:,}")
                return count
        except OSError:
            pass

    return 0


def execute_data_loss_guard(
    new_records: list[dict],
    platform: str,
    json_path: str | None = None,
    monolith_path: str | None = None,
) -> int:
    """
    Count-based loss guard: compares incoming record count against stored baseline.

    Args:
        new_records: List of validated records from pipeline
        platform: Platform identifier
        json_path: Path to L1_normalized JSON file
        monolith_path: Path to L2_published monolith markdown

    Returns:
        Baseline count used for comparison

    Raises:
        PipelineDataLossAnomaly: If drop exceeds threshold or empty incoming with baseline
    """
    config = PROVIDER_CONFIG.get(platform, {})
    threshold = config.get("threshold", 0.15)

    old_count = get_stored_archive_baseline_count(platform, json_path, monolith_path)
    new_count = len(new_records)

    logger.info(
        f"📊 [{platform}] Count Loss Guard: Baseline={old_count:,} | Incoming={new_count:,}"
    )

    # Empty incoming with existing baseline = critical failure
    if old_count > 0 and new_count == 0:
        raise PipelineDataLossAnomaly(
            f"CRITICAL ANOMALY: Incoming fetch returned 0 records, "
            f"but baseline contains {old_count}. Aborting sync."
        )

    # Check drop ratio
    if old_count > 0:
        drop_ratio = (old_count - new_count) / float(old_count)
        if drop_ratio > threshold:
            raise PipelineDataLossAnomaly(
                f"CRITICAL ANOMALY: Incoming count ({new_count:,}) dropped by "
                f"{drop_ratio:.1%} from baseline ({old_count:,}). "
                f"Threshold: {threshold:.0%}. Aborting write."
            )

    logger.info(f"✅ [{platform}] Count Loss Guard PASSED.")
    return old_count


def run_provider_loss_guards(
    new_records: list[dict],
    provider_name: str,
    fail_on_warn: bool | None = None,
    json_path: str | None = None,
    monolith_path: str | None = None,
) -> "DiffReport":
    """
    Run both count-based and content-aware loss guards for a provider.

    This is the main orchestration function that replaces duplicated logic in provider scripts.

    Args:
        new_records: List of validated record dicts from pipeline
        provider_name: Platform identifier (e.g., "microsoft-learn")
        fail_on_warn: Override for fail_on_warn (None = use PROVIDER_CONFIG default)
        json_path: Path to L1_normalized JSON for count baseline
        monolith_path: Path to L2_published monolith for count baseline

    Returns:
        DiffReport from content-aware guard

    Raises:
        PipelineDataLossAnomaly: If either guard fails and fail_on_warn=True
    """
    config = PROVIDER_CONFIG.get(provider_name, {})

    # Determine fail_on_warn: explicit override > config > default True
    if fail_on_warn is None:
        fail_on_warn = config.get("fail_on_warn", True)

    logger.info(f"🛡️ [{provider_name}] Starting provider loss guard orchestration...")

    # 1. Count-based loss guard (fast, catches major drops)
    execute_data_loss_guard(new_records, provider_name, json_path, monolith_path)

    # 2. Content-aware loss guard (comprehensive, catches silent modifications)
    # For google-developer with streams, we run on combined feed first
    streams = config.get("streams")
    if streams and "combined" in streams:
        # Run on combined feed first
        execute_content_loss_guard(
            new_records,
            platform=provider_name,
            id_field=config.get("id_field", "id"),
            fail_on_warn=fail_on_warn,
            stream_id="combined",
        )
    else:
        # Single stream (most providers)
        execute_content_loss_guard(
            new_records,
            platform=provider_name,
            id_field=config.get("id_field", "id"),
            fail_on_warn=fail_on_warn,
        )

    logger.info(f"✅ [{provider_name}] All loss guards passed.")
    return DiffReport(
        platform=provider_name,
        old_count=0,  # Not tracking old_count here
        new_count=len(new_records),
        retained_count=0,
        modified_count=0,
        added_count=0,
        removed_count=0,
        retention_rate=1.0,
        modification_rate=0.0,
        integrity_score=1.0,
        details={"status": "orchestration_complete"},
    )


def generate_provider_baseline(
    new_records: list[dict],
    provider_name: str,
    stream_id: str | None = None,
) -> bool:
    """
    Generate and save baseline fingerprints for a provider.

    Args:
        new_records: List of validated records
        provider_name: Platform identifier
        stream_id: Optional stream identifier (for google-developer multi-stream)

    Returns:
        True if baseline saved successfully
    """
    config = PROVIDER_CONFIG.get(provider_name, {})

    if stream_id:
        # Per-stream baseline (google-developer)
        logger.info(f"💾 [{provider_name} ({stream_id})] Generating stream baseline...")
        return save_baseline(
            provider_name,
            build_fingerprint_index(new_records, config.get("id_field", "id"), provider_name),
            stream_id,
        )
    else:
        # Single baseline (most providers)
        logger.info(f"💾 [{provider_name}] Generating baseline...")
        return save_baseline(
            provider_name,
            build_fingerprint_index(new_records, config.get("id_field", "id"), provider_name),
        )


def generate_all_provider_baselines(
    new_records: list[dict],
    provider_name: str,
) -> dict[str, bool]:
    """
    Generate baselines for all streams of a provider (google-developer).

    Args:
        new_records: List of validated records (combined feed)
        provider_name: Platform identifier

    Returns:
        Dict of stream_id -> success boolean
    """
    config = PROVIDER_CONFIG.get(provider_name, {})
    streams = config.get("streams")

    if not streams:
        # Single baseline provider
        success = generate_provider_baseline(new_records, provider_name)
        return {"default": success}

    # Multi-stream provider (google-developer)
    results = {}
    for stream in streams:
        # For now, all streams use the combined feed
        # In future, could filter records per stream
        success = generate_provider_baseline(new_records, provider_name, stream_id=stream)
        results[stream] = success

    return results