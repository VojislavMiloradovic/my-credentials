"""
Tests for configuration file validation (pyproject.toml, ruff.toml, lychee.toml, retired_urls.json).
"""

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestPyProjectToml:
    """Tests for pyproject.toml configuration."""

    def test_pyproject_toml_valid(self):
        """pyproject.toml should be valid TOML."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        assert "build-system" in data
        assert "project" in data
        assert data["project"]["name"] == "my-credentials"
        assert data["project"]["requires-python"] == ">=3.11,<3.12"

    def test_pyproject_toml_has_dependencies(self):
        """Should have required dependencies."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        deps = data["project"]["dependencies"]
        required = ["requests", "beautifulsoup4", "jsonschema", "tiktoken", "pydantic"]
        for req in required:
            assert any(req in dep for dep in deps)

    def test_pyproject_toml_has_test_dependencies(self):
        """Should have test optional dependencies."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        test_deps = data["project"]["optional-dependencies"]["test"]
        required = [
            "pytest",
            "pytest-cov",
            "pytest-mock",
            "pytest-xdist",
            "responses",
            "freezegun",
            "mypy",
        ]
        for req in required:
            assert any(req in dep for dep in test_deps)

    def test_pyproject_toml_has_dev_dependencies(self):
        """Should have dev optional dependencies."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        dev_deps = data["project"]["optional-dependencies"]["dev"]
        assert "ruff" in dev_deps[0]

    def test_pyproject_toml_has_pytest_config(self):
        """Should have pytest configuration."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        assert "tool" in data
        assert "pytest" in data["tool"]
        assert "ini_options" in data["tool"]["pytest"]

    def test_pyproject_toml_has_ruff_config(self):
        """Should have ruff configuration."""
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        assert "tool" in data
        assert "ruff" in data["tool"]
        assert "lint" in data["tool"]["ruff"]


class TestRuffToml:
    """Tests for ruff.toml configuration."""

    def test_ruff_toml_valid(self):
        """ruff.toml should be valid TOML."""
        with open("ruff.toml", "rb") as f:
            data = tomllib.load(f)

        assert "lint" in data

    def test_ruff_toml_has_ignored_rules(self):
        """Should have expected ignored lint rules."""
        with open("ruff.toml", "rb") as f:
            data = tomllib.load(f)

        ignored = data["lint"]["ignore"]
        expected = ["BLE001", "DTZ005", "DTZ007", "DTZ901", "S110", "S112", "TRY002"]
        for rule in expected:
            assert rule in ignored


class TestLycheeToml:
    """Tests for lychee.toml configuration."""

    def test_lychee_toml_valid(self):
        """lychee.toml should be valid TOML."""
        with open("lychee.toml", "rb") as f:
            data = tomllib.load(f)

        assert "verbose" in data
        assert "timeout" in data
        assert "hosts" in data

    def test_lychee_toml_has_host_limits(self):
        """Should have rate limits for sensitive hosts."""
        with open("lychee.toml", "rb") as f:
            data = tomllib.load(f)

        hosts = data["hosts"]
        assert "linkedin.com" in hosts
        assert "credly.com" in hosts
        assert hosts["linkedin.com"]["concurrency"] == 2
        assert hosts["credly.com"]["concurrency"] == 2


class TestRetiredUrlsJson:
    """Tests for retired_urls.json configuration."""

    def test_retired_urls_json_valid(self):
        """retired_urls.json should be valid JSON."""
        with open("retired_urls.json", "r") as f:
            data = json.load(f)

        assert isinstance(data, dict)

    def test_retired_urls_json_has_all_platforms(self):
        """Should have entries for all platforms."""
        with open("retired_urls.json", "r") as f:
            data = json.load(f)

        expected_platforms = [
            "microsoft-learn",
            "google-skills",
            "aws-skills",
            "credly",
            "linkedin-certifications",
            "google-developer",
        ]
        for platform in expected_platforms:
            assert platform in data
            assert isinstance(data[platform], list)

    def test_retired_urls_json_entries_valid(self):
        """Each entry should have required fields."""
        with open("retired_urls.json", "r") as f:
            data = json.load(f)

        for entries in data.values():
            for entry in entries:
                if isinstance(entry, dict):
                    assert "id" in entry
                    # Optional fields
                    if "match_type" in entry:
                        assert entry["match_type"] in ["url", "uid", "id"]
                    if "url" in entry:
                        assert entry["url"].startswith("http")
                    if "reason" in entry:
                        assert isinstance(entry["reason"], str)
                    if "retired_at" in entry:
                        # Should be YYYY-MM-DD format
                        import re

                        assert re.match(r"^\d{4}-\d{2}-\d{2}$", entry["retired_at"])


class TestRequirementsTxt:
    """Tests for requirements.txt."""

    def test_requirements_txt_exists(self):
        """requirements.txt should exist."""
        assert Path("requirements.txt").exists()

    def test_requirements_txt_has_pinned_versions(self):
        """All requirements should be pinned with ==."""
        with open("requirements.txt", "r") as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        for line in lines:
            assert "==" in line, f"Requirement not pinned: {line}"

    def test_requirements_txt_matches_pyproject(self):
        """requirements.txt should match pyproject.toml dependencies."""
        with open("requirements.txt", "r") as f:
            req_lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        req_packages = {l.split("==")[0].lower() for l in req_lines}

        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)

        pyproject_deps = {
            d.split("==")[0].lower() for d in data["project"]["dependencies"]
        }

        # requirements.txt should be a superset (includes transitive deps)
        assert pyproject_deps.issubset(req_packages)


class TestGitIgnore:
    """Tests for .gitignore."""

    def test_gitignore_exists(self):
        """.gitignore should exist."""
        assert Path(".gitignore").exists()

    def test_gitignore_ignores_python_artifacts(self):
        """.gitignore should ignore Python build artifacts."""
        with open(".gitignore", "r") as f:
            content = f.read()

        patterns = [
            "__pycache__/",
            "*.py[codz]",
            ".pytest_cache/",
            ".coverage",
            "htmlcov/",
            ".mypy_cache/",
            ".ruff_cache/",
            "*.egg-info/",
            "dist/",
            "build/",
        ]
        for pattern in patterns:
            assert pattern in content

    def test_gitignore_ignores_venv(self):
        """.gitignore should ignore virtual environments."""
        with open(".gitignore", "r") as f:
            content = f.read()

        assert ".venv/" in content or "venv/" in content

    def test_gitignore_tracks_uv_lock(self):
        """.gitignore should track uv.lock."""
        with open(".gitignore", "r") as f:
            content = f.read()

        # Should NOT ignore uv.lock (has !uv.lock)
        assert "!uv.lock" in content or "uv.lock" not in content.split("!")[0]


class TestPythonVersion:
    """Tests for .python-version."""

    def test_python_version_exists(self):
        """.python-version should exist."""
        assert Path(".python-version").exists()

    def test_python_version_matches_pyproject(self):
        """.python-version should match pyproject.toml requires-python."""
        with open(".python-version", "r") as f:
            version = f.read().strip()

        assert version == "3.11" or version.startswith("3.11")
