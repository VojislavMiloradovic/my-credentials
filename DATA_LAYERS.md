# Data Layers Architecture

This document describes the multi-layer data architecture for aggregating professional credentials from 6 platforms into a unified, validated dataset.

## Overview

The pipeline uses a 4-layer architecture with platform-specific transforms declared in `dataset_layers.yaml`:

```
L0_raw (source exports) 
    → L1_normalized (validated/deduplicated) 
    → L2_published (archives/JSON-LD) 
    → L3_display (README/llms.txt metrics)
```

## Platforms

| Platform | Key | L0 Source | L1 Transform | L2 Artifacts | L3 Metrics |
|----------|-----|-----------|--------------|--------------|------------|
| Microsoft Learn | `microsoft-learn` | JSON export | `extract_achievements_dedupe_by_id` | `complete`, `index` | `total_achievements`, `total_xp`, `active_achievements` |
| Google Cloud Skills | `google-skills` | HTML profiles | `1:1_pass_through` | `complete`, `index` | `total_badges`, `by_category` |
| AWS Skills | `aws-skills` | CSV export | `parse_csv_combine_retired_flags` | `complete`, `index` | `total_badges`, `active_badges`, `retired_badges` |
| Credly | `credly` | JSON export | `extract_milestone_badges_dedupe` | `complete`, `index` | `total_badges`, `by_issuer` |
| LinkedIn | `linkedin-certifications` | HTML export | `1:1_pass_through` | `complete`, `index` | `total_certifications` |
| Google Developer | `google-developer` | MHTML codelabs + local learnings | `parse_mhtml_codelabs`, `parse_local_learnings_dedupe` | `complete`, `index`, `codelabs`, `local_learnings` | `total_badges`, `codelabs_count`, `local_learnings_count` |

## Transform Types

| Transform | Description | Layers | Platforms |
|-----------|-------------|--------|-----------|
| `1:1_pass_through` | Direct copy, no transformation | L0→L1, L1→L2, L2→L3 | google-skills, linkedin-certifications |
| `extract_achievements_dedupe_by_id` | Extract achievements array, dedupe by ID | L0→L1 | microsoft-learn |
| `combine_streams` | Merge multiple input streams | L1→L2 | (cross-platform) |
| `split_streams` | Split single stream into multiple | L1→L2 | google-developer |
| `compute_display_metrics` | Compute aggregate display metrics | L0→L3 | microsoft-learn |
| `count_streams_separately` | Count each stream independently | L2→L3 | google-developer |
| `parse_csv_combine_retired_flags` | Parse CSV, combine active/retired | L0→L1 | aws-skills |
| `count_active_and_retired` | Count active and retired separately | L1→L3 | aws-skills |
| `extract_milestone_badges_dedupe` | Extract milestone badges, dedupe | L0→L1 | credly |
| `parse_local_learnings_dedupe` | Parse local learnings, dedupe | L0→L1 | google-developer |
| `parse_mhtml_codelabs` | Parse MHTML codelabs export | L0→L1 | google-developer |

## Layer Definitions

### L0_raw - Source Exports
Raw exports from each platform, stored as-is in `for_validation/` or similar directories.

### L1_normalized - Validated & Deduplicated
Platform-specific normalization:
- **Microsoft Learn**: Extract `achievements[]`, dedupe by `achievement_id`
- **Google Skills**: Direct pass-through of parsed HTML
- **AWS Skills**: Parse CSV, combine `status` into `retired` boolean
- **Credly**: Extract `milestone_badges`, dedupe by `badge_id`
- **LinkedIn**: Direct pass-through of parsed HTML
- **Google Developer**: Split into `codelabs` + `local_learnings` streams, each deduplicated

### L2_published - Archives & Linked Data
- **Archive files**: `{platform}-complete.md` (all records), `{platform}-index.md` (summary)
- **Google Developer**: Additional `{platform}-codelabs-complete.md`, `{platform}-local-learnings-complete.md`
- **Cross-platform**: `credentials.jsonld` (Schema.org linked data)

