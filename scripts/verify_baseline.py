"""Verify baseline fingerprints match validation data records."""

import json
import sys
from pathlib import Path

VALIDATION_DIR = "for_validation"
THRESHOLD = 0.05

# Map platform keys to their validation file names
VALIDATION_FILES = {
    "microsoft-learn": "microsoft-learn.json",
    "google-skills": "google_skills_badges.json",
    "aws-skills": "aws_skill_badges.json",
    "credly": "credly_badges.json",
    "linkedin-certifications": "linkedin-certifications.json",
    "google-developer": "google-developer.json",
}

# Which key to count as "records" in validation files (should match baseline)
VALIDATION_COUNT_KEY = {
    "microsoft-learn": "achievements",
    "google-skills": "badges",
    "aws-skills": "badges",
    "credly": "credentials",
    "linkedin-certifications": "certifications",
    "google-developer": "combined_feed",
}

PLATFORMS = list(VALIDATION_FILES.keys())


def count_baseline_fingerprints(platform: str) -> int:
    p = Path(VALIDATION_DIR) / f"{platform}-baseline.json"
    if not p.exists():
        return 0
    with open(p, "r", encoding="utf-8") as f:
        return len(json.load(f).get("fingerprints", {}))


def count_validation_records(platform: str) -> int:
    fname = VALIDATION_FILES.get(platform)
    if not fname:
        return 0
    p = Path(VALIDATION_DIR) / fname
    if not p.exists():
        return 0
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    key = VALIDATION_COUNT_KEY.get(platform)
    if not key or key not in data or not isinstance(data[key], list):
        return 0
    return len([r for r in data[key] if isinstance(r, dict)])


def main() -> int:
    failed = False
    for platform in PLATFORMS:
        b = count_baseline_fingerprints(platform)
        v = count_validation_records(platform)
        if b == 0 and v == 0:
            print(f"  {platform}: SKIP")
            continue
        if b == 0:
            print(f"  {platform}: FAIL - baseline missing, validation has {v}")
            failed = True
            continue
        if v == 0:
            print(
                f"  {platform}: WARN - baseline has {b} fingerprints but no validation data"
            )
            continue
        mismatch = abs(b - v) / max(b, v)
        status = "FAIL" if mismatch > THRESHOLD else "OK"
        print(
            f"  {platform}: {status} - baseline={b}, validation={v}, mismatch={mismatch:.1%}"
        )
        if status == "FAIL":
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
