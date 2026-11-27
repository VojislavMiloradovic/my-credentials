"""Regression tests enforcing supply-chain security invariants on GitHub Actions workflows."""

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"
SHA_PIN_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PIPE_TO_EXEC_RE = re.compile(
    r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:tar|sh|bash|zsh|python)\b"
)
READ_ONLY_WORKFLOWS = {
    "test.yml",
    "repo_health.yml",
    "cross_artifact_validation.yml",
}


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert files, f"No workflow files found under {WORKFLOWS_DIR}"
    return files


def _load_workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name} must parse to a YAML mapping"
    return data


def _iter_external_uses(workflow: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return refs

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_uses = job.get("uses")
        if isinstance(job_uses, str) and not job_uses.startswith("./"):
            refs.append((f"jobs.{job_id}.uses", job_uses.strip()))
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_uses = step.get("uses")
            if isinstance(step_uses, str) and not step_uses.startswith("./"):
                step_label = step.get("name") or f"step[{idx}]"
                refs.append((f"jobs.{job_id}.{step_label}", step_uses.strip()))
    return refs


def _iter_run_scripts(workflow: dict[str, Any]) -> list[tuple[str, str]]:
    scripts: list[tuple[str, str]] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return scripts

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            run_cmd = step.get("run")
            if isinstance(run_cmd, str):
                step_label = step.get("name") or f"step[{idx}]"
                scripts.append((f"jobs.{job_id}.{step_label}", run_cmd))
    return scripts


@pytest.mark.parametrize("workflow_path", _workflow_files(), ids=lambda p: p.name)
def test_all_external_actions_pinned_to_commit_sha(workflow_path: Path) -> None:
    """Every external GitHub Action reference must be pinned to a 40-char commit SHA."""
    workflow = _load_workflow(workflow_path)
    for location, uses_ref in _iter_external_uses(workflow):
        assert SHA_PIN_RE.match(uses_ref), (
            f"{workflow_path.name} ({location}): action '{uses_ref}' must be pinned to a 40-hex commit SHA"
        )


@pytest.mark.parametrize("workflow_path", _workflow_files(), ids=lambda p: p.name)
def test_no_unchecked_binary_downloads_in_workflows(workflow_path: Path) -> None:
    """Workflows must not pipe curl/wget to tar/shells and must verify downloaded archives via sha256sum."""
    workflow = _load_workflow(workflow_path)
    for location, script in _iter_run_scripts(workflow):
        assert not PIPE_TO_EXEC_RE.search(script), (
            f"{workflow_path.name} ({location}): unverified pipe from curl/wget into tar/shell is disallowed"
        )
        if ("curl " in script or "wget " in script) and any(
            ext in script for ext in (".tar.gz", ".tgz", ".zip", ".deb", ".AppImage")
        ):
            assert "sha256sum -c" in script, (
                f"{workflow_path.name} ({location}): external binary archive download must verify checksum via sha256sum -c"
            )


@pytest.mark.parametrize("workflow_name", sorted(READ_ONLY_WORKFLOWS))
def test_read_only_workflows_declare_least_privilege_permissions(
    workflow_name: str,
) -> None:
    """Read-only CI workflows must declare explicit permissions with no write scopes."""
    workflow = _load_workflow(WORKFLOWS_DIR / workflow_name)
    perms = workflow.get("permissions")
    assert isinstance(perms, dict) and perms, (
        f"{workflow_name}: must declare explicit top-level permissions"
    )
    for scope, level in perms.items():
        assert level == "read", (
            f"{workflow_name}: read-only workflow grants '{scope}: {level}' instead of 'read'"
        )
