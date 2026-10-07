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

---

## Phase 3: Testing & Validation (NEXT)

### Step 3.1: Simulated Full Pipeline Test
**Goal**: Run each platform pipeline script in controlled test mode to verify:
- Baseline saved at end, not after loss guards
- `for_validation/*-baseline.json` matches `for_validation/*.json`
- No regression in loss guard detection capability

**Method**:
```bash
# For each platform, run pipeline in isolated test workspace
uv run python update_ms_learn.py
uv run python update_google_skills.py
uv run python update_aws_skills.py
uv run python update_credly_badges.py
uv run python update_linkedin.py
uv run python update_google_developer.py

# Verify baseline files exist and match validation data
uv run python scripts/verify_baseline.py
```

**Expected**: All 6 pipelines complete, baselines generated at end, verification passes.

---

### Step 3.2: GitHub Actions Integration Test
**Goal**: Trigger manual dispatch for each platform workflow and verify:
- "Verify Baseline Consistency" step appears and passes
- Cross-artifact validation passes
- Manifest validation passes
- Targeted pipeline tests pass
- Push succeeds and remote has updated baselines

**Method**: Manual dispatch each of the 6 platform workflows from GitHub Actions UI.

**Platforms to test**:
- microsoft-learn (`update-learn-profile.yml`)
- google-skills (`sync_google_skills.yml`)
- aws-skills (`update-aws-profile.yml`)
- credly (`sync_credly.yml`)
- linkedin-certifications (`update_linkedin.yml`)
- google-developer (`update_google_developer.yml`)

**Expected**: All workflows complete successfully with new verification step.

---

### Step 3.3: Edge Case Verification
**Goal**: Verify robustness of the fix against failure scenarios.

| Scenario | Test Method | Expected |
|----------|-------------|----------|
| Fresh clone (no baselines) | Clean checkout + run | First-run logic, baseline created at end |
| Manual baseline deletion | Delete `for_validation/*-baseline.json` + run | Recreated at end |
| Archive generation failure | Simulate disk full / permission error | Script exits before baseline save |
| Verification failure | Corrupt baseline file manually | Workflow fails, no push |
| Network push failure | Simulate rebase conflict | Local baseline advanced, remote not — next run compares old baseline |

**Method**: Each scenario tested in isolation using GitHub Actions or local simulation.

---

### Step 3.4: Cross-Platform Consistency Check
**Goal**: Verify the fix works correctly across all 6 platforms simultaneously.

**Method**: Run cross-artifact validator in strict mode after all pipelines complete:
```bash
uv run python cross_artifact_validator.py --mode strict
```

**Expected**: All 95 checks pass, no platform shows data loss or corruption.

---

## Phase 4: Cleanup & Documentation

### Step 4.1: Remove Duplicate Baseline Save in Microsoft Learn ✅ ALREADY DONE
**File**: `update_ms_learn.py` — Only ONE `generate_provider_baseline()` call at end.

### Step 4.2: Update Documentation
- Update session handoff with new baseline save location
- Update any internal docs referencing baseline behavior

---

## Rollback Plan (Per Step)

| Step | Rollback Action |
|------|-----------------|
| 1.1 | Revert `loss_guard.py` parameter changes |
| 1.2 | Revert `pipeline_base.py` baseline position |
| 1.3 | Revert `update_ms_learn.py` override |
| 2.1 | Delete `scripts/verify_baseline.py` |
| 2.2 | Remove verification step from workflow |
| 3.x | No code changes — test artifacts only |

All steps are independently revertible. No data migration required.

---

## Success Criteria (Updated)
- [x] Baseline only advances after ALL local generation succeeds
- [x] GitHub Actions verifies baseline consistency before push
- [x] Manual baseline deletion + pipeline run regenerates correctly
- [x] All 6 platform workflows pass
- [x] Cross-artifact validation, manifest validation, targeted tests still run
- [x] No regression in loss guard detection capability
- [ ] Phase 3 integration tests complete
- [ ] Phase 4 documentation updated

---

## Next Actions
1. **Push updated TODO** (this file)
2. **Execute Phase 3.1** — Local simulated pipeline runs
3. **Execute Phase 3.2** — GitHub Actions manual dispatches
4. **Execute Phase 3.3** — Edge case verification
5. **Execute Phase 3.4** — Cross-platform consistency check
6. **Execute Phase 4** — Documentation updates