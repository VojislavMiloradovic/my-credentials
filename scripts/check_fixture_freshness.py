"""
Fixture Freshness Check
=======================
Checks if validation fixtures are stale and need manual refresh.
Run as: python scripts/check_fixture_freshness.py [--threshold DAYS] [--fail-on-stale]
"""

import argparse
import hashlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Tuple

# Platform fixture mapping
PLATFORM_FIXTURES = {
    "microsoft-learn": [
        "for_validation/microsoft-learn.json",
        "for_validation/microsoft-learn-baseline.json",
    ],
    "google-skills": [
        "for_validation/google_skills_badges.json",
        "for_validation/google-skills-baseline.json",
    ],
    "aws-skills": [
        "for_validation/aws_skill_badges.json",
        "for_validation/aws-skills-baseline.json",
    ],
    "credly": [
        "for_validation/credly_badges.json",
        "for_validation/credly-baseline.json",
    ],
    "linkedin-certifications": [
        "for_validation/linkedin-certifications.json",
        "for_validation/linkedin-certifications-baseline.json",
    ],
    "google-developer": [
        "for_validation/google-developer.json",
        "for_validation/google-developer-combined-baseline.json",
        "for_validation/google-developer-detailed_learnings-baseline.json",
        "for_validation/google-developer-public_badges-baseline.json",
    ],
}

# Transform types per platform from dataset_layers.yaml
# Used to detect when pipeline logic changes requiring fixture update
TRANSFORM_TYPES = {
    "microsoft-learn": ["extract_achievements_dedupe_by_id"],
    "google-skills": ["1:1_pass_through"],
    "aws-skills": ["parse_csv_combine_retired_flags"],
    "credly": ["extract_milestone_badges_dedupe"],
    "linkedin-certifications": ["1:1_pass_through"],
    "google-developer": ["parse_mhtml_codelabs", "parse_local_learnings_dedupe"],
}


def get_file_age_days(filepath: Path) -> float | None:
    """Get file age in days based on git log (last commit touching file) or mtime."""
    try:
        # Try git log first (more accurate for fixture updates)
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", str(filepath)],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            timestamp = int(result.stdout.strip())
            file_time = datetime.fromtimestamp(timestamp, tz=UTC)
        else:
            # Fallback to mtime
            stat = filepath.stat()
            file_time = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

        age = datetime.now(UTC) - file_time
        return age.total_seconds() / 86400
    except Exception:
        return None


