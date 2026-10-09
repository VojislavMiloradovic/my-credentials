# MITIGATION TODO: Baseline Advancement Before Publication Fix

## Issue Summary
Baselines are persisted inside `execute_content_loss_guard()` **before** archive generation, README update, cross-artifact validation, manifest validation, targeted tests, and push. Downstream failures leave baseline describing unpublished data.

## Solution: Option 3 (Hybrid + Verify)
- Move baseline save to **end of pipeline script** (after all local generation)
- Add **GitHub Actions verification step** to confirm baseline matches committed validation data before push

---

## Phase 1: Core Pipeline Changes (Local Generation Safety) ✅ COMPLETE

### Step 1.1: Add `persist_baseline` Parameter to `execute_content_loss_guard()` ✅ DONE
**File**: `loss_guard.py`
**Commit**: `a8fd6759`

### Step 1.2: Move Baseline Generation to End of `PipelineBase.run()` ✅ DONE
**File**: `pipeline_base.py`
**Commit**: `63bcc248`

### Step 1.3: Update Microsoft Learn Override ✅ DONE
**File**: `update_ms_learn.py`
**Commit**: `63bcc248`

### Step 1.4: Verify Google Developer Multi-Stream ✅ DONE (No Code Changes)

### Step 1.5: Fix ruff formatting on MITIGATION_TODO.md ✅ DONE
**Commit**: `27d7b8ac`

---

## Phase 2: GitHub Actions Verification Step ✅ COMPLETE

### Step 2.1: Create Verification Script ✅ DONE
**File**: `scripts/verify_baseline.py`
**Commit**: `dc92c4d1`

### Step 2.2: Add Verification Step to Reusable Workflow ✅ DONE
**File**: `.github/workflows/reusable-update.yml`
**Commit**: `dc92c4d1`

### Step 2.3: Fix ruff formatting on verify_baseline.py ✅ DONE
**Commit**: `a25b4db2`

### Step 2.4: Fix verification script to count unique IDs (matching baseline fingerprint index) ✅ DONE
**File**: `scripts/verify_baseline.py`
**Commit**: `f2703823`
- **LinkedIn**: Count unique extracted IDs (handles duplicate certs in source CSV)
- **Google Developer**: Use full title as ID (not truncated to 50 chars)

---

## Phase 3: Testing & Validation ✅ COMPLETE

### Step 3.1: Simulated Full Pipeline Test ✅ DONE
- All 6 platform pipelines run locally
- Baselines generated at end (not after loss guards)
- Verification passes (0.0% mismatch for all platforms)

### Step 3.2: GitHub Actions Integration Test ✅ DONE
- All 6 platform workflows manually dispatched
- "Verify Baseline Consistency" step passes for all
- Push succeeds, remote has updated baselines

### Step 3.3: Edge Case Verification ✅ DONE
| Scenario | Result |
|----------|--------|
| Fresh clone (no baselines) | First-run logic, baseline created at end |
| Manual baseline deletion | Recreated at end |
| Archive generation failure | Logic verified: baseline only at end |
| Verification failure | Caught at pre-flight JSON check (even earlier!) |
| Push failure / rebase conflict | Logic verified; no concurrent conflict occurred |

### Step 3.4: Cross-Platform Consistency Check ✅ DONE
- Cross-artifact validator manual run: **95/95 checks PASSED**

---

## Phase 4: Cleanup & Documentation ✅ COMPLETE

### Step 4.1: Remove Duplicate Baseline Save in Microsoft Learn ✅ DONE
**File**: `update_ms_learn.py` — Only ONE `generate_provider_baseline()` call at end after `sync_fixtures()`

### Step 4.2: Update Documentation ✅ DONE
- MITIGATION_TODO.md updated with final status
- Code comments in `pipeline_base.py` and `update_ms_learn.py` updated during implementation
- Session handoff not needed (same session continues)

---

## Root Cause of LinkedIn 0.1% Mismatch (RESOLVED)

**Two exact duplicate certifications in LinkedIn CSV export:**
| Certification | License | Count |
|---------------|---------|-------|
| Certificate of completion: Introduction to Claude Cowork | `stgugigxajbf` | 2 |
| Essentials - GenAI Protection | `34cf63a3-9c10-4ce1-8855-67ec2b1eb97d` | 2 |

**Root cause**: Verification script counted **total certifications** (1818) but baseline is a **fingerprint index** (unique by ID = 1816).

**Fix**: Updated `scripts/verify_baseline.py` to count **unique extracted IDs** matching baseline fingerprint index semantics.

---

## Root Cause of Google Developer 1.7% Mismatch (RESOLVED)

**Root cause**: Verification script truncated Google Developer titles to 50 chars, causing false collisions (26 duplicates). Baseline uses **full titles** as keys (1736 unique).

**Fix**: Updated `scripts/verify_baseline.py` to use **full title** as ID for Google Developer.

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

## Commit History Summary

| Commit | Description |
|--------|-------------|
| `a8fd6759` | feat(loss_guard): add persist_baseline parameter |
| `63bcc248` | refactor(pipeline_base, update_ms_learn): move baseline to end |
| `27d7b8ac` | fmt: ruff format MITIGATION_TODO.md |
| `dc92c4d1` | feat(scripts): add verify_baseline.py + ci step |
| `a25b4db2` | fmt: ruff format scripts/verify_baseline.py |
| `a9cd3435` | fix: restore aws-skills baseline after test |
| `cd486294` | chore(aws): auto-update AWS profile... |
| `dc8a30ab` | fix: remove trivial test change from README |
| `d4bd7c03` | docs: finalize MITIGATION_TODO.md with complete Phase 1-4 summary |
| `f2703823` | fix(verify_baseline): count unique IDs matching baseline fingerprint index |

---

## Success Criteria ✅ ALL MET

- [x] Baseline only advances after ALL local generation succeeds
- [x] GitHub Actions verifies baseline consistency before push
- [x] Manual baseline deletion + pipeline run regenerates correctly
- [x] All 6 platform workflows pass
- [x] Cross-artifact validation, manifest validation, targeted tests still run
- [x] No regression in loss guard detection capability
- [x] Multiple defense layers active: pre-flight JSON check → verification step → cross-artifact validation
- [x] **LinkedIn mismatch resolved (0.0%)**
- [x] **Google Developer mismatch resolved (0.0%)**

---

## Verification Results (Final)

| Platform | Baseline | Validation | Mismatch |
|----------|----------|------------|----------|
| microsoft-learn | 4928 | 4928 | 0.0% |
| google-skills | 409 | 409 | 0.0% |
| aws-skills | 1008 | 1008 | 0.0% |
| credly | 728 | 728 | 0.0% |
| linkedin-certifications | 1816 | 1816 | 0.0% |
| google-developer | 1736 | 1736 | 0.0% |

**Total**: 592 tests pass, all workflows green, all ruff checks pass.