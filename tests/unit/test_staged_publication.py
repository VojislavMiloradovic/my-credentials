"""
Unit tests for staged fail-closed publication (publish_staged.py),
upstream L1 provenance population (pipeline_base.py), and strict
cross-artifact feed/hash parity checks (cross_artifact_validator.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cross_artifact_validator
import loss_guard
import pipeline_base
import publish_staged
from cross_artifact_validator import CrossArtifactValidator, PlatformCounts
from pipeline_base import PipelineBase


class _ProvenanceDummyPipeline(PipelineBase):
    PLATFORM_NAME = "credly"
    PLATFORM_PREFIX = "credly"
    PLATFORM_DISPLAY_NAME = "Credly"

    def fetch_data(self):
        return []

    def parse_data(self, raw_data):
        return []

    def format_for_archive(self, record):
        return ("", "")

    def build_readme_lines(self, records, latest_slice):
        return []


def _seed_mini_repo(root: Path) -> None:
    """Populate a minimal self-contained repo tree for staged publication tests."""
    repo_root = Path(__file__).parent.parent.parent
    for fname in (
        "generate_jsonld.py",
        "generate_llms_txt.py",
        "generate_llms_full.py",
        "cross_artifact_validator.py",
        "validate_manifest.py",
        "layer_manifest.py",
        "loss_guard.py",
        "verify_assertions.py",
        "archiver.py",
        "pipeline_base.py",
    ):
        src = repo_root / fname
        (root / fname).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # Copy models/ and scripts/verify_baseline.py
    models_dst = root / "models"
    models_dst.mkdir(parents=True, exist_ok=True)
    for model_file in (repo_root / "models").glob("*.py"):
        (models_dst / model_file.name).write_text(
            model_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    scripts_dst = root / "scripts"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    (scripts_dst / "__init__.py").write_text("", encoding="utf-8")
    (scripts_dst / "verify_baseline.py").write_text(
        (repo_root / "scripts" / "verify_baseline.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # Copy dataset_layers.yaml
    (root / "dataset_layers.yaml").write_text(
        (repo_root / "dataset_layers.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    val_dir = root / "for_validation"
    val_dir.mkdir()
    archives_dir = root / "archives"
    archives_dir.mkdir()
    data_dir = root / "data"
    data_dir.mkdir()

    # Old sentinel files that must not change if staging fails
    (root / "README.md").write_text("OLD_README\n", encoding="utf-8")
    (root / "credentials.jsonld").write_text('{"old": true}\n', encoding="utf-8")
    (root / "credentials.feed.json").write_text('{"old": true}\n', encoding="utf-8")
    (root / "credentials.ndjson").write_text('{"old": true}\n', encoding="utf-8")
    (root / "llms.txt").write_text("OLD_LLMS\n", encoding="utf-8")
    (root / "llms-full.txt").write_text("OLD_LLMS_FULL\n", encoding="utf-8")
    (archives_dir / "credly-complete.md").write_text("OLD_ARCHIVE\n", encoding="utf-8")
    (archives_dir / "credly-orphan.md").write_text("ORPHAN\n", encoding="utf-8")

    record = {
        "id": "credly-1",
        "title": "Sample Badge",
        "issuer_name": "Credly",
        "type": "Badge",
        "date": "2026-10-01T12:00:00+00:00",
        "verify_url": "https://www.credly.com/badges/credly-1/public_url",
        "retired": False,
    }
    (val_dir / "credly_badges.json").write_text(
        json.dumps({"platform": "credly", "credentials": [record]}),
        encoding="utf-8",
    )
    (val_dir / "credly-baseline.json").write_text(
        json.dumps(
            {
                "platform": "credly",
                "record_count": 1,
                "fingerprint_schema_version": loss_guard.CURRENT_FINGERPRINT_SCHEMA_VERSION,
                "fingerprints": {
                    "credly-1": {
                        "id": "credly-1",
                        "content_hash": loss_guard.compute_content_hash(
                            record, "id", "credly"
                        ),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    # Custom generator script for testing staged script execution
    (root / "dummy_update.py").write_text(
        "from pathlib import Path\n"
        "Path('README.md').write_text('NEW_README\\n', encoding='utf-8')\n"
        "orphan = Path('archives/credly-orphan.md')\n"
        "if orphan.exists():\n"
        "    orphan.unlink()\n"
        "Path('archives/credly-complete.md').write_text('NEW_ARCHIVE\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )


class TestUpstreamProvenancePopulation:
    """Verify PipelineBase._enrich_record_list_provenance populates L1 IDs and hashes."""

    def test_enrich_record_list_provenance_populates_id_and_hash(self):
        pipeline = _ProvenanceDummyPipeline()
        records = [
            {
                "id": "badge-99",
                "title": "Cloud Security Specialist",
                "date": "2026-09-10",
                "issuer_name": "Datadog",
                "type": "Certification",
                "verify_url": "https://www.credly.com/badges/badge-99",
                "retired": False,
            }
        ]

        pipeline._enrich_record_list_provenance(records)

        rec = records[0]
        assert rec["source_platform"] == "credly"
        assert rec["source_record_id"] == "badge-99"
        expected_hash = loss_guard.compute_content_hash(rec, "id", "credly")
        assert rec["source_hash"] == expected_hash


class TestStagedPublicationOrchestrator:
    """Verify staged execution, fail-closed gating, atomic promotion, and rollback."""

    def test_staged_full_happy_path_promotes_and_prunes_orphans(
        self, temp_dir, monkeypatch
    ):
        _seed_mini_repo(temp_dir)
        monkeypatch.setattr(
            publish_staged,
            "run_staged_validations",
            lambda *_a, **_kw: None,
        )

        exit_code = publish_staged.main(
            [
                "--root-dir",
                str(temp_dir),
                "--mode",
                "full",
                "--script",
                "dummy_update.py",
                "--stage-dir",
                ".staging_test_ok",
            ]
        )

        assert exit_code == 0
        assert not (temp_dir / ".staging_test_ok").exists()
        assert (temp_dir / "README.md").read_text(encoding="utf-8") == "NEW_README\n"
        assert (temp_dir / "archives" / "credly-complete.md").read_text(
            encoding="utf-8"
        ) == "NEW_ARCHIVE\n"
        assert not (temp_dir / "archives" / "credly-orphan.md").exists()

        jsonld_data = json.loads(
            (temp_dir / "credentials.jsonld").read_text(encoding="utf-8")
        )
        creds = jsonld_data["mainEntity"]["hasCredential"]
        assert len(creds) == 1
        assert creds[0]["sourceRecordId"] == "credly-1"
        assert creds[0]["sourceHash"]
        assert (temp_dir / "credentials.feed.json").exists()
        assert (temp_dir / "credentials.ndjson").exists()
        assert "credentials.feed.json" in (temp_dir / "llms.txt").read_text(
            encoding="utf-8"
        )
        assert "credentials.ndjson" in (temp_dir / "llms-full.txt").read_text(
            encoding="utf-8"
        )

    def test_fail_closed_validation_failure_leaves_live_repo_untouched(
        self, temp_dir, monkeypatch
    ):
        _seed_mini_repo(temp_dir)

        def fail_validation(*_a, **_kw):
            raise RuntimeError("simulated strict validation failure")

        monkeypatch.setattr(publish_staged, "run_staged_validations", fail_validation)

        with pytest.raises(RuntimeError, match="simulated strict validation failure"):
            publish_staged.main(
                [
                    "--root-dir",
                    str(temp_dir),
                    "--mode",
                    "full",
                    "--script",
                    "dummy_update.py",
                    "--stage-dir",
                    ".staging_test_fail",
                ]
            )

        assert not (temp_dir / ".staging_test_fail").exists()
        assert (temp_dir / "README.md").read_text(encoding="utf-8") == "OLD_README\n"
        assert (temp_dir / "credentials.jsonld").read_text(
            encoding="utf-8"
        ) == '{"old": true}\n'
        assert (temp_dir / "archives" / "credly-complete.md").read_text(
            encoding="utf-8"
        ) == "OLD_ARCHIVE\n"
        assert (temp_dir / "archives" / "credly-orphan.md").exists()

    def test_two_phase_stage_only_and_promote_stage(self, temp_dir):
        _seed_mini_repo(temp_dir)

        assert (
            publish_staged.main(
                [
                    "--root-dir",
                    str(temp_dir),
                    "--mode",
                    "full",
                    "--script",
                    "dummy_update.py",
                    "--stage-only",
                    "--stage-dir",
                    ".staging_ci_test",
                ]
            )
            == 0
        )

        # Live artifacts must still be untouched after --stage-only
        assert (temp_dir / ".staging_ci_test").is_dir()
        assert (temp_dir / "README.md").read_text(encoding="utf-8") == "OLD_README\n"
        assert (temp_dir / "archives" / "credly-orphan.md").exists()

        # Promote staged artifacts
        assert (
            publish_staged.main(
                [
                    "--root-dir",
                    str(temp_dir),
                    "--promote-stage",
                    ".staging_ci_test",
                ]
            )
            == 0
        )

        assert not (temp_dir / ".staging_ci_test").exists()
        assert (temp_dir / "README.md").read_text(encoding="utf-8") == "NEW_README\n"
        assert not (temp_dir / "archives" / "credly-orphan.md").exists()

    def test_promote_rollback_restores_live_files_on_copy_error(
        self, temp_dir, monkeypatch
    ):
        _seed_mini_repo(temp_dir)
        stage_dir = publish_staged.create_stage_workspace(
            temp_dir, temp_dir / ".staging_rollback"
        )
        (stage_dir / "README.md").write_text("STAGE_README\n", encoding="utf-8")
        (stage_dir / "llms.txt").write_text("STAGE_LLMS\n", encoding="utf-8")

        orig_copy = publish_staged._atomic_copy_file
        calls = {"count": 0}

        def failing_on_second(src: Path, dst: Path) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated disk full during promotion")
            orig_copy(src, dst)

        monkeypatch.setattr(publish_staged, "_atomic_copy_file", failing_on_second)

        with pytest.raises(OSError, match="simulated disk full during promotion"):
            publish_staged.promote_staged_artifacts(temp_dir, stage_dir)

        assert (temp_dir / "README.md").read_text(encoding="utf-8") == "OLD_README\n"
        assert (temp_dir / "llms.txt").read_text(encoding="utf-8") == "OLD_LLMS\n"


class TestValidatorFeedAndL1Parity:
    """Verify cross_artifact_validator checks for L1 hash parity, feeds, and UTC dates."""

    def test_validator_catches_feed_mismatch_and_l1_hash_mismatch(self, temp_dir):
        val_dir = temp_dir / "for_validation"
        val_dir.mkdir()
        record = {
            "id": "credly-1",
            "title": "Badge One",
            "date": "2026-10-01T12:00:00+00:00",
            "issuer_name": "Credly",
            "type": "Badge",
            "retired": False,
        }
        (val_dir / "credly_badges.json").write_text(
            json.dumps({"platform": "credly", "credentials": [record]}),
            encoding="utf-8",
        )
        true_hash = loss_guard.compute_content_hash(record, "id", "credly")

        jsonld_path = temp_dir / "credentials.jsonld"
        jsonld_path.write_text(
            json.dumps(
                {
                    "mainEntity": {
                        "hasCredential": [
                            {
                                "platform": "credly",
                                "name": "Badge One",
                                "credentialStatus": "Active",
                                "dateCreated": "2026-10-01T12:00:00+00:00",
                                "sourceRecordId": "credly-1",
                                "sourceHash": "wrong-hash-value",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        feed_json = temp_dir / "credentials.feed.json"
        feed_json.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "generatedAt": "2026-10-01T12:00:00+00:00",
                    "owner": {"name": "Test", "url": "https://example.com"},
                    "totalCount": 99,
                    "countsByPlatform": {"credly": 1},
                    "credentials": [],
                }
            ),
            encoding="utf-8",
        )
        ndjson = temp_dir / "credentials.ndjson"
        ndjson.write_text(
            json.dumps(
                {
                    "id": "credly-1",
                    "sourceRecordId": "credly-1",
                    "sourceHash": true_hash,
                    "platform": "credly",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        validator = CrossArtifactValidator(strict=True, warn_mode=False)
        with (
            patch("cross_artifact_validator.JSONLD_PATH", str(jsonld_path)),
            patch("cross_artifact_validator.FEED_JSON_PATH", str(feed_json)),
            patch("cross_artifact_validator.FEED_NDJSON_PATH", str(ndjson)),
            patch("cross_artifact_validator.VALIDATION_DIR", str(val_dir)),
            patch(
                "cross_artifact_validator.PLATFORMS",
                {"credly": cross_artifact_validator.PLATFORMS["credly"]},
            ),
        ):
            validator.validate_jsonld()

        by_name = {r.check_name: r for r in validator.results}
        assert by_name["jsonld_provenance_ids_and_hashes"].passed is True
        assert by_name["feed_json_count_parity"].passed is False
        assert by_name["l1_jsonld_source_hash_parity"].passed is False

    def test_validator_handles_mixed_naive_and_aware_iso_dates(self):
        validator = CrossArtifactValidator(strict=True, warn_mode=False)
        counts = PlatformCounts(platform="credly")
        counts.latest_record_date_source = "2026-10-31T02:40:58+00:00"
        counts.latest_record_date_archive = "2026-10-30"
        counts.latest_record_date_jsonld = "2026-10-31T02:40:58+00:00"
        validator.platform_data["credly"] = counts

        with patch(
            "cross_artifact_validator.PLATFORMS",
            {"credly": cross_artifact_validator.PLATFORMS["credly"]},
        ):
            validator.validate_latest_record_ordering()

        results = [
            r
            for r in validator.results
            if r.check_name == "latest_record_date_consistency"
        ]
        assert len(results) == 1
        assert results[0].passed is True
