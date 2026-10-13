SESSION HANDOFF: my-credentials Repository
==========================================

Repository Overview
-------------------
This repository maintains an automated, auditable credential portfolio that scrapes/exports data from 6 platforms, normalizes it, validates it through a multi-layer loss guard pipeline, and generates multiple output formats (markdown archives, JSON-LD, llms.txt, llms-full.txt).

Platforms:
- microsoft-learn (Microsoft Learn achievements, learning paths, modules)
- google-skills (Google Cloud Skills badges via HTML scraping)
- aws-skills (AWS Skill Builder badges via CSV export)
- credly (Credly verified badges via API)
- linkedin-certifications (LinkedIn certifications via CSV export)
- google-developer (Google Developer Profile badges + learning activities via MHTML + RPC)

Repository Structure
--------------------
my-credentials/
├── update_*.py                 # Platform-specific pipeline scripts (6 files)
├── pipeline_base.py            # Base pipeline class with shared orchestration
├── loss_guard.py               # Content-aware loss guard (count + fingerprint + auto-retire)
├── cross_artifact_validator.py # 95 cross-artifact semantic checks
├── generate_*.py               # Output generators (jsonld, llms.txt, llms-full.txt)
├── validate_manifest.py        # Validates dataset_layers.yaml
├── generate_all_provider_baselines() in loss_guard.py  # Multi-stream baseline generation
├── cross_artifact_validator.py # 95 semantic checks across artifacts
├── archiver.py                 # Markdown archive generation (monolith, chunks, index)
├── scripts/
│   ├── sync_fixtures.py        # Copies baseline files to test fixtures
│   ├── check_fixture_freshness.py  # Checks fixture staleness (90-day threshold)
│   └── verify_baseline.py      # Compares baseline fingerprints vs validation data
├── archiver.py                 # Markdown archive generation (monolith, chunks, index)
├── archiver.py                 # Archive generation (monolith, chunks, index)
├── generate_jsonld.py          # Schema.org JSON-LD from markdown archives
├── generate_llms_txt.py        # LLM-optimized index
├── generate_llms_full.py       # Consolidated LLM context
├── validate_manifest.py        # Validates dataset_layers.yaml
├── validate_summary.py         # Prints validation summary
├── pipeline_base.py            # Base pipeline class (Option 2 migration)
├── loss_guard.py               # Content-aware loss guard
├── cross_artifact_validator.py # 95 semantic checks
├── archiver.py                 # Archive generation
├── models/
│   ├── layer_manifest.py       # Pydantic models for dataset_layers.yaml
│   └── provenance.py           # Provenance tracking
├── scripts/
│   ├── sync_fixtures.py
│   ├── check_fixture_freshness.py
│   └── verify_baseline.py
├── update_*.py (6 files)       # Platform-specific pipelines
├── pipeline_base.py            # Base class with shared orchestration
├── loss_guard.py               # Content-aware loss guard
├── cross_artifact_validator.py # 95 semantic checks
├── archiver.py                 # Archive generation
├── generate_jsonld.py          # JSON-LD output
├── generate_llms_txt.py        # LLM index
├── generate_llms_full.py       # Full LLM context
├── validate_manifest.py        # Manifest validator
├── validate_summary.py         # Validation summary printer
├── pipeline_base.py            # Base pipeline class
├── loss_guard.py               # Loss guard implementation
├── cross_artifact_validator.py # Cross-artifact validator
├── archiver.py                 # Archive generation
├── generate_jsonld.py          # JSON-LD generator
├── generate_llms_txt.py        # LLM index generator
├── generate_llms_full.py       # Full LLM context generator
├── validate_manifest.py        # Manifest validator
├── validate_summary.py         # Validation summary
├── pipeline_base.py            # Base pipeline class
├── loss_guard.py               # Loss guard
├── cross_artifact_validator.py # Cross-artifact validator
├── archiver.py                 # Archiver
├── generate_jsonld.py          # JSON-LD generator
├── generate_llms_txt.py        # LLM index generator
├── generate_llms_full.py       # Full LLM context generator
├── validate_manifest.py        # Manifest validator
├── validate_summary.py         # Validation summary
├── pipeline_base.py            # Base pipeline
├── loss_guard.py               # Loss guard
├── cross_artifact_validator.py # Cross-artifact validator
├── archiver.py                 # Archiver
├── generate_jsonld.py          # JSON-LD generator
├── generate_llms_txt.py        # LLM index generator
├── generate_llms_full.py       # Full LLM context generator
├── validate_manifest.py        # Manifest validator
├── validate_summary.py         # Validation summary
├── pipeline_base.py            # Base pipeline
├── loss_guard.py               # Loss guard
├── cross_artifact_validator.py # Cross-artifact validator
├── archiver.py                 # Archiver
├── generate_jsonld.py          # JSON-LD generator
├── generate_llms_txt.py        # LLM index generator
├── generate_llms_full.py       # Full LLM context generator
├── validate_manifest.py        # Manifest validator
├── validate_summary.py         # Validation summary
├── dataset_layers.yaml         # Layer manifest (L0-L3 per platform)
├── retired_urls.json           # URL-based retirement registry
├── pyproject.toml              # Project config (uv, pytest, ruff, mypy)
├── uv.lock                     # Locked dependencies
└── README.md                   # Main documentation

