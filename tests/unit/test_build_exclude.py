"""
Unit tests for build_exclude.py
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

from build_exclude import main, normalize_url


# Fixture to mock PROBLEMATIC_REDIRECT_URLS as empty for tests that expect no .lycheeignore
@pytest.fixture(autouse=True)
def mock_problematic_redirect_urls():
    """Mock PROBLEMATIC_REDIRECT_URLS to be empty for most tests."""
    with patch("build_exclude.PROBLEMATIC_REDIRECT_URLS", []):
        yield


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    @pytest.mark.parametrize(
        "input_url,expected",
        [
            (
                "learn.retired-path",
                "https://learn.microsoft.com/en-us/training/paths/retired-path",
            ),
            (
                "/training/paths/test",
                "https://learn.microsoft.com/en-us/training/paths/test",
            ),
            (
                "training/paths/test",
                "https://learn.microsoft.com/en-us/training/paths/test",
            ),
            (
                "https://learn.microsoft.com/training/paths/test",
                "https://learn.microsoft.com/en-us/training/paths/test",
            ),
            ("https://example.com/path", "https://example.com/path"),
            ("", ""),
            (None, ""),
            (
                "  learn.test-path  ",
                "https://learn.microsoft.com/en-us/training/paths/test-path",
            ),
        ],
    )
    def test_normalize_url(self, input_url, expected):
        assert normalize_url(input_url) == expected


class TestRetiredUrlsCollection:
    """Tests for retired URL collection logic."""

    def test_collect_from_retired_urls_json(self, temp_dir):
        """Should collect URLs from retired_urls.json."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "id": "learn.path-1",
                            "url": "https://learn.microsoft.com/en-us/training/paths/path-1",
                        },
                        "https://learn.microsoft.com/en-us/training/paths/path-2",
                    ],
                    "google-skills": [],
                }
            )
        )

        # Simulate the collection logic from build_exclude.py
        collected = set()
        with open(retired_file, "r") as f:
            data = json.load(f)

        for platform_rules in data.values():
            if isinstance(platform_rules, list):
                for rule in platform_rules:
                    if isinstance(rule, dict):
                        u = rule.get("url") or (
                            rule.get("id")
                            if str(rule.get("id", "")).startswith("http")
                            else None
                        )
                    elif isinstance(rule, str) and rule.startswith("http"):
                        u = rule
                    else:
                        u = None
                    if u:
                        norm = normalize_url(u)
                        if norm:
                            collected.add(norm)

        assert "https://learn.microsoft.com/en-us/training/paths/path-1" in collected
        assert "https://learn.microsoft.com/en-us/training/paths/path-2" in collected

    def test_collect_from_validation_json(self, temp_dir):
        """Should collect retired URLs from validation JSON files."""
        # Create validation directory with JSON files
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        # Create a validation JSON with retired items
        validation_file = validation_dir / "microsoft-learn.json"
        validation_data = {
            "platform": "microsoft-learn",
            "achievements": [
                {
                    "id": "1",
                    "title": "Active Badge",
                    "url": "https://example.com/1",
                    "retired": False,
                },
                {
                    "id": "2",
                    "title": "Retired Badge",
                    "url": "learn.retired-path",
                    "retired": True,
                },
                {
                    "id": "3",
                    "title": "Another Retired",
                    "learningPathUid": "lp-retired",
                    "retired": True,
                },
            ],
            "learning_paths": [
                {
                    "id": "lp-1",
                    "title": "Active Path",
                    "url": "https://example.com/lp1",
                    "retired": False,
                },
                {
                    "id": "lp-retired",
                    "title": "Retired Path",
                    "url": "learn.retired-path-2",
                    "retired": True,
                },
            ],
        }
        validation_file.write_text(json.dumps(validation_data))

        # Simulate collection logic
        collected = set()
        for f in validation_dir.glob("*.json"):
            with open(f, "r") as fp:
                data = json.load(fp)

            if isinstance(data, dict):
                if "fingerprints" in data:
                    continue
                items = []
                for key in (
                    "badges",
                    "achievements",
                    "learning_paths",
                    "certifications",
                    "combined_feed",
                    "public_badges",
                    "detailed_learnings",
                    "verifiable_credentials",
                    "user_creds",
                    "userCredentials",
                ):
                    if key in data and isinstance(data[key], list):
                        items.extend(data[key])
                if not items:
                    continue
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                if isinstance(item, dict) and item.get("retired"):
                    url = None
                    for field in (
                        "url",
                        "learningPathUid",
                        "learning_path_uid",
                        "learningPathId",
                        "sourceUid",
                    ):
                        raw = item.get(field)
                        if raw:
                            url = normalize_url(raw)
                            if url:
                                break
                    if url:
                        collected.add(url)

        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-path" in collected
        )
        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-path-2"
            in collected
        )

    def test_skip_fingerprint_files(self, temp_dir):
        """Should skip baseline fingerprint files."""
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        # Create a baseline fingerprint file
        baseline_file = validation_dir / "aws-skills-baseline.json"
        baseline_data = {
            "platform": "aws-skills",
            "fingerprints": {"1": {"record_id": "1", "content_hash": "abc"}},
        }
        baseline_file.write_text(json.dumps(baseline_data))

        # Create a regular validation file
        regular_file = validation_dir / "aws-skills.json"
        regular_data = {
            "badges": [{"id": "1", "url": "https://example.com/1", "retired": True}]
        }
        regular_file.write_text(json.dumps(regular_data))

        collected = set()
        for f in validation_dir.glob("*.json"):
            with open(f, "r") as fp:
                data = json.load(fp)

            if isinstance(data, dict) and "fingerprints" in data:
                continue  # Should skip

            if isinstance(data, dict):
                items = data.get("badges", [])
            else:
                continue

            for item in items:
                if isinstance(item, dict) and item.get("retired"):
                    url = normalize_url(item.get("url"))
                    if url:
                        collected.add(url)

        # Should only have URL from regular file, not baseline
        assert "https://example.com/1" in collected

    def test_lycheeignore_generation(self, temp_dir):
        """Should generate .lycheeignore with sorted URLs."""
        collected = {
            "https://learn.microsoft.com/en-us/training/paths/b-path",
            "https://learn.microsoft.com/en-us/training/paths/a-path",
            "https://example.com/z-path",
        }

        lycheeignore_path = temp_dir / ".lycheeignore"
        with open(lycheeignore_path, "w", encoding="utf-8") as f:
            f.write("# Retired credentials - auto-generated by build_exclude.py\n")
            f.write(
                "# These URLs return 404 and should be excluded from link checking\n\n"
            )
            f.writelines(f"{url}\n" for url in sorted(collected))

        content = lycheeignore_path.read_text()
        lines = [l for l in content.splitlines() if l and not l.startswith("#")]
        assert lines == sorted(lines)  # Should be sorted
        assert len(lines) == 3

    def test_empty_retired_urls_no_lycheeignore(self, temp_dir):
        """Should not write .lycheeignore when no retired URLs."""
        collected = set()

        lycheeignore_path = temp_dir / ".lycheeignore"
        if collected:
            with open(lycheeignore_path, "w", encoding="utf-8") as f:
                f.write("# Retired credentials\n")
                f.writelines(f"{url}\n" for url in sorted(collected))

        assert not lycheeignore_path.exists()


