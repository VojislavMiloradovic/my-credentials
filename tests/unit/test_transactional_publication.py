"""
Unit tests for transactional publication, atomic file writes, fail-fast gates,
and strict fixture synchronization.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import archiver
import loss_guard
import pipeline_base
from pipeline_base import PipelineBase, _atomic_write_json
from scripts import sync_fixtures as sync_fixtures_mod


class _DummyPipeline(PipelineBase):
    PLATFORM_NAME = "credly"
    PLATFORM_PREFIX = "credly"
    PLATFORM_DISPLAY_NAME = "Credly"
    FAIL_ON_WARN = False

    def __init__(self, records: list[dict], base_dir: Path):
        self.VALIDATION_DIR = str(base_dir / "for_validation")
        self.ARCHIVE_DIR = str(base_dir / "archives")
        self.README_PATH = str(base_dir / "README.md")
        self.JSON_PATH = str(base_dir / "for_validation" / "credly.json")
        self.MONOLITH_PATH = str(base_dir / "archives" / "credly-complete.md")
        self._records = records
        super().__init__()

    def fetch_data(self) -> list[dict]:
        return list(self._records)

    def parse_data(self, raw_data) -> list[dict]:
        return list(raw_data)

    def format_for_archive(self, record: dict) -> tuple[str, str]:
        date_val = record["date"]
        return f"| {date_val} | **{record['title']}** | Credly |", date_val

    def build_readme_lines(self, records: list[dict], latest_slice: str) -> list[str]:
        return [
            f"Count: {len(records)}",
            "Latest: [Slice]({LATEST_SLICE_NORMAL}) ([Raw]({LATEST_SLICE_RAW}))",
        ]


def _seed_workspace(base_dir: Path) -> dict[str, Path]:
    """Populate a temporary workspace with pre-run validation, baseline, archive, README, and fixture files."""
    val_dir = base_dir / "for_validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = base_dir / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    fixture_file = base_dir / "tests" / "fixtures" / "credly" / "baseline.json"
    fixture_file.parent.mkdir(parents=True, exist_ok=True)

    validation_file = val_dir / "credly.json"
    validation_file.write_text(
        json.dumps(
            {
                "platform": "credly",
                "total_combined": 1,
                "combined_feed": [{"id": "old-1"}],
            }
        ),
        encoding="utf-8",
    )

    baseline_data = {
        "platform": "credly",
        "stream_id": None,
        "record_count": 1,
        "created_at": "2024-01-01T00:00:00+00:00",
        "fingerprint_schema_version": loss_guard.CURRENT_FINGERPRINT_SCHEMA_VERSION,
        "fingerprints": {"old-1": {"id": "old-1", "content_hash": "old-hash"}},
    }
    baseline_file = val_dir / "credly-baseline.json"
    baseline_file.write_text(json.dumps(baseline_data), encoding="utf-8")
    fixture_file.write_text(json.dumps(baseline_data), encoding="utf-8")

    monolith_file = archive_dir / "credly-complete.md"
    monolith_file.write_text("OLD_MONOLITH", encoding="utf-8")
    index_file = archive_dir / "credly-index.md"
    index_file.write_text("OLD_INDEX", encoding="utf-8")
    part_file = archive_dir / "credly-2024-01-part-01.md"
    part_file.write_text("OLD_PART_01", encoding="utf-8")
    orphan_file = archive_dir / "credly-2023-12-part-99.md"
    orphan_file.write_text("OLD_ORPHAN_PART_99", encoding="utf-8")

    readme_file = base_dir / "README.md"
    readme_file.write_text(
        "Header\n<!-- CREDLY_START -->\nOLD_README\n<!-- CREDLY_END -->\nFooter\n",
        encoding="utf-8",
    )

    return {
        "val_dir": val_dir,
        "validation_file": validation_file,
        "baseline_file": baseline_file,
        "fixture_file": fixture_file,
        "archive_dir": archive_dir,
        "monolith_file": monolith_file,
        "index_file": index_file,
        "part_file": part_file,
        "orphan_file": orphan_file,
        "readme_file": readme_file,
    }


def _sample_records() -> list[dict]:
    return [
        {
            "id": "cred-100",
            "title": "AWS Certified Solutions Architect",
            "date": "2024-06-10",
            "issuer_name": "Amazon Web Services",
            "type": "Certification",
            "verify_url": "https://www.credly.com/badges/cred-100",
            "retired": False,
        }
    ]


class TestAtomicFileWrites:
    """Verify atomic write helpers never leave partial content or orphaned temp files."""

    def test_atomic_write_text_preserves_target_on_replace_failure(self, temp_dir):
        target = temp_dir / "state.txt"
        target.write_text("ORIGINAL_CONTENT", encoding="utf-8")

        with (
            patch("archiver.os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            archiver.atomic_write_text(str(target), "PARTIAL_NEW_CONTENT")

        assert target.read_text(encoding="utf-8") == "ORIGINAL_CONTENT"
        assert list(temp_dir.glob("*.tmp")) == []

    def test_atomic_write_json_preserves_target_on_replace_failure(self, temp_dir):
        target = temp_dir / "payload.json"
        target.write_text('{"version": 1}', encoding="utf-8")

        with (
            patch("archiver.os.replace", side_effect=OSError("io error")),
            pytest.raises(OSError, match="io error"),
        ):
            _atomic_write_json(str(target), {"version": 2})

        assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
        assert list(temp_dir.glob("*.tmp")) == []


class TestTransactionalPublicationRollback:
    """Verify PipelineBase.run rolls back all artifacts and baselines on any publication failure."""

    @pytest.fixture
    def isolated_env(self, temp_dir, monkeypatch):
        monkeypatch.chdir(temp_dir)
        paths = _seed_workspace(temp_dir)
        monkeypatch.setattr(loss_guard, "VALIDATION_DIR", str(paths["val_dir"]))
        monkeypatch.setattr(
            pipeline_base,
            "run_provider_loss_guards",
            lambda *args, **kwargs: None,
        )
        return temp_dir, paths

    def test_happy_path_updates_all_artifacts_and_baseline(self, isolated_env):
        temp_dir, paths = isolated_env
        pipeline = _DummyPipeline(_sample_records(), temp_dir)
        pipeline.run()

        val_data = json.loads(paths["validation_file"].read_text(encoding="utf-8"))
        assert val_data["combined_feed"][0]["id"] == "cred-100"

        baseline = json.loads(paths["baseline_file"].read_text(encoding="utf-8"))
        assert "cred-100" in baseline["fingerprints"]

        synced_fixture = json.loads(paths["fixture_file"].read_text(encoding="utf-8"))
        assert "cred-100" in synced_fixture["fingerprints"]

        assert "AWS Certified Solutions Architect" in paths["monolith_file"].read_text(
            encoding="utf-8"
        )
        assert not paths["orphan_file"].exists()
        assert "Count: 1" in paths["readme_file"].read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "fail_stage",
        [
            "persist_validation",
            "generate_archive",
            "generate_archive_none",
            "update_readme",
            "generate_baselines_false",
            "sync_fixtures",
        ],
    )
    def test_failure_at_any_stage_rolls_back_all_artifacts_and_baseline(
        self, isolated_env, monkeypatch, fail_stage
    ):
        temp_dir, paths = isolated_env
        baseline_before = paths["baseline_file"].read_text(encoding="utf-8")
        fixture_before = paths["fixture_file"].read_text(encoding="utf-8")
        validation_before = paths["validation_file"].read_text(encoding="utf-8")
        readme_before = paths["readme_file"].read_text(encoding="utf-8")
        monolith_before = paths["monolith_file"].read_text(encoding="utf-8")
        index_before = paths["index_file"].read_text(encoding="utf-8")

        pipeline = _DummyPipeline(_sample_records(), temp_dir)

        if fail_stage == "persist_validation":
            monkeypatch.setattr(
                pipeline,
                "persist_validation",
                lambda _recs: (_ for _ in ()).throw(OSError("validation write failed")),
            )
        elif fail_stage == "generate_archive":
            monkeypatch.setattr(
                pipeline_base,
                "generate_platform_archive",
                lambda *a, **kw: (_ for _ in ()).throw(OSError("archive write failed")),
            )
        elif fail_stage == "generate_archive_none":
            monkeypatch.setattr(
                pipeline_base,
                "generate_platform_archive",
                lambda *a, **kw: None,
            )
        elif fail_stage == "update_readme":
            monkeypatch.setattr(
                pipeline,
                "update_readme",
                lambda *_a, **_kw: (_ for _ in ()).throw(
                    OSError("readme write failed")
                ),
            )
        elif fail_stage == "generate_baselines_false":
            monkeypatch.setattr(
                loss_guard,
                "generate_provider_baseline",
                lambda *_a, **_kw: False,
            )
        elif fail_stage == "sync_fixtures":
            monkeypatch.setattr(
                pipeline_base,
                "sync_fixtures",
                lambda *_a, **_kw: (_ for _ in ()).throw(
                    OSError("fixture sync failed")
                ),
            )

        with pytest.raises((OSError, RuntimeError)):
            pipeline.run()

        # Baseline & fixture MUST NOT advance or corrupt
        assert paths["baseline_file"].read_text(encoding="utf-8") == baseline_before
        assert paths["fixture_file"].read_text(encoding="utf-8") == fixture_before
        # Validation JSON, README, and archives MUST roll back cleanly
        assert paths["validation_file"].read_text(encoding="utf-8") == validation_before
        assert paths["readme_file"].read_text(encoding="utf-8") == readme_before
        assert paths["monolith_file"].read_text(encoding="utf-8") == monolith_before
        assert paths["index_file"].read_text(encoding="utf-8") == index_before
        assert paths["part_file"].read_text(encoding="utf-8") == "OLD_PART_01"
        assert paths["orphan_file"].read_text(encoding="utf-8") == "OLD_ORPHAN_PART_99"
        # Newly created 2024-06 slice must be cleaned up on rollback
        assert not (paths["archive_dir"] / "credly-2024-06-part-01.md").exists()


class TestSyncFixturesStrictness:
    """Verify scripts/sync_fixtures.py fails loudly when expected sources fail while staying CI-workspace safe."""

    def test_unknown_platform_raises_value_error(self, temp_dir, monkeypatch):
        monkeypatch.chdir(temp_dir)
        with pytest.raises(ValueError, match="Unknown platform"):
            sync_fixtures_mod.sync_fixtures("nonexistent-platform")

    def test_missing_for_validation_root_skips_for_ci_workspace(
        self, temp_dir, monkeypatch
    ):
        monkeypatch.chdir(temp_dir)
        assert not (temp_dir / "for_validation").exists()
        assert sync_fixtures_mod.sync_fixtures("credly", verbose=False) == 0

    def test_missing_baseline_when_for_validation_exists_raises(
        self, temp_dir, monkeypatch
    ):
        monkeypatch.chdir(temp_dir)
        (temp_dir / "for_validation").mkdir()
        with pytest.raises(
            FileNotFoundError, match="Expected baseline source not found"
        ):
            sync_fixtures_mod.sync_fixtures("credly", verbose=False)

    def test_atomic_copy_preserves_existing_fixture_on_error(
        self, temp_dir, monkeypatch
    ):
        monkeypatch.chdir(temp_dir)
        src = temp_dir / "for_validation" / "credly-baseline.json"
        dst = temp_dir / "tests" / "fixtures" / "credly" / "baseline.json"
        src.parent.mkdir(parents=True)
        dst.parent.mkdir(parents=True)
        src.write_text('{"new": true}', encoding="utf-8")
        dst.write_text('{"old": true}', encoding="utf-8")

        with (
            patch.object(
                sync_fixtures_mod.shutil, "copy2", side_effect=OSError("copy failed")
            ),
            pytest.raises(OSError, match="copy failed"),
        ):
            sync_fixtures_mod.sync_fixtures("credly", verbose=False)

        assert dst.read_text(encoding="utf-8") == '{"old": true}'
        assert list(dst.parent.glob("*.tmp")) == []


class TestMicrosoftLearnTransactionalOrder:
    """Verify MicrosoftLearnPipeline runs baselines before fixture sync inside transaction."""

    def test_ms_learn_generates_baseline_before_syncing_fixtures_and_rolls_back(
        self, temp_dir, monkeypatch, sample_ms_learn_json
    ):
        import update_ms_learn

        monkeypatch.chdir(temp_dir)
        val_dir = temp_dir / "for_validation"
        val_dir.mkdir()
        archive_dir = temp_dir / "archives"
        archive_dir.mkdir()
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        fixture_file = (
            temp_dir / "tests" / "fixtures" / "microsoft_learn" / "baseline.json"
        )
        fixture_file.parent.mkdir(parents=True)

        json_input = data_dir / "microsoft-learn.json"
        json_input.write_text(json.dumps(sample_ms_learn_json), encoding="utf-8")
        readme = temp_dir / "README.md"
        readme.write_text(
            "Before\n<!-- MS_LEARN_START -->\nOLD\n<!-- MS_LEARN_END -->\nAfter\n",
            encoding="utf-8",
        )
        old_baseline = {
            "platform": "microsoft-learn",
            "record_count": 0,
            "fingerprint_schema_version": loss_guard.CURRENT_FINGERPRINT_SCHEMA_VERSION,
            "fingerprints": {},
        }
        baseline_file = val_dir / "microsoft-learn-baseline.json"
        baseline_file.write_text(json.dumps(old_baseline), encoding="utf-8")
        fixture_file.write_text(json.dumps(old_baseline), encoding="utf-8")

        monkeypatch.setattr(loss_guard, "VALIDATION_DIR", str(val_dir))
        monkeypatch.setattr(update_ms_learn, "VALIDATION_DIR", str(val_dir))
        monkeypatch.setattr(update_ms_learn, "JSON_PATH", str(json_input))
        monkeypatch.setattr(update_ms_learn, "ARCHIVE_DIR", str(archive_dir))
        monkeypatch.setattr(update_ms_learn, "README_PATH", str(readme))
        monkeypatch.setattr(update_ms_learn, "load_retired_rules", lambda _p: [])
        monkeypatch.setattr(
            loss_guard, "run_provider_loss_guards", lambda *a, **kw: None
        )

        # Record execution order and verify new baseline already exists when sync_fixtures runs
        events: list[str] = []
        orig_gen = loss_guard.generate_provider_baseline

        def tracking_baseline(records, provider_name, stream_id=None):
            events.append("baseline")
            return orig_gen(records, provider_name, stream_id=stream_id)

        monkeypatch.setattr(loss_guard, "generate_provider_baseline", tracking_baseline)

        def failing_sync(self):
            events.append("sync")
            current = json.loads(baseline_file.read_text(encoding="utf-8"))
            assert current["record_count"] > 0
            raise OSError("simulated fixture sync failure")

        monkeypatch.setattr(
            update_ms_learn.MicrosoftLearnPipeline, "sync_fixtures", failing_sync
        )

        with pytest.raises(OSError, match="simulated fixture sync failure"):
            update_ms_learn.MicrosoftLearnPipeline().run()

        assert events == ["baseline", "sync"]
        # Rollback restored old baseline and removed newly written validation JSON
        assert json.loads(baseline_file.read_text(encoding="utf-8")) == old_baseline
        assert not (val_dir / "microsoft-learn.json").exists()
        assert "OLD" in readme.read_text(encoding="utf-8")


class TestReadmeStatsStrictness:
    """Verify archiver.update_readme_stats fails loudly on unexpected I/O errors."""

    def test_update_readme_stats_raises_on_io_error(self, temp_dir, monkeypatch):
        readme = temp_dir / "README.md"
        readme.write_text(
            "<!-- GOOGLE_DEVELOPER_START -->\n"
            "| **Total Milestones & Milestone Badges** | 1 |\n"
            "<!-- GOOGLE_DEVELOPER_END -->\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            archiver,
            "safe_write_file",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError("readonly readme")),
        )
        with pytest.raises(OSError, match="readonly readme"):
            archiver.update_readme_stats(
                "google-developer",
                total_count=5,
                public_badges=5,
                detailed_learnings=0,
                readme_path=str(readme),
            )
