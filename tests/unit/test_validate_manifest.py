"""
Unit tests for validate_manifest.py module.
"""
import os
import sys
import tempfile

import pytest


class TestValidateManifest:
    """Tests for validate_manifest module."""

    def test_load_manifest_imports(self):
        """Test that the module can be imported."""
        import validate_manifest
        assert hasattr(validate_manifest, 'validate_manifest')
        assert hasattr(validate_manifest, 'validate_artifact_consistency')
        assert hasattr(validate_manifest, 'validate_transform_types')
        assert hasattr(validate_manifest, 'main')

    def test_validate_manifest_success(self):
        """Test validate_manifest function with valid manifest."""
        # Create a temporary valid manifest
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "extract_achievements_dedupe_by_id"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["readme"]
      metrics: ["units", "achievements"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)

            # Change to temp directory
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from models.layer_manifest import load_manifest
                manifest = load_manifest()
                assert manifest.version == 1
                assert "microsoft-learn" in manifest.platforms
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_validate_artifact_consistency(self):
        """Test validate_artifact_consistency function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create archives directory
            archives_dir = os.path.join(tmpdir, "archives")
            os.makedirs(archives_dir)
            
            # Create manifest
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "extract_achievements_dedupe_by_id"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["archive_index"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)
            
            # Create required archive files
            with open(os.path.join(archives_dir, "microsoft-learn-archive.md"), "w") as f:
                f.write("# Archive")
            with open(os.path.join(archives_dir, "microsoft-learn-index.md"), "w") as f:
                f.write("# Index")
            
            # Create cross-platform artifacts
            with open(os.path.join(tmpdir, "credentials.jsonld"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# README")
            with open(os.path.join(tmpdir, "llms.txt"), "w") as f:
                f.write("# llms.txt")
            with open(os.path.join(tmpdir, "llms-full.txt"), "w") as f:
                f.write("# llms-full.txt")

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import validate_artifact_consistency
                result = validate_artifact_consistency()
                assert result is True
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_validate_transform_types(self):
        """Test validate_transform_types function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "extract_achievements_dedupe_by_id"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["readme"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import validate_transform_types
                result = validate_transform_types()
                assert result is True
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_validate_transform_types_invalid(self):
        """Test validate_transform_types with invalid transform type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "invalid_transform_type"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["readme"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import validate_transform_types
                result = validate_transform_types()
                assert result is False
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_validate_transform_types_with_transforms_dict(self):
        """Test validate_transform_types with transforms dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transforms:
        stream1:
          type: "extract_achievements_dedupe_by_id"
        stream2:
          type: "parse_csv_combine_retired_flags"
      output_streams: ["stream1", "stream2"]
    L2_published:
      source_layer: "L1_normalized"
      transforms:
        archive:
          type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transforms:
        readme:
          type: "compute_display_metrics"
      artifacts: ["readme"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import validate_transform_types
                result = validate_transform_types()
                assert result is True
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)


class TestValidateManifestMain:
    """Tests for main function."""

    def test_main_all_pass(self):
        """Test main function when all validations pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archives_dir = os.path.join(tmpdir, "archives")
            os.makedirs(archives_dir)
            
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "extract_achievements_dedupe_by_id"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["archive_index"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)
            
            with open(os.path.join(archives_dir, "microsoft-learn-archive.md"), "w") as f:
                f.write("# Archive")
            with open(os.path.join(archives_dir, "microsoft-learn-index.md"), "w") as f:
                f.write("# Index")
            with open(os.path.join(tmpdir, "credentials.jsonld"), "w") as f:
                f.write("{}")
            with open(os.path.join(tmpdir, "README.md"), "w") as f:
                f.write("# README")
            with open(os.path.join(tmpdir, "llms.txt"), "w") as f:
                f.write("# llms.txt")
            with open(os.path.join(tmpdir, "llms-full.txt"), "w") as f:
                f.write("# llms-full.txt")

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import main
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)

    def test_main_fail(self):
        """Test main function when validation fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = os.path.join(tmpdir, "dataset_layers.yaml")
            manifest_content = """
version: "1.0"
platforms:
  microsoft-learn:
    L0_raw:
      source: "data/ms-learn.csv"
    L1_normalized:
      source_layer: "L0_raw"
      transform:
        type: "invalid_type"
      output_records: "achievements"
    L2_published:
      source_layer: "L1_normalized"
      transform:
        type: "1:1_pass_through"
      artifacts: ["archive"]
    L3_display:
      source_layer: "L2_published"
      transform:
        type: "compute_display_metrics"
      artifacts: ["archive_index"]
      metrics: ["units"]
"""
            with open(manifest_path, "w") as f:
                f.write(manifest_content)

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            sys.path.insert(0, tmpdir)
            try:
                from validate_manifest import main
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
            finally:
                os.chdir(old_cwd)
                sys.path.remove(tmpdir)
