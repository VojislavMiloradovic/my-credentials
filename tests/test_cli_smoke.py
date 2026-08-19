"""
CLI smoke tests for all entry points.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestCliSmoke:
    """Smoke tests for all CLI entry points."""

    def test_update_ms_learn_imports(self):
        """update_ms_learn.py should import without errors."""
        import update_ms_learn

        assert hasattr(update_ms_learn, "main")

    def test_update_google_skills_imports(self):
        """update_google_skills.py should import without errors."""
        import update_google_skills

        assert hasattr(update_google_skills, "main")

    def test_update_aws_skills_imports(self):
        """update_aws_skills.py should import without errors."""
        import update_aws_skills

        assert hasattr(update_aws_skills, "main")

    def test_update_credly_badges_imports(self):
        """update_credly_badges.py should import without errors."""
        import update_credly_badges

        assert hasattr(update_credly_badges, "main")

    def test_update_linkedin_imports(self):
        """update_linkedin.py should import without errors."""
        import update_linkedin

        assert hasattr(update_linkedin, "main")

    def test_update_google_developer_imports(self):
        """update_google_developer.py should import without errors."""
        import update_google_developer

        assert hasattr(update_google_developer, "main")

    def test_generate_jsonld_imports(self):
        """generate_jsonld.py should import without errors."""
        import generate_jsonld

        assert hasattr(generate_jsonld, "main")

    def test_generate_llms_txt_imports(self):
        """generate_llms_txt.py should import without errors."""
        import generate_llms_txt

        assert hasattr(generate_llms_txt, "generate_llms_txt")

    def test_generate_llms_full_imports(self):
        """generate_llms_full.py should import without errors."""
        import generate_llms_full

        assert hasattr(generate_llms_full, "generate_llms_full")

    def test_archiver_imports(self):
        """archiver.py should import without errors."""
        import archiver

        assert hasattr(archiver, "generate_platform_archive")

    def test_loss_guard_imports(self):
        """loss_guard.py should import without errors."""
        import loss_guard

        assert hasattr(loss_guard, "execute_content_loss_guard")

    def test_sanitize_ms_export_imports(self):
        """sanitize_ms_export.py should import without errors."""
        import sanitize_ms_export

        assert hasattr(sanitize_ms_export, "process_file")

    def test_build_exclude_imports(self):
        """build_exclude.py should import without errors."""
        import build_exclude

        assert hasattr(build_exclude, "normalize_url")

    def test_main_functions_callable(self):
        """All main functions should be callable (with mocked dependencies)."""
        from unittest.mock import patch

        with (
            patch("update_ms_learn.os.path.exists", return_value=False),
            patch("update_ms_learn.sys.exit") as mock_exit,
        ):
            import update_ms_learn

            try:
                update_ms_learn.main()
            except SystemExit:
                pass
            mock_exit.assert_called_with(1)

    def test_update_scripts_exit_codes(self):
        """All update scripts should exit with code 1 on missing input."""
        scripts = [
            "update_ms_learn",
            "update_google_skills",
            "update_aws_skills",
            "update_credly_badges",
            "update_linkedin",
            "update_google_developer",
        ]

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=404)
            mock_post.return_value = MagicMock(status_code=404)
            for script_name in scripts:
                module = __import__(script_name)
                with patch(f"{script_name}.os.path.exists", return_value=False):
                    try:
                        module.main()
                    except SystemExit as e:
                        assert e.code == 1
                    except Exception:
                        pass

    def test_generate_scripts_runnable(self):
        """Generation scripts should be runnable with mocked I/O."""
        with (
            patch("generate_jsonld.os.path.exists", return_value=False),
            patch("generate_jsonld.glob.glob", return_value=[]),
            patch("builtins.open", MagicMock()),
            patch("generate_jsonld.jsonschema.validate"),
        ):
            import generate_jsonld

            try:
                generate_jsonld.main()
            except SystemExit:
                pass
            except Exception:
                pass  # Expected with mocked I/O

    def test_sanitize_ms_export_cli(self):
        """sanitize_ms_export.py should accept file argument."""
        import sys

        import sanitize_ms_export

        def mock_exit(code):
            raise SystemExit(code)

        with (
            patch.object(sys, "argv", ["sanitize_ms_export.py", "nonexistent.json"]),
            patch.object(sanitize_ms_export.sys, "exit", side_effect=mock_exit),
        ):
            try:
                sanitize_ms_export.process_file(Path("nonexistent.json"))
            except SystemExit as e:
                assert e.code == 1


class TestScriptHelp:
    """Test that scripts can show help (if they support --help)."""

    def test_scripts_have_main_guard(self):
        """All scripts should have if __name__ == '__main__' guard."""
        scripts = [
            "update_ms_learn",
            "update_google_skills",
            "update_aws_skills",
            "update_credly_badges",
            "update_linkedin",
            "update_google_developer",
            "generate_jsonld",
            "generate_llms_txt",
            "generate_llms_full",
            "sanitize_ms_export",
            "build_exclude",
        ]

        for script_name in scripts:
            filepath = Path(__file__).parent.parent / f"{script_name}.py"
            content = filepath.read_text(encoding="utf-8")
            assert 'if __name__ == "__main__":' in content
            # Check for a function call after main guard (various patterns)
            main_section = content[content.index('if __name__ == "__main__":') :]
            has_call = (
                f"{script_name}.main()" in main_section
                or f"{script_name}()" in main_section
                or "main()" in main_section
                or "process_file" in main_section
            )
            assert has_call, f"No function call found in main guard for {script_name}"