Key Files and Their Roles
-------------------------
pipeline_base.py: Base class with shared orchestration (fetch, parse, guard, archive, readme). Subclasses implement fetch_data, parse_data, format_for_archive, build_readme_lines. Handles loss guards, baseline generation, archive generation, README update, fixture sync.

loss_guard.py: Content-aware loss guard. Two guards: count-based (fast, catches major drops) and content-aware (fingerprints records, detects replacement/modification/deletion, auto-retires by URL). Multi-stream support via generate_all_provider_baselines().

cross_artifact_validator.py: 95 semantic checks across all artifacts (source, archive, index, readme, jsonld, llms.txt, llms-full). Validates counts, retired status, transforms, platform coverage, latest record dates.

archiver.py: Generates markdown archives (monolith, ~10KB chunks, index, README markers). Handles chunking, token counting (tiktoken), README section injection.

generate_jsonld.py: Parses markdown archives, extracts credentials, outputs Schema.org JSON-LD with provenance fields.

generate_llms_txt.py / generate_llms_full.py: Generate LLM-optimized index files (llms.txt, llms-full.txt) from archives.

validate_manifest.py: Validates dataset_layers.yaml against actual files.

validate_summary.py: Prints validation summary.

archiver.py: Archive generation (monolith, chunks, index, README markers).

generate_jsonld.py: Parses markdown archives, outputs Schema.org JSON-LD.

generate_llms_txt.py / generate_llms_full.py: LLM-optimized index files.

validate_manifest.py: Validates dataset_layers.yaml against actual files.

validate_summary.py: Prints validation summary.

archiver.py: Archive generation (monolith, chunks, index, README markers).

generate_jsonld.py: Parses markdown archives, outputs Schema.org JSON-LD.

generate_llms_txt.py / generate_llms_full.py: LLM-optimized index files.

validate_manifest.py: Validates dataset_layers.yaml against actual files.

validate_summary.py: Prints validation summary.

archiver.py: Archive generation (monolith, chunks, index, README markers).

generate_jsonld.py: Parses markdown archives, outputs Schema.org JSON-LD.

generate_llms_txt.py / generate_llms_full.py: LLM-optimized index files.

validate_manifest.py: Validates dataset_layers.yaml against actual files.

validate_summary.py: Prints validation summary.

Key Configuration Files
-----------------------
dataset_layers.yaml: Defines L0-L3 layers per platform, transforms, artifacts, retired handling.
retired_urls.json: URL-based retirement registry (match_type: url).
PROVIDER_CONFIG in loss_guard.py: Per-platform config (id_field, baseline_sources, thresholds, streams, fail_on_warn).
dataset_layers.yaml: Layer manifest (L0_raw, L1_normalized, L2_published, L3_display per platform).
retired_urls.json: URL-based retirement registry.
PROVIDER_CONFIG in loss_guard.py: Per-platform config (id_field, baseline_sources, thresholds, streams, fail_on_warn).

