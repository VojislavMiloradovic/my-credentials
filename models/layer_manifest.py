"""
Layer Manifest Schema
=====================
Pydantic models for dataset_layers.yaml validation.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LayerTransform(BaseModel):
    """Single transformation definition."""

    type: Literal[
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
    ]
    params: dict = Field(default_factory=dict)


class LayerDef(BaseModel):
    """Definition of a single dataset layer."""

    source_layer: str | None = None
    source: str | list[str] | None = None
    sources: list[str] | None = None
    transform: LayerTransform | None = None
    transforms: dict[str, LayerTransform] | None = None
    output_records: str | None = None
    output_streams: list[str] | None = None
    retired_handling: Literal[
        "none", "registry_only", "combine_source_and_registry"
    ] = "none"
    artifacts: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    description: str = ""


class PlatformLayers(BaseModel):
    """All four layers for one platform."""

    L0_raw: LayerDef
    L1_normalized: LayerDef
    L2_published: LayerDef
    L3_display: LayerDef


class LayerManifest(BaseModel):
    """Root manifest document."""

    version: int
    platforms: dict[str, PlatformLayers]


MANIFEST_PATH = Path("dataset_layers.yaml")


def load_manifest() -> LayerManifest:
    """Load and validate dataset_layers.yaml."""
    import yaml

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return LayerManifest(**data)


def get_platform_layers(platform: str) -> PlatformLayers:
    """Get layer definitions for a platform."""
    return load_manifest().platforms[platform]


def get_layer_def(platform: str, layer: str) -> LayerDef:
    """Get a specific layer definition."""
    platform_layers = get_platform_layers(platform)
    return getattr(platform_layers, layer)


def get_artifact_layer_mapping() -> dict[str, str]:
    """Return mapping of artifact name -> layer name for all platforms."""
    manifest = load_manifest()
    mapping = {}
    for platform, layers in manifest.platforms.items():
        for layer_name in ("L2_published", "L3_display"):
            layer_def = getattr(layers, layer_name)
            for artifact in layer_def.artifacts:
                mapping[f"{platform}:{artifact}"] = layer_name
    return mapping


def get_all_platform_layers() -> dict[str, PlatformLayers]:
    """Get layer definitions for ALL platforms.

    Returns:
        Dictionary mapping platform key to its PlatformLayers object.
        Use this when you need to iterate over all platforms.
    """
    return load_manifest().platforms


def get_platforms_with_l2_artifact(artifact: str) -> list[str]:
    """Return platform keys that have a specific artifact in L2_published.

    Args:
        artifact: The logical artifact name to search for. Supported aliases:
            - "archive_complete" or "complete" (maps to manifest "complete")
            - "archive_index" or "index" (maps to manifest "index")
            - "jsonld" (maps to manifest "complete" since JSON-LD is generated from complete)

    Returns:
        List of platform keys that have this artifact in their L2_published layer.
        Empty list if none found.
    """
    # Map logical artifact names to manifest artifact names
    artifact_map = {
        "archive_complete": "complete",
        "complete": "complete",
        "archive_index": "index",
        "index": "index",
        "jsonld": "complete",  # JSON-LD is generated from complete archive
    }
    manifest_artifact = artifact_map.get(artifact, artifact)

    manifest = load_manifest()
    result = []
    for platform, layers in manifest.platforms.items():
        if hasattr(layers, "L2_published"):
            l2_artifacts = getattr(layers.L2_published, "artifacts", [])
            if manifest_artifact in l2_artifacts:
                result.append(platform)
    return result
