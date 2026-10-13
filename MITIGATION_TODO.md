# Mitigation Plan: Provider-Specific Fingerprint Schemas

**Objective**: Address the content fingerprint weakness where dates, verification URLs, issuer names, and retirement state are excluded from loss guard hashes, allowing silent metadata drift.

**Approach**: Implement declarative, provider-specific fingerprint schemas (Option B) with schema versioning (Option D) to enable safe migration.

---

## Phase 1: Foundation (Core Infrastructure)

### 1.1 Create Fingerprint Schema Definitions
- New module: `models/fingerprint_schemas.py`
- Define `FINGERPRINT_SCHEMAS` dictionary with per-platform field lists
- Each schema specifies:
  - Fields to include in hash: title, date, issuer, category, canonical verification URL, retired
  - Canonical issuer for platforms with fixed issuers (Microsoft, AWS, Google Cloud)
  - ID field or custom ID strategy
- Define `CURRENT_FINGERPRINT_SCHEMA_VERSION = 2`

### 1.2 Modify Content Hash Function
- Update `compute_content_hash()` in `loss_guard.py`
- Accept optional schema parameter
- Schema-driven mode: hash only declared fields (with canonical issuer injection)
- Fallback mode: current global `VOLATILE_FIELDS` exclusion for unknown platforms

### 1.3 Version Baseline Format
- Update `save_baseline()` to include `fingerprint_schema_version` in output JSON
- Update `load_baseline()` to return `None` on version mismatch (forces regeneration)
- Baseline JSON structure adds:
  ```json
  "fingerprint_schema_version": 2
  ```

### 1.4 Wire Schema Into Baseline Generation
- Update `build_fingerprint_index()` to look up and pass schema by platform
- Update `generate_all_provider_baselines()` to propagate schema
- Ensure multi-stream providers (google-developer, credly) use correct schema per stream

---

## Phase 2: Pipeline Integration (Sequential, One Platform at a Time)

### 2.1 Google Developer
- Schema already protected for date changes via title+date ID strategy
- Add fields: description, source, retired
- Run pipeline and verify

### 2.2 Microsoft Learn
- Canonical issuer: "Microsoft"
- Fields: title, grantedOn, category, verify_url, retired
- Run pipeline and verify

### 2.3 Credly
- Fields: title, date, issuer_name, type (as category), verify_url, retired
- Run pipeline and verify

### 2.4 AWS Skills
- Fields: title, date, issuer_name, type (as category), verify_url, retired
- Run pipeline and verify

### 2.5 Google Skills
- Fields: title, date, issuer_name, type (as category), verify_url, retired
- Run pipeline and verify

### 2.6 LinkedIn Certifications
- Map: authority → issuer, issued → date, license → ID
- Handle missing verify_url gracefully
- Run pipeline and verify

---

## Phase 3: Validation & Sync

### 3.1 Sync Fixtures
- Run `scripts/sync_fixtures.py` to propagate new baselines to test fixtures

### 3.2 Fixture Freshness Check
- Run `scripts/check_fixture_freshness.py --threshold 90`
- Confirm no stale fixtures

### 3.3 Full Test Suite
- Run `pytest tests/ -q`
- Target: all 592 tests pass

### 3.4 Cross-Artifact Validation
- Run `cross_artifact_validator.py --mode strict`
- Target: all platform-specific checks PASS

### 3.5 Full Pipeline Execution
- Execute all 6 platform pipelines sequentially
- Verify each completes without error
- Confirm new baselines generated with schema version 2

---

## Phase 4: Cleanup & Documentation

### 4.1 Deprecate Global VOLATILE_FIELDS
- Retain as fallback only for unknown platforms
- Document that schemas are now primary mechanism

### 4.2 Update Architecture Documentation
- Add fingerprint schema section to relevant docs
- Document migration behavior (auto-regeneration on version bump)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Baseline invalidation on schema bump | Schema version in baseline triggers auto-regeneration on load |
| Field missing in some records | Schema fields optional; hash only present fields |
| Pipeline fails mid-run | Each platform independent; run sequentially |
| Cross-artifact validation breaks | Schema only affects loss guard; validation reads normalized JSON |
| Missing fields in source data | Canonical issuer injection; optional schema fields |

---

## Rollback Procedure

If any platform fails:
1. Restore `loss_guard.py` and `models/fingerprint_schemas.py` from git
2. Restore `for_validation/*baseline.json` and `tests/fixtures/*/baseline.json`
3. Re-run affected pipelines → old baselines regenerate automatically

---

## Success Criteria

- All 6 pipelines execute without error
- All 592 tests pass
- Cross-artifact validation: all platform-specific checks PASS
- Fixture freshness: no stale fixtures
- Baselines contain `fingerprint_schema_version: 2`
- Silent metadata drift now detected (date corrections, issuer changes, URL changes, retirement state)

---

## Files to Modify

| File | Purpose |
|------|---------|
| `models/fingerprint_schemas.py` | New — schema definitions and version constant |
| `loss_guard.py` | Core logic: hash function, baseline I/O, index building |
| `models/__init__.py` | Export new symbols |

---

## Field Mapping Reference (Per Platform)

| Platform | Title | Date | Issuer | Category | Verify URL | Retired | ID Strategy |
|----------|-------|------|--------|----------|------------|---------|-------------|
| microsoft-learn | ✅ | grantedOn | Microsoft (fixed) | ✅ category | ✅ url | ✅ | id_field=id |
| credly | ✅ | date/issued_at | ✅ issuer_name | ✅ type | ✅ verify_url | ✅ | id_field=id |
| aws-skills | ✅ | date/issued_at | ✅ issuer_name | ✅ type | ✅ verify_url | ✅ | id_field=id |
| google-skills | ✅ | date/issued_at | ✅ issuer_name | ✅ type | ✅ verify_url | ✅ | id_field=id |
| linkedin-certifications | ✅ name | issued | ✅ authority | ❌ | ✅ url (nullable) | ✅ | id_field=license |
| google-developer (public) | ✅ | ✅ date | Google (fixed) | ❌ | ❌ | ✅ | title_date_hash |
| google-developer (detailed) | ✅ | ✅ date | Google (fixed) | ❌ | ✅ url | ✅ | title_date_hash |