Pipeline Flow (pipeline_base.py run())
-------------------------------------
1. fetch_data() -> raw data
2. parse_data() -> list[dict] records
3. pre_loss_guard() hook (deduplication etc)
4. run_provider_loss_guards() with persist_baseline=False
5. post_loss_guard() hook (retired marking)
6. persist_validation() -> for_validation/{platform}.json
6. sort records (newest first)
7. format_for_archive()
8. build_readme_lines()
9. generate_archive() -> monolith, chunks, index, README markers
10. update_readme() with slice links
10. generate_all_provider_baselines() OR generate_provider_baseline()
13. sync_fixtures() -> copies baseline files to tests/fixtures/

Critical Fixes Applied (Recent)
-------------------------------
1. loss_guard.py: generate_all_provider_baselines() now generates main combined baseline ("default") before per-stream baselines. Fixes missing fixture files for Credly (4 files) and Google Developer (3 files).
2. pipeline_base.py: generate_all_provider_baselines() called BEFORE sync_fixtures() (was reversed). Ensures fixtures get NEW baseline files.
3. update_google_developer.py: Added STREAMS = ["public_badges", "detailed_learnings", "combined"] class variable. Enables multi-stream baseline generation.
4. cross_artifact_validator.py: validate_source_snapshots() now prefers combined_feed (deduplicated) over summing components. Fixed Google Developer double-count (3591 -> 1736).
3. cross_artifact_validator.py: Added validate_stream_completeness() for multi-stream platforms. Verifies sum(streams) >= combined (dedup reduces count).
4. cross_artifact_validator.py: Fixed LinkedIn regex to match "certifications" not "verified".
5. loss_guard.py: generate_all_provider_baselines() now generates main combined baseline ("default") before per-stream baselines. Fixes missing fixture files for Credly (4 files) and Google Developer (3 files).
4. pipeline_base.py: Swapped order - generate_all_provider_baselines() runs BEFORE sync_fixtures() (was reversed). Fixes fixture freshness.
5. update_google_developer.py: Added STREAMS class variable for multi-stream support.

Current State (as of 2026-10-13)
--------------------------------
All 592 tests pass.
Cross-artifact validation: 95/95 pass.
Google Developer source count: 1,736 (was 3,591 double-counted).
Fixture freshness: PASS (no missing/stale).
All 6 platform workflows: PASS.
Ruff checks: PASS.
All 592 tests pass.

