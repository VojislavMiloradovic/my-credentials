# Mitigation Implementation Todo List

## Phase 1: Core Fixes (Allow for_validation regeneration) ✅ COMPLETE
- [x] **Strategy 6**: Fix Cross-Artifact Validator - Treat missing source snapshots as SKIP/WARN instead of ERROR
- [x] **Strategy 7**: Fix Fixture Freshness Check - Allow missing files (warn only, don't fail with --fail-on-stale)

## Phase 2: Pre-Commit Validation in Reusable Workflow ✅ COMPLETE
- [x] **Strategy 1**: Add Cross-Artifact Validation to reusable-update.yml (pre-commit)
- [x] **Strategy 2**: Add Manifest Validation to reusable-update.yml (pre-commit)
- [x] **Strategy 3**: Add Targeted Pipeline Tests to reusable-update.yml (pre-commit)

## Phase 3: Enforcement Layer
- [x] **Strategy 5**: Remove `continue-on-error: true` from cross_artifact_validation.yml
- [x] **Strategy 4**: Configure branch protection required checks — **Skipped (unnecessary)** — Pre-commit validation in reusable workflow already enforces all checks before push

## Testing After Each Strategy
- Run relevant component test
- Verify pipelines still operational
- Verify output format unchanged
- Document recovery plan for each failure mode

## Recovery Plans (Non-Rollback)
- Each strategy must have a way to recover without git revert