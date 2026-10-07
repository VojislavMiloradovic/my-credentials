# MITIGATION TODO: Baseline Advancement Before Publication Fix

## Issue Summary
Baselines are persisted inside `execute_content_loss_guard()` **before** archive generation, README update, cross-artifact validation, manifest validation, targeted tests, and push. Downstream failures leave baseline describing unpublished data.

## Solution: Option 3 (Hybrid + Verify)
- Move baseline save to **end of pipeline script** (after all local generation)
- Add **GitHub Actions verification step** to confirm baseline matches committed validation data before push

---

## Phase 1: Core Pipeline Changes (Local Generation Safety)

### Step 1.1: Add `persist_baseline` Parameter to `execute_content_loss_guard()` ✅ DONE
**File**: `loss_guard.py`

**Changes**:
- Add `persist_baseline: bool = False` parameter to `execute_content_loss_guard()`
- Gate `save_baseline()` call behind `if persist_baseline:`
- Update `run_provider_loss_guards()` to accept and pass through `persist_baseline`
- Ensure `generate_provider_baseline()` and `generate_all_provider_baselines()` still work when called explicitly

**Verification**: All existing tests pass. Loss guard runs without saving baseline when `persist_baseline=False`.

**Commit Message**: `feat(loss_guard): add persist_baseline parameter to control baseline persistence`

---

### Step 1.2: Move Baseline Generation to End of `PipelineBase.run()` ✅ DONE
**File**: `pipeline_base.py`

**Changes**:
- In `run()`: change `run_provider_loss_guards(..., persist_baseline=False)`
- Remove `generate_provider_baseline(records, self.PLATFORM_NAME)` call after loss guards (~line 251)
- Add `generate_provider_baseline(records, self.PLATFORM_NAME)` after `self.sync_fixtures()` (~line 280)

**Verification**: 
- Run pipeline script → baseline NOT saved after loss guards
- Baseline IS saved after archive/README/fixtures complete
- All 6 platform pipelines still run without error

**Commit Message**: `refactor(pipeline_base): move baseline generation to end of pipeline run`

---

### Step 1.3: Update Microsoft Learn Override ✅ DONE
**File**: `update_ms_learn.py`

**Changes**:
- In `MicrosoftLearnPipeline.run()`: change `run_provider_loss_guards(..., persist_baseline=False)`
- Move `generate_provider_baseline()` call to after `self.sync_fixtures()`
- Remove duplicate baseline save (currently saves twice)

**Verification**: Microsoft Learn pipeline runs, baseline saved once at end.

**Commit Message**: `fix(update_ms_learn): align baseline save with base class flow`

---

### Step 1.4: Verify Google Developer Multi-Stream ✅ DONE (No Code Changes)
**File**: `update_google_developer.py` (no changes needed — uses base `run()`)

**Verification**: 
- Google Developer pipeline runs
- All 3 streams (`public_badges`, `detailed_learnings`, `combined`) pass loss guards with `persist_baseline=False`
- Baseline saved once at end for combined stream

**Commit Message**: `test: verify google-developer multi-stream baseline flow` (no code changes)

---

## Phase 2: GitHub Actions Verification Step

### Step 2.1: Create Verification Script
**New File**: `scripts/verify_baseline.py`

**Purpose**: Compare `for_validation/{platform}-baseline.json` fingerprint count vs `for_validation/{platform}.json` record count. Fail if mismatch > 5%.

