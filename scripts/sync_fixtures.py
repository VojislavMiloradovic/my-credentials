"""
sync_fixtures.py
----------------
Syncs baseline files from for_validation/ to tests/fixtures/ for loss_guard cross-artifact validation tests.
Run automatically at the end of each update pipeline.

NOTE: Does NOT sync main validation files (they contain production data).
Test fixtures in tests/fixtures/ must remain small, controlled test data.
"""

import shutil
from pathlib import Path

# Mapping: platform -> list of (source_file, destination_file)
# ONLY syncs baseline files from for_validation/
FIXTURE_MAP = {
    "microsoft-learn": [
        (
            "for_validation/microsoft-learn-baseline.json",
            "tests/fixtures/microsoft_learn/baseline.json",
        ),
    ],
    "google-skills": [
        (
            "for_validation/google-skills-baseline.json",
            "tests/fixtures/google_skills/baseline.json",
        ),
    ],
    "aws-skills": [
        (
            "for_validation/aws-skills-baseline.json",
            "tests/fixtures/aws_skills/baseline.json",
        ),
    ],
    "credly": [
        ("for_validation/credly-baseline.json", "tests/fixtures/credly/baseline.json"),
    ],
    "linkedin-certifications": [
        (
            "for_validation/linkedin-certifications-baseline.json",
            "tests/fixtures/linkedin/baseline.json",
        ),
    ],
    "google-developer": [
        (
            "for_validation/google-developer-combined-baseline.json",
            "tests/fixtures/google_developer/combined_baseline.json",
        ),
        (
            "for_validation/google-developer-detailed_learnings-baseline.json",
            "tests/fixtures/google_developer/detailed_learnings_baseline.json",
        ),
        (
            "for_validation/google-developer-public_badges-baseline.json",
            "tests/fixtures/google_developer/public_badges_baseline.json",
        ),
    ],
}


def sync_fixtures(platform: str, verbose: bool = True) -> int:
    """
    Sync baseline files from for_validation to tests/fixtures for a platform.

    Args:
        platform: Platform identifier (e.g., "microsoft-learn")
        verbose: Print sync status

    Returns:
        Number of files synced
    """
    if platform not in FIXTURE_MAP:
        if verbose:
            print(f"  [SYNC] Unknown platform: {platform}")
        return 0

    synced = 0
    for src, dst in FIXTURE_MAP[platform]:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            if verbose:
                print(f"  [SYNC] Source not found: {src}")
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)

        if verbose:
            print(f"  [SYNC] {src} -> {dst}")
        synced += 1

    return synced


def sync_all_platforms(verbose: bool = True) -> int:
    """Sync fixtures for all platforms."""
    total = 0
    for platform in FIXTURE_MAP:
        total += sync_fixtures(platform, verbose=verbose)
    return total


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        platform = sys.argv[1]
        synced = sync_fixtures(platform)
        print(f"Synced {synced} file(s) for {platform}")
    else:
        synced = sync_all_platforms()
        print(f"Synced {synced} file(s) for all platforms")