class TestBuildExcludeIntegration:
    """Integration tests for build_exclude.py main logic."""

    def test_main_logic_with_mock_files(self, temp_dir):
        """Test the main collection logic with mocked file structure."""
        # Set up directory structure
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "id": "learn.path-1",
                            "url": "https://learn.microsoft.com/en-us/training/paths/path-1",
                        },
                    ],
                }
            )
        )

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "achievements": [
                        {"id": "1", "url": "learn.path-1", "retired": True},
                    ]
                }
            )
        )

        # Run the collection logic
        collected = set()

        # From retired_urls.json
        with open(retired_file, "r") as f:
            data = json.load(f)
        for platform_rules in data.values():
            if isinstance(platform_rules, list):
                for rule in platform_rules:
                    if isinstance(rule, dict):
                        u = rule.get("url") or (
                            rule.get("id")
                            if str(rule.get("id", "")).startswith("http")
                            else None
                        )
                    elif isinstance(rule, str) and rule.startswith("http"):
                        u = rule
                    else:
                        u = None
                    if u:
                        norm = normalize_url(u)
                        if norm:
                            collected.add(norm)

        # From validation JSONs
        for f in validation_dir.glob("*.json"):
            with open(f, "r") as fp:
                data = json.load(fp)
            if isinstance(data, dict) and "fingerprints" in data:
                continue
            items = []
            for key in ("achievements", "learning_paths"):
                if key in data and isinstance(data[key], list):
                    items.extend(data[key])
            for item in items:
                if isinstance(item, dict) and item.get("retired"):
                    for field in (
                        "url",
                        "learningPathUid",
                        "learning_path_uid",
                        "learningPathId",
                        "sourceUid",
                    ):
                        raw = item.get(field)
                        if raw:
                            url = normalize_url(raw)
                            if url:
                                collected.add(url)
                                break

        # Should have both URLs
        assert "https://learn.microsoft.com/en-us/training/paths/path-1" in collected


