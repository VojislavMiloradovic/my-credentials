# MITIGATION TODO: Manifest Not Operational Source of Truth

## Issue Summary
The manifest (`dataset_layers.yaml`) is not the operational source of truth. Three generators (`generate_llms_full.py`, `generate_llms_txt.py`, `generate_jsonld.py`) call `get_platform_layers()` without required `platform` argument, causing `TypeError` that is silently caught and falls back to hardcoded duplicate configs. The manifest is decorative, not operational.

---

## Solution: Option 1 + 4 (Fix Manifest API + Fail Fast)
1. Add `get_all_platform_layers()` to `layer_manifest.py`
2. Update all three generators to use it properly
3. Remove silent fallbacks — fail fast on manifest errors
4. Remove duplicate hardcoded configs

---

## Phase 1: Manifest API Fix (Foundation)

### Step 1.1: Add `get_all_platform_layers()` to `layer_manifest.py`
**File**: `models/layer_manifest.py`
**Change**: Add function returning all platforms' layers
```python
def get_all_platform_layers() -> dict[str, PlatformLayers]:
    """Get layer definitions for ALL platforms."""
    return load_manifest().platforms
```
**Commit**: Single file, additive only
**Risk**: Zero — purely additive

### Step 1.2: Add helper `get_platforms_with_l2_artifact(artifact: str)`
**File**: `models/layer_manifest.py`
**Change**: Add targeted query function
```python
def get_platforms_with_l2_artifact(artifact: str) -> list[str]:
    """Return platform keys with specific artifact in L2_published."""
    manifest = load_manifest()
    return [
        p for p, layers in manifest.platforms.items()
        if hasattr(layers, "L2_published") and artifact in getattr(layers.L2_published, "artifacts", [])
    ]
```
**Commit**: Single file, additive only
**Risk**: Zero — purely additive

---

## Phase 2: Generator Updates (One at a Time)

### Step 2.1: Update `generate_llms_full.py`
**File**: `generate_llms_full.py`
**Changes**:
- Replace `_get_monolith_configs()` with manifest-driven version using `get_platforms_with_l2_artifact("archive_complete")`
- Remove `_FALLBACK_MONOLITH_CONFIGS` constant
- Remove `try/except` fallback — let manifest errors propagate
**Commit**: Single file
**Risk**: Low — single generator, easy to verify

### Step 2.2: Update `generate_llms_txt.py`
**File**: `generate_llms_txt.py`
**Changes**:
- Replace `_get_monolith_configs()` with manifest-driven version
- Replace `_get_slice_configs()` with manifest-driven version
- Remove both fallback constants
- Remove `try/except` fallbacks
**Commit**: Single file
**Risk**: Low — single generator

### Step 2.3: Update `generate_jsonld.py`
**File**: `generate_jsonld.py`
**Changes**:
- Replace fallback platform map with manifest-driven version using `get_platforms_with_l2_artifact("jsonld")`
- Remove `_FALLBACK_PLATFORM_MAP` constant
- Remove `try/except` fallback — let manifest errors propagate
**Commit**: Single file
**Risk**: Low — single generator

---

## Phase 3: Validation & Cleanup

### Step 3.1: Verify All Generators Work with Manifest
**Method**: Run each generator locally
```bash
uv run python generate_llms_full.py
uv run python generate_llms_txt.py
uv run python generate_jsonld.py
```
**Verify**: Output files match expected format, no errors

### Step 3.2: Run Full Test Suite
**Command**: `uv run pytest tests/ -v`
**Expected**: All 592 tests pass
**If failures**: Fix any tests that relied on silent fallbacks

### Step 3.2: Run Ruff Checks
**Command**: `uv run ruff check . && uv run ruff format --check .`
**Expected**: All pass

---

## Phase 4: GitHub Actions Integration Test

### Step 4.1: Trigger Platform Workflows
**Action**: Manually dispatch each platform workflow
- `update-learn-profile.yml`
- `sync_google_skills.yml`
- `update-aws-profile.yml`
- `sync_credly.yml`
- `update_linkedin.yml`
- `update_google_developer.yml`

### Step 4.2: Verify Generation Steps Pass
**Check each workflow**:
- `Generate JSON-LD` step passes
- `Generate llms.txt` step passes
- `Generate llms-full.txt` step passes
- No fallback warnings in logs

### Step 4.3: Cross-Artifact Validation
**Manual dispatch**: `cross_artifact_validation.yml`
**Expected**: 95/95 checks pass

---

## Phase 5: Documentation & Removal of Duplicates

### Step 5.1: Remove Fallback Constants (Already Done in Phase 2)
**Verify**: No `_FALLBACK_*` constants remain in generators

### Step 5.2: Update Internal Documentation
**Files**: Any internal docs referencing fallbacks
**Action**: Update to reflect manifest-driven approach

---

## Rollback Plan (Per Step)

| Step | Rollback |
|------|----------|
| 1.1 | Remove `get_all_platform_layers()` |
| 1.2 | Remove `get_platforms_with_l2_artifact()` |
| 2.1 | Revert `generate_llms_full.py` |
| 2.2 | Revert `generate_llms_txt.py` |
| 2.3 | Revert `generate_jsonld.py` |
| 3.x | No code changes |

All steps independently revertible. No data migration.

---

## Success Criteria

- [ ] `get_all_platform_layers()` added to `layer_manifest.py`
- [ ] `get_platforms_with_l2_artifact()` added to `layer_manifest.py`
- [ ] `generate_llms_full.py` uses manifest, no fallbacks
- [ ] `generate_llms_txt.py` uses manifest, no fallbacks
- [ ] `generate_jsonld.py` uses manifest, no fallbacks
- [ ] All 592 tests pass
- [ ] All 6 platform workflows pass
- [ ] Cross-artifact validation: 95/95 pass
- [ ] No `_FALLBACK_*` constants in generators
- [ ] Manifest is single source of truth for platform configs

---

## Next Actions

1. Begin **Phase 1, Step 1.1** when ready
2. Each step = one commit + push
3. Verify after each step before proceeding

---

## Estimated Effort

| Phase | Files | Complexity |
|-------|-------|------------|
| 1 | 1 | Low |
| 2 | 3 | Medium |
| 3 | 0 (verification) | Low |
| 4 | 0 (CI) | Medium |
| 5 | 0 (cleanup) | Low |

Total: ~4 files changed, ~100 lines modified