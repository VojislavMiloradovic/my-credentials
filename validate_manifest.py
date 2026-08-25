"""
validate_manifest.py
====================

CI validation script for dataset_layers.yaml manifest.
Validates that the manifest conforms to the Pydantic schema and
that all declared artifacts/files exist in the repository.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from models.layer_manifest import load_manifest


def validate_manifest() -> bool:
    """Validate the dataset_layers.yaml manifest."""
    print("🔍 Validating dataset_layers.yaml manifest...")

    try:
        manifest = load_manifest()
        print(f"✅ Manifest loaded successfully (version {manifest.version})")
    except Exception as e:
        print(f"❌ Manifest validation failed: {e}")
        return False

    # Check all platforms have all 4 layers
    required_layers = ["L0_raw", "L1_normalized", "L2_published", "L3_display"]
    platforms = manifest.platforms

    for platform_key, platform_layers in platforms.items():
        print(f"\n📋 Checking platform: {platform_key}")

        for layer_name in required_layers:
            layer_def = getattr(platform_layers, layer_name, None)
            if not layer_def:
                print(f"  ❌ Missing layer: {layer_name}")
                return False
            print(f"  ✅ Layer {layer_name} present")

            # Validate source/source_layer consistency
            if layer_name == "L0_raw":
                if not layer_def.source and not layer_def.sources:
                    print("  ⚠️  L0_raw should have source or sources")
            else:
                if not layer_def.source_layer:
                    print(f"  ⚠️  {layer_name} should have source_layer")

        # Check L1_normalized has output_records or output_streams
        l1 = platform_layers.L1_normalized
        if not l1.output_records and not l1.output_streams:
            print("  ⚠️  L1_normalized should have output_records or output_streams")

        # Check L2_published has artifacts
        l2 = platform_layers.L2_published
        if not l2.artifacts:
            print("  ⚠️  L2_published should have artifacts")

        # Check L3_display has metrics
        l3 = platform_layers.L3_display
        if not l3.metrics:
            print("  ⚠️  L3_display should have metrics")

    print(f"\n✅ All {len(platforms)} platforms validated successfully")
    return True


def validate_artifact_consistency() -> bool:
    """Validate that manifest artifacts match generated files."""
    print("\n🔍 Validating artifact consistency with repository...")

    try:
        manifest = load_manifest()
    except Exception as e:
        print(f"❌ Could not load manifest: {e}")
        return False

    archive_dir = Path("archives")
    all_ok = True

    for platform_key, platform_layers in manifest.platforms.items():
        # Check L2_published artifacts
        l2 = platform_layers.L2_published
        for artifact in l2.artifacts:
            expected_file = archive_dir / f"{platform_key}-{artifact}.md"
            if not expected_file.exists():
                print(f"  ⚠️  Missing artifact file: {expected_file}")
                all_ok = False
            else:
                print(f"  ✅ Found: {expected_file}")

        # Check L3_display artifacts that are files
        l3 = platform_layers.L3_display
        for artifact in l3.artifacts:
            if artifact == "archive_index":
                expected_file = archive_dir / f"{platform_key}-index.md"
                if not expected_file.exists():
                    print(f"  ⚠️  Missing artifact file: {expected_file}")
                    all_ok = False
                else:
                    print(f"  ✅ Found: {expected_file}")

    # Check cross-platform artifacts
    cross_artifacts = {
        "jsonld": Path("credentials.jsonld"),
        "readme": Path("README.md"),
        "llms_txt": Path("llms.txt"),
        "llms_full": Path("llms-full.txt"),
    }

    for filepath in cross_artifacts.values():
        if filepath.exists():
            print(f"  ✅ Found: {filepath}")
        else:
            print(f"  ⚠️  Missing cross-platform artifact: {filepath}")
            all_ok = False

    if all_ok:
        print("\n✅ All artifact files present")
    else:
        print(
            "\n⚠️  Some artifact files are missing (may be generated after pipeline runs)"
        )

    return all_ok


def validate_transform_types() -> bool:
    """Validate that transform types are recognized."""
    print("\n🔍 Validating transform types...")

    valid_transforms = {
        "1:1_pass_through",
        "extract_achievements_dedupe_by_id",
        "combine_streams",
        "split_streams",
        "compute_display_metrics",
        "count_streams_separately",
        "parse_csv_combine_retired_flags",
        "count_active_and_retired",
        "extract_milestone_badges_dedupe",
        "parse_local_learnings_dedupe",
        "parse_mhtml_codelabs",
    }

    try:
        manifest = load_manifest()
    except Exception as e:
        print(f"❌ Could not load manifest: {e}")
        return False

    all_ok = True
    for platform_key, platform_layers in manifest.platforms.items():
        for layer_name in ["L1_normalized", "L2_published", "L3_display"]:
            layer_def = getattr(platform_layers, layer_name, None)
            if not layer_def:
                continue

            # Check single transform
            if layer_def.transform:
                if layer_def.transform.type not in valid_transforms:
                    print(
                        f"  ❌ Unknown transform type: {layer_def.transform.type} (platform: {platform_key}, layer: {layer_name})"
                    )
                    all_ok = False
                else:
                    print(
                        f"  ✅ {platform_key}.{layer_name}.transform: {layer_def.transform.type}"
                    )

            # Check multiple transforms
            if layer_def.transforms:
                for stream_name, transform in layer_def.transforms.items():
                    if transform.type not in valid_transforms:
                        print(
                            f"  ❌ Unknown transform type: {transform.type} (platform: {platform_key}, layer: {layer_name}, stream: {stream_name})"
                        )
                        all_ok = False
                    else:
                        print(
                            f"  ✅ {platform_key}.{layer_name}.transforms.{stream_name}: {transform.type}"
                        )

    if all_ok:
        print("\n✅ All transform types recognized")

    return all_ok


def main():
    """Main validation entry point."""
    print("=" * 60)
    print("📋 Dataset Layer Manifest Validation")
    print("=" * 60)

    checks = [
        ("Manifest Schema", validate_manifest),
        ("Transform Types", validate_transform_types),
        ("Artifact Consistency", validate_artifact_consistency),
    ]

    results = []
    for name, check_fn in checks:
        print(f"\n--- {name} ---")
        result = check_fn()
        results.append((name, result))

    print("\n" + "=" * 60)
    print("📊 Validation Summary")
    print("=" * 60)

    all_passed = True
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} {name}")
        if not result:
            all_passed = False

    if all_passed:
        print("\n🎉 All validations passed!")
        sys.exit(0)
    else:
        print("\n❌ Some validations failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
