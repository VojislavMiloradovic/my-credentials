"""
publish_staged.py
=================

Staged, fail-closed artifact publication and atomic promotion orchestrator.

Generates L1/L2/L3 artifacts (or runs active assertion probing) inside a
repo-local staging workspace on the same filesystem, validates the staged
artifact set before any live mutation occurs, and atomically promotes public
artifacts, archives, baselines, and synced fixtures to the repository root.

Supports:
- Full single-command local execution (stage -> generate -> validate -> promote)
- Two-phase GitHub Actions execution (--stage-only, then independent CI
  validation steps inside the stage dir, then --promote-stage / --cleanup-stage)
  so individual CI checks remain independently commentable for baseline recovery.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT_CODE_GLOBS = ("*.py",)
ROOT_STATIC_FILES = (
    "dataset_layers.yaml",
    "pyproject.toml",
    "uv.lock",
    "retired_urls.json",
    "README.md",
    "credentials.jsonld",
    "credentials.feed.json",
    "credentials.ndjson",
    "llms.txt",
    "llms-full.txt",
)
STAGED_SUBDIRS = (
    "models",
    "scripts",
    "data",
    "for_validation",
    "archives",
    "tests/fixtures",
)
PROMOTE_ROOT_FILES = (
    "README.md",
    "credentials.jsonld",
    "credentials.feed.json",
    "credentials.ndjson",
    "llms.txt",
    "llms-full.txt",
    "retired_urls.json",
)
PROMOTE_DIRS_SYNC_UPDATES_ONLY = ("data", "for_validation", "tests/fixtures")
PROMOTE_DIRS_MIRROR_DELETIONS = ("archives",)


def _atomic_copy_file(src: Path, dst: Path) -> None:
    """Copy src to dst atomically via a same-directory temp file and os.replace."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(dst.parent),
            prefix=f".{dst.name}.",
            suffix=".promote.tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
        shutil.copy2(src, tmp_path)
        try:
            os.replace(tmp_path, dst)
        except OSError:
            if os.name != "nt" or not dst.exists():
                raise
            backup_path = dst.with_name(f"{dst.name}.bak")
            os.replace(dst, backup_path)
            try:
                os.replace(tmp_path, dst)
            except OSError:
                if not dst.exists() and backup_path.exists():
                    os.replace(backup_path, dst)
                raise
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except OSError:
                    pass
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _files_differ(a: Path, b: Path) -> bool:
    """Return True if b does not exist or its byte contents differ from a."""
    if not b.exists():
        return True
    try:
        return a.read_bytes() != b.read_bytes()
    except OSError:
        return True


def _ignore_copy_entries(_src: str, names: list[str]) -> set[str]:
    ignored = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
        ".venv",
    }
    return {
        name
        for name in names
        if name in ignored
        or name.startswith(".staging_")
        or name.endswith((".pyc", ".pyo", ".tmp"))
    }


def create_stage_workspace(root_dir: Path, stage_dir: Path) -> Path:
    """Populate a clean staging directory from root_dir on the same filesystem."""
    root_resolved = root_dir.resolve()
    stage_resolved = stage_dir.resolve()
    if stage_resolved == root_resolved:
        raise ValueError("Staging directory cannot be the repository root itself.")

    if stage_resolved.exists():
        shutil.rmtree(stage_resolved)
    stage_resolved.mkdir(parents=True, exist_ok=True)

    # Copy top-level Python modules
    for pattern in ROOT_CODE_GLOBS:
        for src_file in root_resolved.glob(pattern):
            if src_file.is_file():
                shutil.copy2(src_file, stage_resolved / src_file.name)

    # Copy root manifests, configs, and existing L2/L3 artifacts
    for rel_name in ROOT_STATIC_FILES:
        src_file = root_resolved / rel_name
        if src_file.is_file():
            shutil.copy2(src_file, stage_resolved / rel_name)

    # Copy required directories
    for rel_dir in STAGED_SUBDIRS:
        src_subdir = root_resolved / rel_dir
        if src_subdir.is_dir():
            dst_subdir = stage_resolved / rel_dir
            dst_subdir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                src_subdir,
                dst_subdir,
                dirs_exist_ok=True,
                ignore=_ignore_copy_entries,
            )

    return stage_resolved