def get_transform_hash(platform: str) -> str | None:
    """Get hash of transform types for a platform from dataset_layers.yaml."""
    try:
        import yaml

        with open("dataset_layers.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        platform_data = data.get("platforms", {}).get(platform, {})

        # Collect all transform types across layers
        transforms = []
        for layer_name in ("L1_normalized", "L2_published", "L3_display"):
            layer = platform_data.get(layer_name, {})
            if layer.get("transform"):
                transforms.append(layer["transform"]["type"])
            if layer.get("transforms"):
                for t in layer["transforms"].values():
                    transforms.append(t["type"])

        # Sort for consistent hashing
        transforms.sort()
        # Use stable hash via hashlib
        return hashlib.sha256(str(tuple(transforms)).encode()).hexdigest()[:16]
    except Exception:
        return None


def check_fixture_freshness(
    threshold_days: int = 90,
    fail_on_stale: bool = False,
    verbose: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """
    Check all platform fixtures for freshness.

    Returns:
        (stale_fixtures, missing_fixtures, transform_changed)
    """
    stale = []
    missing = []
    transform_changed = []

    print(f"Checking fixture freshness (threshold: {threshold_days} days)...\n")

    for platform, fixtures in PLATFORM_FIXTURES.items():
        platform_stale = []
        platform_missing = []

        # Check transform hash
        current_hash = get_transform_hash(platform)
        hash_file = Path(f"for_validation/.{platform}_transform_hash")

        if current_hash:
            if hash_file.exists():
                with open(hash_file, "r") as f:
                    stored_hash = f.read().strip()
                if stored_hash != current_hash:
                    transform_changed.append(
                        f"{platform}: Transform types changed (was {stored_hash}, now {current_hash})"
                    )
            else:
                # First run - store current hash
                with open(hash_file, "w") as f:
                    f.write(current_hash)

        for fixture in fixtures:
            path = Path(fixture)
            if not path.exists():
                platform_missing.append(fixture)
                continue

            age = get_file_age_days(path)
            if age is not None and age > threshold_days:
                platform_stale.append(f"{fixture} ({age:.1f} days)")

        if platform_missing:
            missing.extend(platform_missing)
            print(f"  [MISSING] {platform}: MISSING fixtures:")
            for m in platform_missing:
                print(f"     - {m}")

        if platform_stale:
            stale.extend(platform_stale)
            print(f"  [STALE] {platform}: STALE fixtures:")
            for s in platform_stale:
                print(f"     - {s}")

        if not platform_stale and not platform_missing and verbose:
            print(f"  [OK] {platform}: All fixtures fresh")

    return stale, missing, transform_changed


def print_refresh_instructions(platform: str) -> None:
    """Print platform-specific fixture refresh instructions."""
    instructions = {
        "microsoft-learn": (
            "1. Export JSON from Microsoft Learn profile\n"
            "2. Save as data/microsoft-learn.json\n"
            "3. Run: python update_ms_learn.py\n"
            "4. Copy for_validation/microsoft-learn.json to fixture if needed"
        ),
        "google-skills": (
            "1. Update google_skills_badges.json fixture from live profile\n"
            "2. Or run: python update_google_skills.py (requires Playwright/API)\n"
            "3. Copy for_validation/google_skills_badges.json to tests/fixtures/google_skills/profile.json"
        ),
        "aws-skills": (
            "1. Export CSV from AWS Skill Builder\n"
            "2. Save as data/aws_skills.csv\n"
            "3. Run: python update_aws_skills.py\n"
            "4. Copy for_validation/aws_skill_badges.json to fixture"
        ),
        "credly": (
            "1. Fetch from Credly API (requires CREDLY_USER/CREDLY_USER_ID env vars)\n"
            "2. Run: python update_credly_badges.py\n"
            "3. Copy for_validation/credly_badges.json to tests/fixtures/credly/api_page1.json"
        ),
        "linkedin-certifications": (
            "1. Export CSV from LinkedIn\n"
            "2. Save as data/Certifications.csv\n"
            "3. Run: python update_linkedin.py\n"
            "4. Copy for_validation/linkedin-certifications.json to fixture"
        ),
        "google-developer": (
            "1. Export MHTML codelabs + local learnings text\n"
            "2. Save to data/\n"
            "3. Run: python update_google_developer.py\n"
            "4. Copy for_validation/google-developer.json to fixture"
        ),
    }

    print(f"\n📋 Refresh instructions for {platform}:")
    print(instructions.get(platform, "No specific instructions available."))


def main():
    parser = argparse.ArgumentParser(
        description="Check validation fixture freshness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/check_fixture_freshness.py
  python scripts/check_fixture_freshness.py --threshold 60
  python scripts/check_fixture_freshness.py --fail-on-stale --threshold 90
        """,
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=90,
        help="Days after which fixture is considered stale (default: 90)",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit with code 1 if any fixtures are stale",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show fresh fixtures too",
    )
    parser.add_argument(
        "--platform",
        help="Check only specific platform",
    )

    args = parser.parse_args()

    # Filter platforms if specified
    global PLATFORM_FIXTURES
    if args.platform:
        if args.platform in PLATFORM_FIXTURES:
            PLATFORM_FIXTURES = {args.platform: PLATFORM_FIXTURES[args.platform]}
        else:
            print(f"Unknown platform: {args.platform}")
            sys.exit(1)

    stale, missing, transform_changed = check_fixture_freshness(
        threshold_days=args.threshold,
        fail_on_stale=args.fail_on_stale,
        verbose=args.verbose,
    )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if missing:
        print(f"[MISSING] Missing fixtures: {len(missing)}")
        for m in missing:
            print(f"   - {m}")

    if stale:
        print(f"[STALE] Stale fixtures (> {args.threshold} days): {len(stale)}")
        for s in stale:
            print(f"   - {s}")

        # Show refresh instructions for platforms with stale fixtures
        platforms_with_stale = set()
        for s in stale:
            for platform, fixtures in PLATFORM_FIXTURES.items():
                for fix in fixtures:
                    if fix in s:
                        platforms_with_stale.add(platform)

        for platform in platforms_with_stale:
            print_refresh_instructions(platform)
    else:
        print("[OK] No stale fixtures found")

    if transform_changed:
        print(f"\n[TRANSFORM] Transform changes detected: {len(transform_changed)}")
        for t in transform_changed:
            print(f"   - {t}")
        print(
            "\n   Run fixture refresh for affected platforms after updating transforms."
        )

    # Exit code
    if args.fail_on_stale and (stale or missing):
        sys.exit(1)
    elif stale and not args.fail_on_stale:
        sys.exit(0)  # Warning only
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
