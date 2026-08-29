"""
Custom link checker wrapper for GitHub Actions.
Runs lychee with JSON output and generates a detailed summary
with status table, redirect chains, and error details.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_lychee_json(args: list[str]) -> dict[str, Any]:
    """Run lychee with JSON output and parse results."""
    cmd = ["lychee", "--format", "json", "--no-progress"] + args
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300, check=False
    )

    if result.returncode not in (0, 1, 2):  # 0=ok, 1=errors, 2=failed
        print(f"Lychee failed with exit code {result.returncode}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
        return {"error": result.stderr}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON output: {e}", file=sys.stderr)
        print(f"stdout: {result.stdout[:500]}", file=sys.stderr)
        return {"error": "JSON parse error"}


def generate_summary(data: dict[str, Any]) -> str:
    """Generate a detailed markdown summary from lychee JSON output."""
    if "error" in data:
        return f"## ❌ Link Checker Error\n\n```\n{data['error']}\n```"

    # Lychee JSON structure (from lychee 0.15.0):
    # {
    #   "total": 27724,
    #   "ok": 23528,
    #   "errors": 9,
    #   "excluded": 1323,
    #   "timeouts": 0,
    #   "redirected": 139,
    #   "unique": 7405,
    #   "unknown": 0,
    #   "unsupported": 0,
    #   "results": [
    #     {
    #       "url": "https://example.com",
    #       "status": 200,
    #       "status_text": "OK",
    #       "is_redirect": false,
    #       "redirect_url": null,
    #       "is_excluded": false,
    #       "exclude_pattern": null,
    #       "error": null,
    #       "file": "README.md",
    #       "line": 42
    #     },
    #     ...
    #   ]
    # }
    # The failed/redirected/excluded arrays are NOT at root level -
    # they must be derived from the "results" array

    total = data.get("total", 0)
    unique = data.get("unique", 0)
    ok = data.get("ok", 0)
    errors_count = data.get("errors", 0)
    excluded_count = data.get("excluded", 0)
    timeouts = data.get("timeouts", 0)
    redirected_count = data.get("redirected", 0)
    unknown = data.get("unknown", 0)
    unsupported = data.get("unsupported", 0)

    results = data.get("results", [])

    # Categorize results from the results array
    failed_links = []
    redirected_links = []
    excluded_links = []
    timeout_links = []

    for item in results:
        is_excluded = item.get("is_excluded", False)
        is_redirect = item.get("is_redirect", False)
        error = item.get("error")
        status = item.get("status", 0)

        entry = {
            "url": item.get("url", "N/A"),
            "status": status,
            "status_text": item.get("status_text", ""),
            "redirect_url": item.get("redirect_url"),
            "error": error,
            "file": item.get("file", "unknown"),
            "line": item.get("line", 0),
            "exclude_pattern": item.get("exclude_pattern"),
        }

        if is_excluded:
            excluded_links.append(entry)
        elif is_redirect:
            redirected_links.append(entry)
        elif error or status == 0 or status >= 400:
            failed_links.append(entry)
        elif status == 0 or (item.get("status_text", "").lower() == "timeout"):
            timeout_links.append(entry)

    summary_parts = ["## Link Checker Summary\n"]

    # Status table
    summary_parts.append("| Status | Count |\n")
    summary_parts.append("| --- | --- |\n")
    summary_parts.append(f"| 🔍 Total | {total} |\n")
    summary_parts.append(f"| 🔗 Unique | {unique} |\n")
    summary_parts.append(f"| ✅ Successful | {ok} |\n")
    summary_parts.append(f"| ⏳ Timeouts | {timeouts} |\n")
    summary_parts.append(f"| 🔀 Redirected | {redirected_count} |\n")
    summary_parts.append(f"| 👻 Excluded | {excluded_count} |\n")
    summary_parts.append(f"| ❓ Unknown | {unknown} |\n")
    summary_parts.append(f"| 🚫 Errors | {errors_count} |\n")
    summary_parts.append(f"| ⛔ Unsupported | {unsupported} |\n")
    summary_parts.append("\n")

    # REDIRECTS - show full redirect chains with source files
    if redirected_links:
        summary_parts.append(f"## 🔀 Redirected Links ({len(redirected_links)})\n")
        summary_parts.append(
            "*These links returned 3xx redirects. Check if they redirect to auth pages or valid destinations.*\n\n"
        )
        summary_parts.append(
            "| Source File | Line | Input URL | Redirect Target | Status |\n"
        )
        summary_parts.append("| --- | --- | --- | --- | --- |\n")

        for item in redirected_links:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            redirect = (item["redirect_url"] or "N/A").replace("|", "\\|")
            status = str(item["status"])
            summary_parts.append(
                f"| {file} | {line} | {url} | {redirect} | {status} |\n"
            )
        summary_parts.append("\n")

    # ERRORS - show all errors with details and source files
    if failed_links:
        summary_parts.append(f"## 🚫 Errors ({len(failed_links)})\n")
        summary_parts.append(
            "*These links failed completely. Check if they are retired, broken, or need authentication.*\n\n"
        )
        summary_parts.append("| Source File | Line | URL | Status | Error |\n")
        summary_parts.append("| --- | --- | --- | --- | --- |\n")

        for item in failed_links:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            status = str(item["status"])
            error = (item["error"] or "Unknown error").replace("|", "\\|")[:300]
            summary_parts.append(f"| {file} | {line} | {url} | {status} | {error} |\n")
        summary_parts.append("\n")

    # TIMEOUTS
    if timeout_links:
        summary_parts.append(f"## ⏳ Timeouts ({len(timeout_links)})\n")
        summary_parts.append("| Source File | Line | URL | Status | Error |\n")
        summary_parts.append("| --- | --- | --- | --- | --- |\n")
        for item in timeout_links:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            status = str(item["status"])
            error = (item["error"] or "Timeout").replace("|", "\\|")[:300]
            summary_parts.append(f"| {file} | {line} | {url} | {status} | {error} |\n")
        summary_parts.append("\n")

    # EXCLUDED - show by pattern with source files
    if excluded_links:
        summary_parts.append(f"## 👻 Excluded Links ({len(excluded_links)})\n")
        # Group by pattern
        patterns = {}
        for item in excluded_links:
            pattern = item["exclude_pattern"] or "unknown"
            if pattern not in patterns:
                patterns[pattern] = []
            patterns[pattern].append(item)

        for pattern, items in sorted(patterns.items(), key=lambda x: -len(x[1])):
            summary_parts.append(f"### Pattern: `{pattern}` ({len(items)} links)\n")
            summary_parts.append("| Source File | Line | URL |\n")
            summary_parts.append("| --- | --- | --- |\n")
            for item in items:
                file = item["file"].replace("|", "\\|")
                line = str(item["line"])
                url = item["url"].replace("|", "\\|")
                summary_parts.append(f"| {file} | {line} | {url} |\n")
            summary_parts.append("\n")

    # SUCCESSFUL - just count, don't list (too many)
    if ok > 0:
        summary_parts.append(f"## ✅ Successful ({ok})\n")
        summary_parts.append(
            f"*{ok} links passed successfully. Not listed for brevity.*\n\n"
        )

    return "".join(summary_parts)


def truncate_summary(summary: str, max_bytes: int = 1000000) -> str:
    """Truncate summary to fit within GitHub's 1MB step summary limit."""
    summary_bytes = summary.encode("utf-8")
    if len(summary_bytes) <= max_bytes:
        return summary

    truncated = summary_bytes[: max_bytes - 500].decode("utf-8", errors="ignore")
    return (
        truncated
        + "\n\n---\n"
        + "*⚠️ Summary truncated to fit GitHub's 1MB step summary limit.*\n"
    )