@dataclass
class _PromotionRollbackLog:
    """Tracks original file states touched during promotion for atomic rollback."""

    backup_root: Path
    restores: list[tuple[Path, Path]] = field(default_factory=list)
    created: list[Path] = field(default_factory=list)

    def snapshot_target(self, target: Path, rel_key: str) -> None:
        if target.exists():
            backup_path = self.backup_root / rel_key
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
            self.restores.append((target, backup_path))
        else:
            self.created.append(target)

    def rollback(self) -> None:
        for created_path in reversed(self.created):
            try:
                if created_path.is_file():
                    created_path.unlink()
            except OSError:
                pass
        for target, backup_path in reversed(self.restores):
            try:
                if backup_path.exists():
                    _atomic_copy_file(backup_path, target)
            except OSError:
                pass


def promote_staged_artifacts(root_dir: Path, stage_dir: Path) -> list[str]:
    """
    Atomically promote generated outputs, baselines, fixtures, and archive deletions
    from stage_dir into root_dir. Rolls back all changes if any replacement fails.
    """
    root_resolved = root_dir.resolve()
    stage_resolved = stage_dir.resolve()
    if not stage_resolved.is_dir():
        raise FileNotFoundError(f"Staging directory does not exist: {stage_resolved}")

    promoted_paths: list[str] = []
    backup_dir = Path(
        tempfile.mkdtemp(prefix=".promote_backup_", dir=str(root_resolved))
    )
    rollback_log = _PromotionRollbackLog(backup_root=backup_dir)

    try:
        # 1. Promote changed or newly created root artifacts
        for rel_name in PROMOTE_ROOT_FILES:
            src_file = stage_resolved / rel_name
            dst_file = root_resolved / rel_name
            if src_file.is_file() and _files_differ(src_file, dst_file):
                rollback_log.snapshot_target(dst_file, rel_name)
                _atomic_copy_file(src_file, dst_file)
                promoted_paths.append(rel_name)

        # 2. Promote updated files in data/, for_validation/, and tests/fixtures/
        for rel_dir in PROMOTE_DIRS_SYNC_UPDATES_ONLY:
            src_dir = stage_resolved / rel_dir
            if not src_dir.is_dir():
                continue
            for src_file in sorted(src_dir.rglob("*")):
                if not src_file.is_file():
                    continue
                rel_path = src_file.relative_to(stage_resolved)
                dst_file = root_resolved / rel_path
                if _files_differ(src_file, dst_file):
                    rollback_log.snapshot_target(dst_file, rel_path.as_posix())
                    _atomic_copy_file(src_file, dst_file)
                    promoted_paths.append(rel_path.as_posix())

        # 3. Mirror archives/ (updates, additions, and pruned archive chunk deletions)
        for rel_dir in PROMOTE_DIRS_MIRROR_DELETIONS:
            src_dir = stage_resolved / rel_dir
            dst_dir = root_resolved / rel_dir
            if not src_dir.is_dir():
                continue
            staged_files = {
                p.relative_to(stage_resolved).as_posix(): p
                for p in src_dir.rglob("*")
                if p.is_file()
            }
            for rel_posix, src_file in sorted(staged_files.items()):
                dst_file = root_resolved / rel_posix
                if _files_differ(src_file, dst_file):
                    rollback_log.snapshot_target(dst_file, rel_posix)
                    _atomic_copy_file(src_file, dst_file)
                    promoted_paths.append(rel_posix)

            if dst_dir.is_dir():
                for live_file in sorted(dst_dir.rglob("*")):
                    if not live_file.is_file():
                        continue
                    rel_posix = live_file.relative_to(root_resolved).as_posix()
                    if rel_posix not in staged_files:
                        rollback_log.snapshot_target(live_file, rel_posix)
                        live_file.unlink()
                        promoted_paths.append(f"-{rel_posix}")

        return promoted_paths
    except Exception:
        rollback_log.rollback()
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _run_staged_step(
    cmd: list[str],
    stage_dir: Path,
    *,
    label: str,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Execute one command inside stage_dir and fail closed on non-zero exit."""
    print(f"[STAGE] Running {label}: {' '.join(cmd)}")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(cmd, cwd=str(stage_dir), env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Staged step '{label}' failed with exit code {result.returncode}"
        )


def run_staged_generation(
    stage_dir: Path,
    *,
    mode: str,
    script: str | None = None,
    pre_script: str | None = None,
    verify_args: list[str] | None = None,
    python_exe: str = sys.executable,
) -> None:
    """Run generation pipeline steps inside stage_dir."""
    if mode == "full":
        if pre_script:
            _run_staged_step(
                [python_exe, *shlex.split(pre_script)],
                stage_dir,
                label="pre-script",
            )
        if not script:
            raise ValueError("--script is required in 'full' mode.")
        _run_staged_step(
            [python_exe, *shlex.split(script)],
            stage_dir,
            label=f"scraper ({script})",
        )
        _run_staged_step(
            [python_exe, "generate_jsonld.py"],
            stage_dir,
            label="generate_jsonld.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_txt.py"],
            stage_dir,
            label="generate_llms_txt.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_full.py"],
            stage_dir,
            label="generate_llms_full.py",
        )
    elif mode == "downstream":
        _run_staged_step(
            [python_exe, "generate_jsonld.py"],
            stage_dir,
            label="generate_jsonld.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_txt.py"],
            stage_dir,
            label="generate_llms_txt.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_full.py"],
            stage_dir,
            label="generate_llms_full.py",
        )
    elif mode == "verify-assertions":
        _run_staged_step(
            [python_exe, "verify_assertions.py", *(verify_args or [])],
            stage_dir,
            label="verify_assertions.py",
        )
        _run_staged_step(
            [python_exe, "generate_jsonld.py"],
            stage_dir,
            label="generate_jsonld.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_txt.py"],
            stage_dir,
            label="generate_llms_txt.py",
        )
        _run_staged_step(
            [python_exe, "generate_llms_full.py"],
            stage_dir,
            label="generate_llms_full.py",
        )
    else:
        raise ValueError(f"Unsupported staging mode: {mode}")


def run_staged_validations(
    stage_dir: Path,
    *,
    skip_cross_validation: bool = False,
    skip_manifest_validation: bool = False,
    skip_baseline_verification: bool = False,
    report_path: Path | None = None,
    python_exe: str = sys.executable,
) -> None:
    """Validate staged artifacts inside stage_dir before promotion."""
    if not skip_cross_validation:
        resolved_report = (
            str(report_path.resolve())
            if report_path
            else str((stage_dir / "cross_artifact_report.json").resolve())
        )
        _run_staged_step(
            [
                python_exe,
                "cross_artifact_validator.py",
                "--mode",
                "strict",
                "--report",
                resolved_report,
            ],
            stage_dir,
            label="cross_artifact_validator.py",
        )

    if not skip_manifest_validation:
        _run_staged_step(
            [python_exe, "validate_manifest.py"],
            stage_dir,
            label="validate_manifest.py",
        )

    if not skip_baseline_verification:
        _run_staged_step(
            [python_exe, "scripts/verify_baseline.py"],
            stage_dir,
            label="scripts/verify_baseline.py",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Staged fail-closed generator, validator, and atomic promoter."
    )
    parser.add_argument(
        "--root-dir",
        default=".",
        help="Repository root directory (default: current working directory)",
    )
    parser.add_argument(
        "--stage-dir",
        default=None,
        help="Optional repo-local staging directory path (auto-generated if omitted)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "downstream", "verify-assertions"],
        default=None,
        help="Pipeline execution mode (default: full if --script is set, else downstream)",
    )
    parser.add_argument(
        "--pre-script",
        default="",
        help="Optional sanitization/pre-script command + args to execute before scraping",
    )
    parser.add_argument(
        "--script",
        default="",
        help="Scraper script command + args (e.g., update_ms_learn.py)",
    )
    parser.add_argument(
        "--verify-args",
        default="",
        help="Shell-quoted arguments string passed to verify_assertions.py in verify-assertions mode",
    )
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Generate staged artifacts in --stage-dir without validating or promoting",
    )
    parser.add_argument(
        "--promote-stage",
        default=None,
        help="Atomically promote previously validated --promote-stage directory and clean it up",
    )
    parser.add_argument(
        "--cleanup-stage",
        default=None,
        help="Idempotently remove a staging directory and exit",
    )
    parser.add_argument(
        "--keep-stage",
        action="store_true",
        help="Keep the temporary staging directory after completion (debugging)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip all validation gates before promotion (escape hatch)",
    )
    parser.add_argument("--skip-cross-validation", action="store_true")
    parser.add_argument("--skip-manifest-validation", action="store_true")
    parser.add_argument("--skip-baseline-verification", action="store_true")
    parser.add_argument(
        "--report",
        default=None,
        help="Optional output path for cross_artifact_validator JSON report",
    )
    return parser.parse_args(argv)


def _resolve_stage_path(root_dir: Path, raw_stage: str | None) -> Path:
    if raw_stage:
        candidate = Path(raw_stage)
        return candidate if candidate.is_absolute() else (root_dir / candidate)
    return root_dir / f".staging_publish_{uuid.uuid4().hex[:10]}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    root_dir = Path(args.root_dir).resolve()

    if args.cleanup_stage:
        target = _resolve_stage_path(root_dir, args.cleanup_stage)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            print(f"[STAGE] Cleaned up staging workspace: {target}")
        return 0

    if args.promote_stage:
        stage_dir = _resolve_stage_path(root_dir, args.promote_stage)
        promoted = promote_staged_artifacts(root_dir, stage_dir)
        print(
            f"[STAGE] Promoted {len(promoted)} changed path(s) atomically: "
            f"{', '.join(promoted) if promoted else '(no changes)'}"
        )
        if not args.keep_stage and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        return 0

    mode = args.mode or ("full" if args.script else "downstream")
    stage_dir = _resolve_stage_path(root_dir, args.stage_dir)
    verify_args = shlex.split(args.verify_args) if args.verify_args else []
    report_path = Path(args.report) if args.report else None

    keep_stage = args.keep_stage or args.stage_only
    try:
        create_stage_workspace(root_dir, stage_dir)
        print(f"[STAGE] Created staging workspace at {stage_dir}")
        run_staged_generation(
            stage_dir,
            mode=mode,
            script=args.script or None,
            pre_script=args.pre_script or None,
            verify_args=verify_args,
        )

        if args.stage_only:
            print(f"[STAGE] Staged generation complete (stage-only): {stage_dir}")
            return 0

        if not args.skip_validation:
            run_staged_validations(
                stage_dir,
                skip_cross_validation=args.skip_cross_validation,
                skip_manifest_validation=args.skip_manifest_validation,
                skip_baseline_verification=args.skip_baseline_verification,
                report_path=report_path,
            )

        promoted = promote_staged_artifacts(root_dir, stage_dir)
        print(
            f"[STAGE] Validation passed. Promoted {len(promoted)} changed path(s) atomically: "
            f"{', '.join(promoted) if promoted else '(no changes)'}"
        )
        return 0
    finally:
        if not keep_stage and stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
