# MITIGATION TODO: Google Developer Source Counting Double-Count & Per-Stream Validation

## Issue Summary
The cross-artifact validator double-counts Google Developer credentials by summing `combined_feed` (deduplicated union) + `public_badges` + `detailed_learnings` = 3,591 instead of using the deduplicated `combined_feed` (1,736). Additionally, per-stream completeness is not validated.

---

## Solution: Option 3 — Fix Source Counting + Add Per-Stream Validation

1. Fix `validate_source_snapshots()` to prefer `combined_feed` when present
2. Add `validate_stream_completeness()` for multi-stream platforms
3. Wire into validation pipeline

---

## Phase 1: Fix Source Counting (Step 1) 🟡 IN PROGRESS

### Step 1.1: Fix `validate_source_snapshots()` in `cross_artifact_validator.py`
**File**: `cross_artifact_validator.py`
**Change**: Modify `validate_source_snapshots()` to prefer `combined_feed` when present
**Commit**: Single file
**Risk**: Low — only affects Google Developer counting

---

## Phase 2: Add Per-Stream Validation (Step 2)

### Step 2.1: Add `validate_stream_completeness()` method
**File**: `cross_artifact_validator.py`
**Change**: Add new method to validate per-stream completeness for multi-stream platforms
**Commit**: Single file
**Risk**: Low — additive only

### Step 2.2: Wire into validation pipeline
**File**: `cross_artifact_validator.py`
**Change**: Call `validate_stream_completeness()` in `run_all()`
**Commit**: Single file
**Risk**: Low

---

## Phase 3: Validation & Testing

### Step 3.1: Verify Locally
```bash
uv run python cross_artifact_validator.py --mode strict
# Expected: Google Developer source count = 1,736 (not 3,591)
# Stream completeness check passes
```

### Step 3.2: Run Full Test Suite
```bash
uv run pytest tests/ -v
```
**Expected**: All 592 tests pass

### Step 3.3: Run Ruff Checks
```bash
uv run ruff check . && uv run ruff format --check .
```

---

## Phase 4: GitHub Actions Integration Test

Trigger all 6 platform workflows + cross-artifact validation manually.

---

## Rollback Plan (Per Step)

| Step | Rollback |
|------|----------|
| 1.1 | Revert `cross_artifact_validator.py` to before counting fix |
| 2.1 | Remove `validate_stream_completeness()` method |
| 2.2 | Remove call to `validate_stream_completeness()` in `run_all()` |

All steps independently revertible.

---

## Success Criteria

- [ ] Google Developer source count: 3,591 → 1,736
- [ ] Stream completeness check passes for Google Developer
- [ ] All 592 tests pass
- [ ] Cross-artifact validation: 96/96 pass
- [ ] All 6 platform workflows pass
- [ ] Ruff checks pass