### L3_display - Display Metrics
- **README.md**: Human-readable summary with metrics tables
- **llms.txt**: LLM-friendly index with archive links
- **llms-full.txt**: Consolidated context for large-context LLMs
- **Metrics**: Platform-specific counts (total, active, retired, by category, etc.)

## Cross-Artifact Validation

The `cross_artifact_validator.py` validates that record counts flow correctly across layers using **manifest-declared transforms** (not hardcoded tolerances).

### Validation Rules (from manifest)

| Comparison | Transform | Expected Relationship |
|------------|-----------|----------------------|
| L0 → L1 | `extract_achievements_dedupe_by_id` | L1 ≤ L0 (deduplication) |
| L0 → L1 | `parse_csv_combine_retired_flags` | L1 = L0 (rows preserved) |
| L0 → L1 | `extract_milestone_badges_dedupe` | L1 ≤ L0 (deduplication) |
| L0 → L1 | `parse_mhtml_codelabs` / `parse_local_learnings_dedupe` | L1 ≤ L0 (deduplication) |
| L0 → L1 | `1:1_pass_through` | L1 = L0 |
| L1 → L2 | `combine_streams` | L2 = sum(L1 streams) |
| L1 → L2 | `split_streams` | L2 = L1 per stream |
| L2 → L3 | `compute_display_metrics` | L3 derived from L0/L1 |
| L2 → L3 | `count_streams_separately` | L3 = sum(L2 streams) |

## Manifest Schema

The `dataset_layers.yaml` is validated against Pydantic models in `models/layer_manifest.py`:

```yaml
version: "1.0"
platforms:
  platform-key:
    L0_raw:
      source: "path/to/source"
      artifacts: [...]
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "transform_type"
        params: {...}
      output_records: "field_name"
      output_streams: {...}
    L2_published:
      source_layer: "L1_normalized"
      artifacts: [...]
      transforms: {...}
    L3_display:
      source_layer: "L2_published"
      metrics: [...]
      artifacts: [...]
```

## Running Validation

```bash
# Validate manifest schema and artifact consistency
python validate_manifest.py

# Full cross-artifact validation (requires pipeline outputs)
python cross_artifact_validator.py
```

## Adding a New Platform

1. Add platform entry to `dataset_layers.yaml` with all 4 layers
2. Create/update pipeline script in root (e.g., `update_new_platform.py`)
3. Add `_layer_metadata` emission using `generate_layer_metadata()` from `layer_manifest`
4. Update archiver to handle new platform's L2 artifacts
5. Run `validate_manifest.py` to verify
6. Run pipeline to generate artifacts
7. Run `cross_artifact_validator.py` to verify counts

## Pipeline Scripts

All pipeline scripts follow the same pattern:

```python
from layer_manifest import get_platform_layers, generate_layer_metadata


def main():
    # ... fetch and process data ...

    # Emit layer metadata for validation
    platform_layers = get_platform_layers()["platform-key"]
    metadata = generate_layer_metadata(
        "platform-key",
        {
            "L0_raw": l0_count,
            "L1_normalized": l1_count,
            "L2_published": {"complete": l2_count, "index": 1},
            "L3_display": {"total_badges": l3_count},
        },
    )

    output = {
        "records": records,
        "_layer_metadata": metadata,  # For cross_artifact_validator
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
```

## Generated Artifacts

### Archives (`archives/`)
- `{platform}-complete.md` - Full record listing
- `{platform}-index.md` - Summary with metrics
- Google Developer: `-codelabs-complete.md`, `-local-learnings-complete.md`

### Cross-Platform
- `credentials.jsonld` - Schema.org `ItemList` with `EducationalOccupationalCredential`
- `README.md` - Human-readable dashboard
- `llms.txt` - LLM index with archive links
- `llms-full.txt` - Consolidated context

## Version History

- **v1.0** (2025): Initial 4-layer architecture with 6 platforms, manifest-driven validation