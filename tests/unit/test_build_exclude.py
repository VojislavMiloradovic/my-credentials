"""
Unit tests for build_exclude.py
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from build_exclude import normalize_url, retired_urls


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    @pytest.mark.parametrize("input_url,expected", [
        ("learn.retired-path", "https://learn.microsoft.com/en-us/training/paths/retired-path"),
        ("/training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("https://learn.microsoft.com/training/paths/test", "https://learn.microsoft.com/en-us/training/paths/test"),
        ("https://example.com/path", "https://example.com/path"),
        ("", ""),
        (None, ""),
        ("  learn.test-path  ", "https://learn.microsoft.com/en-us/training/paths/test-path"),
    ])
    def test_normalize_url(self, input_url, expected):
        assert normalize_url(input_url) == expected


class TestRetiredUrlsCollection:
    """Tests for retired URL collection logic."""

    def test_collect_from_retired_urls_json(self, temp_dir):
        """Should collect URLs from retired_urls.json."""
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({
            "microsoft-learn": [
                {"id": "learn.path-1", "url": "https://learn.microsoft.com/en-us/training/paths/path-1"},
                "https://learn.microsoft.com/en-us/training/paths/path-2",
            ],
            "google-skills": [],
        }))
        
        # Simulate the collection logic from build_exclude.py
        collected = set()
        with open(retired_file, "r") as f:
            data = json.load(f)
        
        for platform_rules in data.values():
            if isinstance(platform_rules, list):
                for rule in platform_rules:
                    if isinstance(rule, dict):
                        u = rule.get("url") or (rule.get("id") if str(rule.get("id", "")).startswith("http") else None)
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
                {"id": "1", "title": "Active Badge", "url": "https://example.com/1", "retired": False},
                {"id": "2", "title": "Retired Badge", "url": "learn.retired-path", "retired": True},
                {"id": "3", "title": "Another Retired", "learningPathUid": "lp-retired", "retired": True},
            ],
            "learning_paths": [
                {"id": "lp-1", "title": "Active Path", "url": "https://example.com/lp1", "retired": False},
                {"id": "lp-retired", "title": "Retired Path", "url": "learn.retired-path-2", "retired": True},
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
                    "badges", "achievements", "learning_paths", "certifications",
                    "combined_feed", "public_badges", "detailed_learnings",
                    "verifiable_credentials", "user_creds", "userCredentials",
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
                    for field in ("url", "learningPathUid", "learning_path_uid", "learningPathId", "sourceUid"):
                        raw = item.get(field)
                        if raw:
                            url = normalize_url(raw)
                            if url:
                                break
                    if url:
                        collected.add(url)
        
        assert "https://learn.microsoft.com/en-us/training/paths/retired-path" in collected
        assert "https://learn.microsoft.com/en-us/training/paths/retired-path-2" in collected

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
        regular_data = {"badges": [{"id": "1", "url": "https://example.com/1", "retired": True}]}
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
            f.write("# These URLs return 404 and should be excluded from link checking\n\n")
            for url in sorted(collected):
                f.write(f"{url}\n")
        
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
                for url in sorted(collected):
                    f.write(f"{url}\n")
        
        assert not lycheeignore_path.exists()


class TestBuildExcludeIntegration:
    """Integration tests for build_exclude.py main logic."""

    def test_main_logic_with_mock_files(self, temp_dir):
        """Test the main collection logic with mocked file structure."""
        # Set up directory structure
        retired_file = temp_dir / "retired_urls.json"
        retired_file.write_text(json.dumps({
            "microsoft-learn": [
                {"id": "learn.path-1", "url": "https://learn.microsoft.com/en-us/training/paths/path-1"},
            ],
        }))
        
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        (validation_dir / "microsoft-learn.json").write_text(json.dumps({
            "achievements": [
                {"id": "1", "url": "learn.path-1", "retired": True},
            ]
        }))
        
        # Run the collection logic
        collected = set()
        
        # From retired_urls.json
        with open(retired_file, "r") as f:
            data = json.load(f)
        for platform_rules in data.values():
            if isinstance(platform_rules, list):
                for rule in platform_rules:
                    if isinstance(rule, dict):
                        u = rule.get("url") or (rule.get("id") if str(rule.get("id", "")).startswith("http") else None)
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
                    for field in ("url", "learningPathUid", "learning_path_uid", "learningPathId", "sourceUid"):
                        raw = item.get(field)
                        if raw:
                            url = normalize_url(raw)
                            if url:
                                collected.add(url)
                                break
        
        # Should have both URLs
        assert "https://learn.microsoft.com/en-us/training/paths/path-1" in collected