"""
Unit tests for scripts/sanitize_gdev_mhtml.py and workflow sanitization wiring.
"""

import quopri
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.sanitize_gdev_mhtml import process_file, sanitize_mhtml
from update_google_developer import parse_google_learnings_mhtml


class TestSanitizeMhtmlText:
    """Tests for sanitize_mhtml raw string scrubbing."""

    def test_unfolds_quoted_printable_and_redacts_email(self):
        raw = 'content=3D"alice.sm=\nith@example.com"'
        result = sanitize_mhtml(raw)
        assert "alice" not in result
        assert "example.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_preserves_cid_marker_as_redacted(self):
        raw = '<link rel=3D"stylesheet" href=3D"cid:css-1234@mhtml.blink">'
        result = sanitize_mhtml(raw)
        assert "[CID_REDACTED]@mhtml.blink" in result
        assert "[EMAIL_REDACTED]" not in result

    def test_strips_xsrf_meta_and_og_profile_acct_tags(self):
        raw = (
            '<meta name=3D"og-profile-acct" content=3D"user@example.com">\n'
            '<meta name=3D"xsrf_token" content=3D"Ln9q39vbb-secret-token">\n'
            '<div class=3D"ok">Keep</div>'
        )
        result = sanitize_mhtml(raw)
        assert "Ln9q39vbb-secret-token" not in result
        assert "user@example.com" not in result
        assert "og-profile-acct" not in result
        assert "xsrf_token" not in result
        assert "Keep" in result

    def test_redacts_json_and_attr_xsrf_and_uid_and_authuser(self):
        raw = (
            '"userId": "101955490139738322968", '
            '"_xsrf": "secret-json-xsrf", '
            "https://accounts.google.com/ListAccounts?authuser=3D0&listPages=3D1"
        )
        result = sanitize_mhtml(raw)
        assert "101955490139738322968" not in result
        assert "secret-json-xsrf" not in result
        assert "authuser=3D[REDACTED]" in result


class TestProcessMhtmlFile:
    """Tests for multipart MHTML file sanitization and parser compatibility."""

    def test_process_file_strips_account_widgets_and_preserves_learnings(
        self, temp_dir
    ):
        msg = MIMEMultipart("related", type="text/html")

        learnings_html = """<!DOCTYPE html>
<html>
<head>
  <meta name="og-profile-acct" content="private.user@example.com">
  <meta name="xsrf_token" content="super-secret-xsrf-value">
  <script>window.WIZ_global_data = {"email":"private.user@example.com"};</script>
</head>
<body>
  <a href="https://accounts.google.com/ListAccounts?authuser=0">private.user@example.com</a>
  <ul>
    <li class="badge-event-row">
      <a class="badge-event-title" href="https://developer.android.com/codelabs/test">Test Codelab</a>
      <span class="badge-event-date">15. avgust 2024.</span>
    </li>
  </ul>
</body>
</html>"""
        main_part = MIMEText("", "html", "utf-8")
        main_part.replace_header("Content-Transfer-Encoding", "quoted-printable")
        main_part.set_payload(
            quopri.encodestring(learnings_html.encode("utf-8")).decode("ascii")
        )
        main_part["Content-Location"] = (
            "https://me.developers.google.com/badges/recognitions/learnings"
        )
        msg.attach(main_part)

        widget_part = MIMEText(
            "<div>Account: private.user@example.com</div>", "html", "utf-8"
        )
        widget_part["Content-Location"] = "https://ogs.google.com/u/0/widget/account"
        msg.attach(widget_part)

        cookie_part = MIMEText("<script>rotate()</script>", "html", "utf-8")
        cookie_part["Content-Location"] = (
            "https://accounts.google.com/RotateCookiesPage"
        )
        msg.attach(cookie_part)

        mhtml_path = temp_dir / "Developer.mhtml"
        mhtml_path.write_bytes(msg.as_bytes())

        process_file(mhtml_path)

        sanitized_text = mhtml_path.read_text(encoding="utf-8")
        assert "private.user@example.com" not in sanitized_text
        assert "super-secret-xsrf-value" not in sanitized_text
        assert "RotateCookiesPage" not in sanitized_text
        assert "ogs.google.com" not in sanitized_text

        # Parser must still extract the learning item cleanly
        parsed = parse_google_learnings_mhtml(str(mhtml_path))
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Test Codelab"
        assert parsed[0]["date"] == "2024-08-15"

    def test_process_file_accepts_directory(self, temp_dir):
        f = temp_dir / "sample.mhtml"
        f.write_text("email: test.user@example.com", encoding="utf-8")
        process_file(temp_dir)
        assert "test.user@example.com" not in f.read_text(encoding="utf-8")


class TestWorkflowSanitizationBoundary:
    """Ensure workflows run sanitization in the same job and do not mask Gitleaks."""

    def test_ms_learn_workflow_runs_sanitization_in_reusable_job(self):
        wf_path = (
            Path(__file__).parent.parent.parent
            / ".github"
            / "workflows"
            / "update-learn-profile.yml"
        )
        if not wf_path.exists():
            return
        data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        jobs = data["jobs"]
        assert list(jobs.keys()) == ["update-ms-learn"]
        job_with = jobs["update-ms-learn"]["with"]
        assert "sanitize_ms_export.py" in job_with["pre_script"]
        assert "data/microsoft-learn.json" in job_with["artifact_paths"]

    def test_google_dev_workflow_runs_sanitization_in_reusable_job(self):
        wf_path = (
            Path(__file__).parent.parent.parent
            / ".github"
            / "workflows"
            / "update_google_developer.yml"
        )
        if not wf_path.exists():
            return
        data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        jobs = data["jobs"]
        assert list(jobs.keys()) == ["update-profile"]
        job_with = jobs["update-profile"]["with"]
        assert "sanitize_gdev_mhtml.py" in job_with["pre_script"]
        assert "data/" in job_with["artifact_paths"]

    def test_repo_health_does_not_pre_sanitize_before_gitleaks(self):
        wf_path = (
            Path(__file__).parent.parent.parent
            / ".github"
            / "workflows"
            / "repo_health.yml"
        )
        if not wf_path.exists():
            return
        content = wf_path.read_text(encoding="utf-8")
        assert "sanitize_ms_export.py" not in content
        assert "sanitize_gdev_mhtml.py" not in content
        data = yaml.safe_load(content)
        # Note: PyYAML parses bare `on:` as boolean True
        on_section = data.get("on") or data.get(True)
        paths_ignore = on_section["push"]["paths-ignore"]
        assert "data/microsoft-learn.json" in paths_ignore
        assert "data/*.mhtml" in paths_ignore

    def test_reusable_update_scans_after_sanitization(self):
        wf_path = (
            Path(__file__).parent.parent.parent
            / ".github"
            / "workflows"
            / "reusable-update.yml"
        )
        if not wf_path.exists():
            return
        data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = data["jobs"]["update-credentials"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        pre_idx = step_names.index("Run Pre-Processing / Sanitization Script")
        scan_idx = step_names.index("Post-Sanitization Secret Scan (Gitleaks)")
        exec_idx = step_names.index("Execute Scraper Script")
        assert pre_idx < scan_idx < exec_idx
        assert "gitleaks" in steps[scan_idx]["run"]
        assert "dir ." in steps[scan_idx]["run"]