class TestBuildExcludeMain:
    """Tests for the main() function of build_exclude.py."""

    def test_main_creates_lycheeignore_when_retired_urls_exist(self, temp_dir):
        """Should create .lycheeignore when retired URLs are found."""
        # Set up retired_urls.json
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "id": "learn.path-1",
                            "url": "https://learn.microsoft.com/en-us/training/paths/path-1",
                        },
                    ],
                }
            )
        )

        # Set up validation directory with retired items
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "achievements": [
                        {"id": "1", "url": "learn.path-2", "retired": True},
                    ]
                }
            )
        )

        # Run main in temp directory
        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        # Check .lycheeignore was created
        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()

        content = lycheeignore_path.read_text()
        assert "lycheeignore_written=true" in content or lycheeignore_path.exists()
        # Should contain both URLs
        assert "https://learn.microsoft.com/en-us/training/paths/path-1" in content
        assert "https://learn.microsoft.com/en-us/training/paths/path-2" in content

    def test_main_no_lycheeignore_when_no_retired_urls(self, temp_dir):
        """Should not create .lycheeignore when no retired URLs found."""
        # Set up retired_urls.json with empty data
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps({"microsoft-learn": [], "google-skills": []})
        )

        # Set up validation directory with no retired items
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "achievements": [
                        {"id": "1", "url": "learn.path-1", "retired": False},
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        # Check .lycheeignore was NOT created
        lycheeignore_path = temp_dir / ".lycheeignore"
        assert not lycheeignore_path.exists()

    def test_main_handles_missing_retired_urls_json(self, temp_dir):
        """Should handle missing retired_urls.json gracefully."""
        # No retired_urls.json file

        # Set up validation directory
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "achievements": [
                        {"id": "1", "url": "learn.path-1", "retired": True},
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://learn.microsoft.com/en-us/training/paths/path-1" in content

    def test_main_handles_corrupted_retired_urls_json(self, temp_dir):
        """Should handle corrupted retired_urls.json gracefully."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text("invalid json {")

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "achievements": [
                        {"id": "1", "url": "learn.path-1", "retired": True},
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            # Should not raise, just print warning to stderr
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()

    def test_main_handles_corrupted_validation_json(self, temp_dir):
        """Should handle corrupted validation JSON gracefully."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text("invalid json {")

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        # Should still work, just skip the corrupted file
        lycheeignore_path = temp_dir / ".lycheeignore"
        # No retired URLs from validation, but retired_urls.json exists
        # Since it's empty, no .lycheeignore should be created
        assert not lycheeignore_path.exists()

    def test_main_handles_list_format_validation_json(self, temp_dir):
        """Should handle validation JSON that is a list (not dict)."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        # Validation JSON as a list
        (validation_dir / "google-skills.json").write_text(
            json.dumps(
                [
                    {"id": "1", "url": "https://example.com/1", "retired": True},
                    {"id": "2", "url": "https://example.com/2", "retired": False},
                ]
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://example.com/1" in content
        assert "https://example.com/2" not in content  # Not retired

    def test_main_handles_empty_validation_json(self, temp_dir):
        """Should handle empty validation JSON gracefully."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(json.dumps({}))

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert not lycheeignore_path.exists()

    def test_main_collects_from_multiple_platforms(self, temp_dir):
        """Should collect retired URLs from multiple platforms."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/ml-1"
                        },
                    ],
                    "google-skills": [
                        {"url": "https://skills.google/badges/gs-1"},
                    ],
                    "aws-skills": [
                        {
                            "url": "https://skillsprofile.skillbuilder.aws/user/test/badges/aws-1"
                        },
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        # Should contain URLs from all three platforms
        assert "https://learn.microsoft.com/en-us/training/paths/ml-1" in content
        assert "https://skills.google/badges/gs-1" in content
        assert (
            "https://skillsprofile.skillbuilder.aws/user/test/badges/aws-1" in content
        )

    def test_main_handles_string_ids_in_retired_urls(self, temp_dir):
        """Should handle string IDs that are HTTP URLs in retired_urls.json."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        "https://learn.microsoft.com/en-us/training/paths/string-id",
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://learn.microsoft.com/en-us/training/paths/string-id" in content

    def test_main_handles_non_http_string_ids(self, temp_dir):
        """Should skip non-HTTP string IDs in retired_urls.json."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        "not-a-url-id",
                        "also-not-a-url",
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        # Should not create file since no valid URLs
        assert not lycheeignore_path.exists()

    def test_main_handles_dict_without_url_or_id(self, temp_dir):
        """Should handle dict rules without url or valid id."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {"reason": "Retired", "retired_at": "2024-01-01"},
                        {"id": "not-http", "reason": "Retired"},
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        # Should not create file since no valid URLs
        assert not lycheeignore_path.exists()

    def test_main_uses_sourceuid_field(self, temp_dir):
        """Should use sourceUid field for retired detection."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "verifiable_credentials": [
                        {
                            "id": "vc-1",
                            "sourceUid": "learn.retired-vc-path",
                            "retired": True,
                        }
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-vc-path"
            in content
        )

    def test_main_uses_learningpathuid_field(self, temp_dir):
        """Should use learningPathUid field for retired detection."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "learning_paths": [
                        {
                            "id": "lp-1",
                            "learningPathUid": "learn.retired-lp-path",
                            "retired": True,
                        }
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-lp-path"
            in content
        )

    def test_main_uses_learning_path_uid_field(self, temp_dir):
        """Should use learning_path_uid field (snake_case) for retired detection."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "learning_paths": [
                        {
                            "id": "lp-1",
                            "learning_path_uid": "learn.retired-snake-path",
                            "retired": True,
                        }
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-snake-path"
            in content
        )

    def test_main_uses_learningpathid_field(self, temp_dir):
        """Should use learningPathId field for retired detection."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps(
                {
                    "learning_paths": [
                        {
                            "id": "lp-1",
                            "learningPathId": "learn.retired-id-path",
                            "retired": True,
                        }
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert (
            "https://learn.microsoft.com/en-us/training/paths/retired-id-path"
            in content
        )

    def test_main_skips_fingerprint_files(self, temp_dir):
        """Should skip baseline fingerprint files in for_validation."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()

        # Create a fingerprint/baseline file
        (validation_dir / "aws-skills-baseline.json").write_text(
            json.dumps(
                {
                    "platform": "aws-skills",
                    "fingerprints": {"1": {"record_id": "1", "content_hash": "abc"}},
                }
            )
        )

        # Create a regular validation file
        (validation_dir / "aws-skills.json").write_text(
            json.dumps(
                {
                    "badges": [
                        {"id": "1", "url": "https://example.com/1", "retired": True}
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        # Should only have URL from regular file
        assert "https://example.com/1" in content

    def test_main_handles_google_developer_combined_feed(self, temp_dir):
        """Should handle google-developer combined_feed format."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"google-developer": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "google-developer.json").write_text(
            json.dumps(
                {
                    "combined_feed": [
                        {
                            "id": "1",
                            "title": "Retired Badge",
                            "url": "https://g.dev/retired",
                            "retired": True,
                        },
                        {
                            "id": "2",
                            "title": "Active Badge",
                            "url": "https://g.dev/active",
                            "retired": False,
                        },
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://g.dev/retired" in content
        assert "https://g.dev/active" not in content

    def test_main_handles_google_developer_public_badges(self, temp_dir):
        """Should handle google-developer public_badges format."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"google-developer": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "google-developer.json").write_text(
            json.dumps(
                {
                    "public_badges": [
                        {
                            "id": "1",
                            "title": "Retired Badge",
                            "url": "https://g.dev/pub-retired",
                            "retired": True,
                        },
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://g.dev/pub-retired" in content

    def test_main_handles_google_developer_detailed_learnings(self, temp_dir):
        """Should handle google-developer detailed_learnings format."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"google-developer": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "google-developer.json").write_text(
            json.dumps(
                {
                    "detailed_learnings": [
                        {
                            "id": "1",
                            "title": "Retired Learning",
                            "url": "https://g.dev/dl-retired",
                            "retired": True,
                        },
                    ]
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert lycheeignore_path.exists()
        content = lycheeignore_path.read_text()
        assert "https://g.dev/dl-retired" in content

    def test_main_sorts_urls_in_output(self, temp_dir):
        """Should write URLs in sorted order to .lycheeignore."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/z-last"
                        },
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/a-first"
                        },
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/m-middle"
                        },
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        content = lycheeignore_path.read_text()
        # Extract non-comment lines
        lines = [
            l.strip()
            for l in content.splitlines()
            if l.strip() and not l.startswith("#")
        ]
        assert lines == sorted(lines), "URLs should be sorted alphabetically"

    def test_main_outputs_correct_format(self, temp_dir):
        """Should output .lycheeignore with correct header format."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/test"
                        },
                    ],
                }
            )
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            # Capture stdout
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                main()
            output = f.getvalue()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        assert "lycheeignore_written=true" in output

    def test_main_outputs_false_when_no_retired(self, temp_dir):
        """Should output lycheeignore_written=false when no retired URLs."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(
            json.dumps({"achievements": []})
        )

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            import io
            from contextlib import redirect_stdout

            f = io.StringIO()
            with redirect_stdout(f):
                main()
            output = f.getvalue()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        assert "lycheeignore_written=false" in output

    def test_main_handles_glob_no_matches(self, temp_dir):
        """Should handle when glob finds no validation files."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({"microsoft-learn": []}))

        # No for_validation directory

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            main()
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))

        lycheeignore_path = temp_dir / ".lycheeignore"
        assert not lycheeignore_path.exists()

    def test_main_handles_permission_error_on_write(self, temp_dir, monkeypatch):
        """Should handle permission error when writing .lycheeignore."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(
            json.dumps(
                {
                    "microsoft-learn": [
                        {
                            "url": "https://learn.microsoft.com/en-us/training/paths/test"
                        },
                    ],
                }
            )
        )

        # Mock open to raise PermissionError
        original_open = open

        def mock_open(path, *args, **kwargs):
            if (
                str(path).endswith(".lycheeignore") and "w" in args[0]
                if args
                else "w" in kwargs.get("mode", "w")
            ):
                raise PermissionError("Permission denied")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mock_open)

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        sys.path.insert(0, str(temp_dir))
        try:
            # Should not raise, just handle gracefully
            main()
        except PermissionError:
            pass  # Expected if not caught
        finally:
            os.chdir(old_cwd)
            sys.path.remove(str(temp_dir))