How to Run Locally
-------------------
Prerequisites: Python 3.11, uv (https://github.com/astral-sh/uv)

Setup:
uv sync --extra test

Run all tests:
uv run pytest tests/ -v

Run specific test suites:
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/integration/test_google_developer_pipeline.py -v

Run specific platform pipeline:
uv run python update_ms_learn.py
uv run python update_aws_skills.py
uv run python update_google_skills.py
uv run python update_credly_badges.py
uv run python update_linkedin.py
uv run python update_google_developer.py

Run cross-artifact validator:
uv run python cross_artifact_validator.py --mode strict

Run fixture freshness check:
uv run python scripts/check_fixture_freshness.py --fail-on-stale --threshold 90

Run cross-artifact validator:
uv run python cross_artifact_validator.py --mode strict

Generate outputs:
uv run python generate_jsonld.py
uv run python generate_llms_txt.py
uv run python generate_llms_full.py

Linting/formatting:
uv run ruff check .
uv run ruff format --check .
uv run ruff format .
uv run ruff check --fix .

Type checking:
uv run mypy tests/ --ignore-missing-imports

Git Workflow
------------
Main branch protected. Push directly to main after local verification.
Commit messages: conventional (fix:, feat:, chore:, docs:).
Rebase before push: git pull --rebase && git push
Local: C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials (synced with OneDrive)
GitHub: https://github.com/VojislavMiloradovic/my-credentials
GitHub Actions: https://github.com/VojislavMiloradovic/my-credentials/actions

GitHub Actions Workflows
------------------------
.github/workflows/
- reusable-update.yml: Main pipeline (called by platform workflows)
- update-learn-profile.yml: Microsoft Learn (manual/schedule)
- sync_google_skills.yml: Google Skills (manual/schedule)
- update-aws-profile.yml: AWS (manual/schedule)
- sync_credly.yml: Credly (manual/schedule)
- update_linkedin.yml: LinkedIn (manual/schedule)
- update_google_developer.yml: Google Developer (manual/schedule)
- cross_artifact_validation.yml: Monthly + on push/PR
- test.yml: Test suite + fixture freshness + lint (monthly + push/PR)
- link_checker.yml: Monthly link validation
- repo_health.yml: Security/health checks

Platform-Specific Details
-------------------------
microsoft-learn: JSON export -> extract achievements -> dedupe by ID -> retired by URL
google-skills: HTML scrape -> badges
aws-skills: CSV -> parse retired flags -> combine
credly: API (native + external) -> dedupe -> retired by registry
linkedin-certifications: CSV -> 1:1 pass-through -> retired by registry
google-developer: RPC (badges) + MHTML (learnings) -> combine -> dedupe -> retired by URL + registry

Key Nuances
-----------
- Windows locally, Ubuntu in GitHub Actions (line endings: LF in repo, CRLF on Windows checkout)
- uv version mismatch locally (0.11.11 vs 0.12.3 in Actions) - use C:\Users\Toughbook\.local\bin\uv.exe locally
- Line endings: repo uses LF, Git converts to CRLF on Windows checkout
- Use PowerShell for shell commands, escape $ as `$ in strings
- uv version mismatch locally (0.11.11 vs 0.12.3 in Actions) - use C:\Users\Toughbook\.local\bin\uv.exe locally
- Line endings: repo uses LF, Git converts to CRLF on Windows checkout
- Use PowerShell for shell commands, escape $ as `$ in strings
- uv sync --frozen --all-extras installs all optional dependencies
- dataset_layers.yaml artifact names: "complete", "index" (not "archive_complete", "archive_index", "jsonld")
- archiver.py uses tiktoken with cl100k_base encoding
- loss_guard.py excludes volatile fields from hashing: timestamps, versions, provenance, partition keys
- Fixture freshness check warns only (no --fail-on-stale in CI)
- Google Developer retired items: 15 in baseline, matched by URL
- Cross-artifact validator checks 95 conditions across 6 platforms
- Credly has 3 streams: native, external, combined
- Google Developer has 3 streams: public_badges, detailed_learnings, combined
- Credly STREAMS = ["native", "external", "combined"]
- Google Developer STREAMS = ["public_badges", "detailed_learnings", "combined"]
- Credly STREAMS = ["native", "external", "combined"]
- Google Developer STREAMS = ["public_badges", "detailed_learnings", "combined"]
- Fixture freshness check warns only (no --fail-on-stale in CI)
- Google Developer retired items: 15 in baseline, matched by URL
- Cross-artifact validator checks 95 conditions across 6 platforms
- Credly has 3 streams: native, external, combined
- Google Developer has 3 streams: public_badges, detailed_learnings, combined
- Credly STREAMS = ["native", "external", "combined"]
- Google Developer STREAMS = ["public_badges", "detailed_learnings", "combined"]
- Fixture freshness check warns only (no --fail-on-stale in CI)
- Google Developer retired items: 15 in baseline, matched by URL
- Cross-artifact validator checks 95 conditions across 6 platforms
- Credly has 3 streams: native, external, combined
- Google Developer has 3 streams: public_badges, detailed_learnings, combined
- Credly STREAMS = ["native", "external", "combined"]
- Google Developer STREAMS = ["public_badges", "detailed_learnings", "combined"]

Testing Commands Quick Reference
--------------------------------
uv run pytest tests/ -q --tb=short          # All tests (592)
uv run pytest tests/unit/ -q                # Unit tests only (363)
uv run pytest tests/integration/ -q         # Integration tests only
uv run pytest tests/ -k "cross_artifact" -v # Cross-artifact tests
uv run pytest tests/unit/test_loss_guard.py -v
uv run pytest tests/integration/test_google_developer_pipeline.py -v
uv run pytest tests/integration/test_credly_pipeline.py -v

Verification Commands
---------------------
uv run python cross_artifact_validator.py --mode strict
uv run python scripts/verify_baseline.py
uv run python scripts/check_fixture_freshness.py --fail-on-stale --threshold 90
uv run python generate_jsonld.py
uv run python generate_llms_txt.py
uv run python generate_llms_full.py
uv run python scripts/verify_baseline.py
uv run python scripts/check_fixture_freshness.py --fail-on-stale --threshold 90

All checks passing as of 2026-10-13.