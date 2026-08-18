"""
Unit tests for the loss_guard module.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from loss_guard import (
    PipelineDataLossAnomaly,
    RecordFingerprint,
    DiffReport,
    DEFAULT_THRESHOLDS,
    PLATFORM_THRESHOLDS,
    compute_content_hash,
    extract_record_id,
    build_fingerprint_index,
    load_baseline,
    save_baseline,
    compare_fingerprints,
    log_diff_report,
    execute_content_loss_guard,
    VALIDATION_DIR,
)


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_compute_content_hash_basic(self):
        """Should compute stable hash for record."""
        record = {
            "id": "test-001",
            "title": "Test Badge",
            "issued_at": "2024-01-15",
            "issuer": "Test Issuer",
            "skills": ["Skill1", "Skill2"],
        }
        hash1 = compute_content_hash(record, "id")
        hash2 = compute_content_hash(record, "id")
        assert hash1 == hash2
        assert len(hash1) == 32  # SHA256 truncated to 32 chars

    def test_compute_content_hash_excludes_volatile_fields(self):
        """Should exclude volatile fields from hash."""
        record1 = {
            "id": "test-001",
            "title": "Test Badge",
            "issued_at": "2024-01-15",
            "version": "1.0",
            "_ts": "2024-01-15T10:00:00Z",
            "image_url": "https://img.com/1",
        }
        record2 = {
            "id": "test-001",
            "title": "Test Badge",
            "issued_at": "2024-01-15",
            "version": "2.0",  # Different version
            "_ts": "2024-01-15T11:00:00Z",  # Different timestamp
            "image_url": "https://img.com/2",  # Different image
        }
        # Should produce same hash despite volatile field differences
        assert compute_content_hash(record1, "id") == compute_content_hash(record2, "id")

    def test_compute_content_hash_includes_content_fields(self):
        """Should include non-volatile fields in hash."""
        record1 = {"id": "test-001", "title": "Badge A", "issuer": "Issuer 1"}
        record2 = {"id": "test-001", "title": "Badge B", "issuer": "Issuer 1"}  # Different title
        record3 = {"id": "test-001", "title": "Badge A", "issuer": "Issuer 2"}  # Different issuer
        
        hash1 = compute_content_hash(record1, "id")
        hash2 = compute_content_hash(record2, "id")
        hash3 = compute_content_hash(record3, "id")
        
        assert hash1 != hash2  # Different title -> different hash
        assert hash1 != hash3  # Different issuer -> different hash

    def test_compute_content_hash_normalizes_lists(self):
        """Should normalize lists for stable hashing."""
        record1 = {"id": "test-001", "skills": ["B", "A", "C"]}
        record2 = {"id": "test-001", "skills": ["A", "B", "C"]}  # Different order
        assert compute_content_hash(record1, "id") == compute_content_hash(record2, "id")

    def test_compute_content_hash_normalizes_dicts(self):
        """Should normalize dicts for stable hashing."""
        record1 = {"id": "test-001", "metadata": {"b": 2, "a": 1}}
        record2 = {"id": "test-001", "metadata": {"a": 1, "b": 2}}
        assert compute_content_hash(record1, "id") == compute_content_hash(record2, "id")

    def test_compute_content_hash_excludes_id_field(self):
        """Should exclude the ID field itself from hash."""
        record1 = {"id": "test-001", "title": "Test"}
        record2 = {"id": "test-002", "title": "Test"}  # Different ID
        assert compute_content_hash(record1, "id") == compute_content_hash(record2, "id")


class TestExtractRecordId:
    """Tests for extract_record_id function."""

    @pytest.mark.parametrize("platform,record,expected_id", [
        ("microsoft-learn", {"id": "ACH001"}, "ACH001"),
        ("microsoft-learn", {"credentialId": "CRED001"}, "CRED001"),
        ("microsoft-learn", {"sourceUid": "UID001"}, "UID001"),
        ("google-skills", {"id": "123"}, "123"),
        ("google-skills", {"badge_id": "456"}, "456"),
        ("aws-skills", {"id": "aws-001"}, "aws-001"),
        ("credly", {"id": "badge-001"}, "badge-001"),
        ("linkedin-certifications", {"license": "LIC-001", "name": "Cert"}, "linkedin-LIC-001"),
        ("linkedin-certifications", {"name": "Cert"}, "linkedin-"),  # hash-based
        ("google-developer", {"title": "Badge", "date": "2024-01-15"}, "gdev-"),  # hash-based
    ])
    def test_extract_record_id_platforms(self, platform, record, expected_id):
        result = extract_record_id(record, "id", platform)
        if expected_id.endswith("-"):  # hash-based
            assert result.startswith(expected_id)
        else:
            assert result == expected_id

    def test_extract_record_id_fallback(self):
        """Should fall back to content hash when no ID fields present."""
        record = {"title": "Test", "data": "value"}
        result = extract_record_id(record, "id", "unknown-platform")
        assert result.startswith("auto-")


class TestBuildFingerprintIndex:
    """Tests for build_fingerprint_index function."""

    def test_build_fingerprint_index_basic(self):
        """Should build index from records."""
        records = [
            {"id": "1", "title": "Badge 1", "issued_at": "2024-01-15"},
            {"id": "2", "title": "Badge 2", "issued_at": "2024-01-16"},
        ]
        index = build_fingerprint_index(records, "id", "test-platform")
        
        assert len(index) == 2
        assert "1" in index
        assert "2" in index
        assert isinstance(index["1"], RecordFingerprint)
        assert index["1"].record_id == "1"
        assert index["1"].platform == "test-platform"

    def test_build_fingerprint_index_skips_no_id(self):
        """Should skip records with no identifiable ID."""
        records = [
            {"id": "1", "title": "Badge 1"},
            {"title": "Badge 2"},  # No ID - will get auto-generated ID
        ]
        index = build_fingerprint_index(records, "id", "test-platform")
        # Records without explicit ID get auto-generated IDs
        assert len(index) >= 1
        assert "1" in index


class TestLoadSaveBaseline:
    """Tests for baseline loading and saving."""

    def test_load_baseline_no_file(self, temp_dir):
        """Should return None when no baseline exists."""
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            result = load_baseline("test-platform")
            assert result is None

    def test_load_baseline_valid_file(self, temp_dir):
        """Should load valid baseline file."""
        baseline_data = {
            "platform": "test-platform",
            "record_count": 2,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                "1": {"record_id": "1", "content_hash": "abc123", "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"},
                "2": {"record_id": "2", "content_hash": "def456", "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"},
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            result = load_baseline("test-platform")
            assert result is not None
            assert len(result) == 2
            assert "1" in result

    def test_load_baseline_invalid_format(self, temp_dir):
        """Should return None for invalid baseline format."""
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps({"invalid": "format"}))
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            result = load_baseline("test-platform")
            assert result is None

    def test_save_baseline_creates_file(self, temp_dir):
        """Should save baseline atomically."""
        index = {
            "1": RecordFingerprint("1", "hash1", "test-platform", "2024-01-15T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test-platform", "2024-01-15T10:00:00Z"),
        }
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            result = save_baseline("test-platform", index)
            assert result is True
            
            baseline_path = Path(temp_dir) / "test-platform-baseline.json"
            assert baseline_path.exists()
            data = json.loads(baseline_path.read_text())
            assert data["platform"] == "test-platform"
            assert data["record_count"] == 2
            assert "1" in data["fingerprints"]


class TestCompareFingerprints:
    """Tests for compare_fingerprints function."""

    def test_compare_fingerprints_first_run(self):
        """First run (no baseline) should return all added."""
        incoming = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-15T10:00:00Z"),
        }
        report = compare_fingerprints(None, incoming, "test-platform")
        
        assert report.old_count == 0
        assert report.new_count == 2
        assert report.retained_count == 0
        assert report.modified_count == 0
        assert report.added_count == 2
        assert report.removed_count == 0
        assert report.retention_rate == 1.0

    def test_compare_fingerprints_all_retained(self):
        """All records retained with same hash."""
        baseline = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-15T10:00:00Z"),
        }
        incoming = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-16T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-16T10:00:00Z"),
        }
        report = compare_fingerprints(baseline, incoming, "test-platform")
        
        assert report.old_count == 2
        assert report.new_count == 2
        assert report.retained_count == 2
        assert report.modified_count == 0
        assert report.added_count == 0
        assert report.removed_count == 0
        assert report.retention_rate == 1.0

    def test_compare_fingerprints_modified(self):
        """Records with same ID but different hash should be modified."""
        baseline = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z"),
        }
        incoming = {
            "1": RecordFingerprint("1", "hash2", "test", "2024-01-16T10:00:00Z"),  # Different hash
        }
        report = compare_fingerprints(baseline, incoming, "test-platform")
        
        assert report.retained_count == 0
        assert report.modified_count == 1
        assert "1" in report.details["modified_ids"]

    def test_compare_fingerprints_added_removed(self):
        """Should track added and removed records."""
        baseline = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-15T10:00:00Z"),
        }
        incoming = {
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-16T10:00:00Z"),
            "3": RecordFingerprint("3", "hash3", "test", "2024-01-16T10:00:00Z"),
        }
        report = compare_fingerprints(baseline, incoming, "test-platform")
        
        assert report.retained_count == 1
        assert report.added_count == 1
        assert report.removed_count == 1
        assert "3" in report.details["added_ids"]
        assert "1" in report.details["removed_ids"]

    def test_compare_fingerprints_integrity_score(self):
        """Integrity score should reflect data quality."""
        # Perfect retention
        baseline = {"1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z")}
        incoming = {"1": RecordFingerprint("1", "hash1", "test", "2024-01-16T10:00:00Z")}
        report = compare_fingerprints(baseline, incoming, "test-platform")
        assert report.integrity_score == 1.0
        
        # 50% removal
        baseline = {
            "1": RecordFingerprint("1", "hash1", "test", "2024-01-15T10:00:00Z"),
            "2": RecordFingerprint("2", "hash2", "test", "2024-01-15T10:00:00Z"),
        }
        incoming = {"1": RecordFingerprint("1", "hash1", "test", "2024-01-16T10:00:00Z")}
        report = compare_fingerprints(baseline, incoming, "test-platform")
        # retention=0.5, modification=0, removal=0.5, addition=0
        # score = 0.4*0.5 + 0.2*1 + 0.2*0.5 + 0.2*1 = 0.2 + 0.2 + 0.1 + 0.2 = 0.7
        assert 0.6 < report.integrity_score < 0.8


class TestExecuteContentLossGuard:
    """Tests for execute_content_loss_guard main function."""

    def test_execute_content_loss_guard_first_run(self, temp_dir):
        """First run should pass and create baseline."""
        records = [
            {"id": "1", "title": "Badge 1", "issued_at": "2024-01-15"},
            {"id": "2", "title": "Badge 2", "issued_at": "2024-01-16"},
        ]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            report = execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=True)
            
            assert report.old_count == 0
            assert report.new_count == 2
            # Baseline should be created
            baseline_path = Path(temp_dir) / "test-platform-baseline.json"
            assert baseline_path.exists()

    def test_execute_content_loss_guard_pass(self, temp_dir):
        """Matching baseline should pass."""
        # Create records that will generate known hashes
        records_for_baseline = [
            {"id": "1", "title": "Badge 1", "issued_at": "2024-01-15", "issuer": "Test"},
            {"id": "2", "title": "Badge 2", "issued_at": "2024-01-16", "issuer": "Test"},
        ]
        
        # Compute hashes for baseline
        from loss_guard import compute_content_hash
        hash1 = compute_content_hash(records_for_baseline[0], "id")
        hash2 = compute_content_hash(records_for_baseline[1], "id")
        
        # Create baseline with computed hashes
        baseline_data = {
            "platform": "test-platform",
            "record_count": 2,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                "1": {"record_id": "1", "content_hash": hash1, "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"},
                "2": {"record_id": "2", "content_hash": hash2, "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"},
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # Use same records for incoming
        records = [
            {"id": "1", "title": "Badge 1", "issued_at": "2024-01-15", "issuer": "Test"},
            {"id": "2", "title": "Badge 2", "issued_at": "2024-01-16", "issuer": "Test"},
        ]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            report = execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=True)
            
            assert report.retention_rate == 1.0

    def test_execute_content_loss_guard_fail_retention(self, temp_dir):
        """Should fail when retention rate below threshold."""
        # Create baseline with 10 records
        baseline_data = {
            "platform": "test-platform",
            "record_count": 10,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                str(i): {"record_id": str(i), "content_hash": f"hash{i}", "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"}
                for i in range(10)
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # Incoming only 7 records (30% loss > 15% default threshold)
        records = [{"id": str(i), "title": f"Badge {i}", "issued_at": "2024-01-15"} for i in range(7)]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            with pytest.raises(PipelineDataLossAnomaly) as exc_info:
                execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=True)
            
            assert "Retention rate" in str(exc_info.value)

    def test_execute_content_loss_guard_fail_modification(self, temp_dir):
        """Should fail when modification rate exceeds threshold."""
        # Create baseline
        baseline_data = {
            "platform": "test-platform",
            "record_count": 10,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                str(i): {"record_id": str(i), "content_hash": f"hash{i}", "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"}
                for i in range(10)
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # Incoming with 4 modified records (40% > 30% default threshold)
        records = []
        for i in range(10):
            if i < 4:
                records.append({"id": str(i), "title": f"Modified Badge {i}", "issued_at": "2024-01-15"})  # Different content
            else:
                records.append({"id": str(i), "title": f"Badge {i}", "issued_at": "2024-01-15"})
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            with pytest.raises(PipelineDataLossAnomaly) as exc_info:
                execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=True)
            
            assert "Modification rate" in str(exc_info.value)

    def test_execute_content_loss_guard_warn_removal(self, temp_dir):
        """Should warn (not fail by default) on removal rate."""
        baseline_data = {
            "platform": "test-platform",
            "record_count": 10,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                str(i): {"record_id": str(i), "content_hash": f"hash{i}", "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"}
                for i in range(10)
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # 3 removed (30% > 15% threshold) but retention OK
        records = [{"id": str(i), "title": f"Badge {i}", "issued_at": "2024-01-15"} for i in range(7)]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            # With fail_on_warn=True (default), it should fail on warning too
            with pytest.raises(PipelineDataLossAnomaly):
                execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=True)
            
            # With fail_on_warn=False, should pass with warning
            report = execute_content_loss_guard(records, "test-platform", "id", fail_on_warn=False)
            assert report.removed_count == 3

    def test_execute_content_loss_guard_platform_thresholds(self, temp_dir):
        """Should use platform-specific thresholds."""
        # Microsoft Learn has stricter thresholds (min_retention_rate: 0.90)
        # Create baseline with 100 records that have known content
        baseline_records = [{"id": str(i), "title": f"Badge {i}", "issued_at": "2024-01-15", "issuer": "Test"} for i in range(100)]
        
        from loss_guard import compute_content_hash
        baseline_data = {
            "platform": "microsoft-learn",
            "record_count": 100,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                str(i): {"record_id": str(i), "content_hash": compute_content_hash(baseline_records[i], "id"), "platform": "microsoft-learn", "timestamp": "2024-01-15T10:00:00Z"}
                for i in range(100)
            },
        }
        baseline_path = Path(temp_dir) / "microsoft-learn-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # 89 retained (89% < 90% threshold for MS Learn) - use first 89 records
        records = baseline_records[:89]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            with pytest.raises(PipelineDataLossAnomaly) as exc_info:
                execute_content_loss_guard(records, "microsoft-learn", "id", fail_on_warn=True)
            
            assert "Retention rate" in str(exc_info.value)

    def test_execute_content_loss_guard_custom_thresholds(self, temp_dir):
        """Should allow custom threshold overrides."""
        baseline_records = [{"id": str(i), "title": f"Badge {i}", "issued_at": "2024-01-15", "issuer": "Test"} for i in range(100)]
        
        from loss_guard import compute_content_hash
        baseline_data = {
            "platform": "test-platform",
            "record_count": 100,
            "created_at": "2024-01-15T10:00:00Z",
            "fingerprints": {
                str(i): {"record_id": str(i), "content_hash": compute_content_hash(baseline_records[i], "id"), "platform": "test-platform", "timestamp": "2024-01-15T10:00:00Z"}
                for i in range(100)
            },
        }
        baseline_path = Path(temp_dir) / "test-platform-baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_data))
        
        # 85 retained - 85% retention, 15% removal (at default threshold)
        records = baseline_records[:85]
        
        with patch("loss_guard.VALIDATION_DIR", str(temp_dir)):
            report = execute_content_loss_guard(
                records, "test-platform", "id",
                thresholds={"min_retention_rate": 0.80, "max_removal_rate": 0.50},
                fail_on_warn=True
            )
            assert report.retention_rate == 0.85


class TestThresholdConstants:
    """Tests for threshold constants."""

    def test_default_thresholds_exist(self):
        """Default thresholds should be defined."""
        assert "min_retention_rate" in DEFAULT_THRESHOLDS
        assert "max_modification_rate" in DEFAULT_THRESHOLDS
        assert "max_removal_rate" in DEFAULT_THRESHOLDS
        assert "min_integrity_score" in DEFAULT_THRESHOLDS

    def test_platform_thresholds_exist(self):
        """Platform-specific thresholds should be defined for all platforms."""
        expected_platforms = [
            "microsoft-learn", "google-skills", "aws-skills",
            "credly", "linkedin-certifications", "google-developer"
        ]
        for platform in expected_platforms:
            assert platform in PLATFORM_THRESHOLDS
            assert "min_retention_rate" in PLATFORM_THRESHOLDS[platform]