**Implementation**:
```python
#!/usr/bin/env python
"""Verify baseline fingerprints match validation data records."""
import json, os, sys
from pathlib import Path

VALIDATION_DIR = "for_validation"
THRESHOLD = 0.05

PLATFORMS = [
    "microsoft-learn", "google-skills", "aws-skills",
    "credly", "linkedin-certifications", "google-developer"
]

def count_baseline_fingerprints(platform):
    p = Path(VALIDATION_DIR) / f"{platform}-baseline.json"
    if not p.exists(): return 0
    return len(json.load(open(p)).get("fingerprints", {}))

def count_validation_records(platform):
    for fname in [f"{platform}.json", f"{platform}-baseline.json"]:
        p = Path(VALIDATION_DIR) / fname
        if p.exists():
            data = json.load(open(p))
            total = 0
            for k in ["combined_feed", "achievements", "badges", "credentials",
                      "public_badges", "detailed_learnings", "verifiable_credentials"]:
                if k in data and isinstance(data[k], list):
                    total += len([r for r in data[k] if isinstance(r, dict)])
            return total
    return 0

def main():
    failed = False
    for platform in PLATFORMS:
        b = count_baseline_fingerprints(platform)
        v = count_validation_records(platform)
        if b == 0 and v == 0:
            print(f"  {platform}: SKIP")
            continue
        if b == 0:
            print(f"  {platform}: FAIL - baseline missing, validation has {v}")
            failed = True
            continue
        mismatch = abs(b - v) / max(b, v)
        status = "FAIL" if mismatch > THRESHOLD else "OK"
        print(f"  {platform}: {status} - baseline={b}, validation={v}, mismatch={mismatch:.1%}")
        if status == "FAIL": failed = True
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
```

**Verification**: Run locally → passes with current data.

**Commit Message**: `feat(scripts): add verify_baseline.py for post-validation consistency check`

---

### Step 2.2: Add Verification Step to Reusable Workflow
**File**: `.github/workflows/reusable-update.yml`

**Location**: After "Run Manifest Validation (Strict Mode)", before "Validate Artifact Paths"

**New Step**:
```yaml
      # Strategy 4: Baseline Consistency Verification
      - name: Verify Baseline Consistency
        run: uv run python scripts/verify_baseline.py
```

**Verification**: 
- Trigger workflow manually for one platform
- "Verify Baseline Consistency" step appears and passes
- Push succeeds

**Commit Message**: `ci(reusable-update): add baseline consistency verification step`

---

## Phase 3: Testing & Validation

### Step 3.1: Simulated Full Pipeline Test
- Run each platform pipeline script in test mode
- Verify baseline saved at end, not after loss guards
- Verify `for_validation/*-baseline.json` matches `for_validation/*.json`

### Step 3.2: GitHub Actions Integration Test
- Manual dispatch each platform workflow
- Confirm all steps pass including new verification
- Confirm push succeeds and remote has updated baselines

### Step 3.3: Edge Case Verification
| Scenario | Test Method | Expected |
|----------|-------------|----------|
| Fresh clone (no baselines) | Clean checkout + run | First-run logic, baseline created at end |
| Manual baseline deletion | Delete `for_validation/*-baseline.json` + run | Recreated at end |
| Archive generation failure | Simulate disk full / permission error | Script exits before baseline save |
| Verification failure | Corrupt baseline file manually | Workflow fails, no push |

---

## Phase 4: Cleanup & Documentation

### Step 4.1: Remove Duplicate Baseline Save in Microsoft Learn
**File**: `update_ms_learn.py`
- Ensure only ONE `generate_provider_baseline()` call (at end after `sync_fixtures`)

### Step 4.2: Update Documentation
- Update any internal docs referencing baseline save location
- Update session handoff if needed

---

## Rollback Plan (Per Step)

| Step | Rollback Action |
|------|-----------------|
| 1.1 | Revert `loss_guard.py` parameter changes |
| 1.2 | Revert `pipeline_base.py` baseline position |
| 1.3 | Revert `update_ms_learn.py` override |
| 2.1 | Delete `scripts/verify_baseline.py` |
| 2.2 | Remove verification step from workflow |

All steps are independently revertible. No data migration required.

---

## Commit Strategy
Each step above = **one commit + push**. Pipelines remain operational after each step.

**Order**: 1.1 → 1.2 → 1.3 → (verify 1.4) → 2.1 → 2.2 → 3.x → 4.x

---

## Success Criteria
- [x] Baseline only advances after ALL local generation succeeds
- [ ] GitHub Actions verifies baseline consistency before push
- [ ] Manual baseline deletion + pipeline run regenerates correctly
- [ ] All 6 platform workflows pass
- [ ] Cross-artifact validation, manifest validation, targeted tests still run
- [ ] No regression in loss guard detection capability