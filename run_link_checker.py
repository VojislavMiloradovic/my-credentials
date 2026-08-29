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


def categorize_results(data: dict[str, Any]) -> dict[str, list]:
    """Categorize lychee results into different categories."""
    results = data.get("results", [])

    categories = {
        "successful": [],
        "redirected": [],
        "excluded": [],
        "errors": [],
        "timeouts": [],
        "unknown": [],
        "unsupported": [],
    }

    for item in results:
        url = item.get("url", "")
        status = item.get("status", 0)
        status_text = item.get("status_text", "")
        is_redirect = item.get("is_redirect", False)
        redirect_url = item.get("redirect_url")
        is_excluded = item.get("is_excluded", False)
        exclude_pattern = item.get("exclude_pattern")
        error = item.get("error")
        file = item.get("file", "unknown")
        line = item.get("line", 0)

        entry = {
            "url": url,
            "status": status,
            "status_text": status_text,
            "redirect_url": redirect_url,
            "error": error,
            "file": file,
            "line": line,
            "exclude_pattern": exclude_pattern,
        }

        if is_excluded:
            categories["excluded"].append(entry)
        elif is_redirect:
            categories["redirected"].append(entry)
        elif error:
            categories["errors"].append(entry)
        elif status == 0 or status_text.lower() == "timeout":
            categories["timeouts"].append(entry)
        elif status >= 400:
            categories["errors"].append(entry)
        elif status >= 300:
            categories["redirected"].append(entry)
        elif status == 200 or status_text.lower() == "ok":
            categories["successful"].append(entry)
        else:
            categories["unknown"].append(entry)

    return categories


def generate_summary(data: dict[str, Any]) -> str:
    """Generate a detailed markdown summary from lychee JSON output."""
    if "error" in data:
        return f"## ❌ Link Checker Error\n\n```\n{data['error']}\n```"

    # Categorize all results
    categories = categorize_results(data)

    total = len(data.get("results", []))
    unique = data.get("unique", total)

    # Count categories
    successful_count = len(categories["successful"])
    redirected_count = len(categories["redirected"])
    excluded_count = len(categories["excluded"])
    errors_count = len(categories["errors"])
    timeouts_count = len(categories["timeouts"])
    unknown_count = len(categories["unknown"])
    unsupported_count = len(categories["unsupported"])

    summary_parts = ["## Link Checker Summary\n"]

    # Status table
    summary_parts.append("| Status | Count |\n")
    summary_parts.append("| --- | --- |\n")
    summary_parts.append(f"| 🔍 Total | {total} |\n")
    summary_parts.append(f"| 🔗 Unique | {unique} |\n")
    summary_parts.append(f"| ✅ Successful | {successful_count} |\n")
    summary_parts.append(f"| ⏳ Timeouts | {timeouts_count} |\n")
    summary_parts.append(f"| 🔀 Redirected | {redirected_count} |\n")
    summary_parts.append(f"| 👻 Excluded | {excluded_count} |\n")
    summary_parts.append(f"| ❓ Unknown | {unknown_count} |\n")
    summary_parts.append(f"| 🚫 Errors | {errors_count} |\n")
    summary_parts.append(f"| ⛔ Unsupported | {unsupported_count} |\n")
    summary_parts.append("\n")

    # REDIRECTS - show full redirect chains with source files
    if categories["redirected"]:
        summary_parts.append(f"## 🔀 Redirected Links ({redirected_count})\n")
        summary_parts.append(
            "*These links returned 3xx redirects. Check if they redirect to auth pages or valid destinations.*\n\n"
        )
        summary_parts.append(
            "| Source File | Line | Input URL | Redirect Target | Status |\n"
        )
        summary_parts.append("| --- | --- | --- | --- | --- |\n")

        for item in categories["redirected"]:
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
    if categories["errors"]:
        summary_parts.append(f"## 🚫 Errors ({errors_count})\n")
        summary_parts.append(
            "*These links failed completely. Check if they are retired, broken, or need authentication.*\n\n"
        )
        summary_parts.append("| Source File | Line | URL | Status | Error |\n")
        summary_parts.append("| --- | --- | --- | --- | --- |\n")

        for item in categories["errors"]:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            status = str(item["status"])
            error = (item["error"] or "Unknown error").replace("|", "\\|")[:300]
            summary_parts.append(f"| {file} | {line} | {url} | {status} | {error} |\n")
        summary_parts.append("\n")

    # TIMEOUTS
    if categories["timeouts"]:
        summary_parts.append(f"## ⏳ Timeouts ({timeouts_count})\n")
        summary_parts.append("| Source File | Line | URL | Status |\n")
        summary_parts.append("| --- | --- | --- | --- |\n")

        for item in categories["timeouts"]:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            status = str(item["status"])
            summary_parts.append(f"| {file} | {line} | {url} | {status} |\n")
        summary_parts.append("\n")

    # EXCLUDED - show by pattern with source files
    if categories["excluded"]:
        summary_parts.append(f"## 👻 Excluded Links ({excluded_count})\n")
        # Group by pattern
        patterns = {}
        for item in categories["excluded"]:
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

    # UNKNOWN
    if categories["unknown"]:
        summary_parts.append(f"## ❓ Unknown ({unknown_count})\n")
        summary_parts.append("| Source File | Line | URL | Status | Status Text |\n")
        summary_parts.append("| --- | --- | --- | --- | --- |\n")
        for item in categories["unknown"]:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            status = str(item["status"])
            status_text = item["status_text"].replace("|", "\\|")
            summary_parts.append(
                f"| {file} | {line} | {url} | {status} | {status_text} |\n"
            )
        summary_parts.append("\n")

    # UNSUPPORTED
    if categories["unsupported"]:
        summary_parts.append(f"## ⛔ Unsupported ({unsupported_count})\n")
        summary_parts.append("| Source File | Line | URL |\n")
        summary_parts.append("| --- | --- | --- |\n")
        for item in categories["unsupported"]:
            file = item["file"].replace("|", "\\|")
            line = str(item["line"])
            url = item["url"].replace("|", "\\|")
            summary_parts.append(f"| {file} | {line} | {url} |\n")
        summary_parts.append("\n")

    # SUCCESSFUL - just count, don't list (too many)
    if categories["successful"]:
        summary_parts.append(f"## ✅ Successful ({successful_count})\n")
        summary_parts.append(
            f"*{successful_count} links passed successfully. Not listed for brevity.*\n\n"
        )

    return "".join(summary_parts)


def truncate_summary(summary: str, max_bytes: int = 1000000) -> str:
    """Truncate summary to fit within GitHub's 1MB step summary limit."""
    summary_bytes = summary.encode("utf-8")
    if len(summary_bytes) <= max_bytes:
        return summary

    # Truncate and add notice
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
    categories = categorize_results(data)
    if categories["errors"] or categories["timeouts"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