def main():
    # Default files to check (same as workflow)
    default_files = [
        "README.md",
        "llms.txt",
        "llms-full.txt",
    ]

    # Add archive files
    archive_dir = Path("archives")
    if archive_dir.exists():
        for pattern in ("*.md",):
            default_files.extend(str(p) for p in archive_dir.glob(pattern))

    # Also check old archive dir if exists
    old_archive_dir = Path("archive")
    if old_archive_dir.exists():
        for pattern in ("*.md",):
            default_files.extend(str(p) for p in old_archive_dir.glob(pattern))

    # Build lychee arguments
    args = [
        "--config",
        "lychee.toml",
        "--exclude",
        "(linkedin\\.com/in/|credly\\.com/users/)",
    ] + default_files

    print("Building .lycheeignore...", file=sys.stderr)
    subprocess.run([sys.executable, "build_exclude.py"], check=False)

    print("Running link checker...", file=sys.stderr)
    data = run_lychee_json(args)

    # Debug: print raw data structure to stderr
    print(f"Lychee data keys: {list(data.keys())}", file=sys.stderr)
    if "results" in data:
        print(f"Results count: {len(data['results'])}", file=sys.stderr)
        if data["results"]:
            print(
                f"First result keys: {list(data['results'][0].keys())}", file=sys.stderr
            )

    print("Generating summary...", file=sys.stderr)
    summary = generate_summary(data)

    print("Truncating if needed...", file=sys.stderr)
    summary = truncate_summary(summary)

    # Write to step summary
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "w", encoding="utf-8") as f:
            f.write(summary)
        print(
            f"Written to step summary ({len(summary.encode('utf-8'))} bytes)",
            file=sys.stderr,
        )
    else:
        # Fallback: print to stdout
        print(summary)

    # Exit with error code if there were failures (but not excluded)
    # Re-categorize to check for errors/timeouts
    results = data.get("results", [])
    has_errors = any(
        item.get("error") or item.get("status", 0) >= 400 or item.get("status", 0) == 0
        for item in results
        if not item.get("is_excluded", False) and not item.get("is_redirect", False)
    )
    if has_errors and isinstance(data, dict) and "error" not in data:
        sys.exit(1)


if __name__ == "__main__":
    main()
