"""
Custom link checker wrapper for GitHub Actions.
Reads lychee JSON output from file and generates a detailed summary
with status table, redirect chains, and error details.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

RESULTS_FILE = "link_check_results/latest.json"


def load_results() -> dict[str, Any]:
    """Load lychee JSON results from file."""
    path = Path(RESULTS_FILE)
    if not path.exists():
        print(f"Error: {RESULTS_FILE} not found", file=sys.stderr)
        return {"error": f"{RESULTS_FILE} not found"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from {RESULTS_FILE}: {e}", file=sys.stderr)
        return {"error": "JSON parse error"}


def extract_detailed_results(data: dict[str, Any]) -> dict[str, list]:
    """
    Extract detailed results from lychee's map structures.
    Lychee 0.15.0+ uses maps keyed by URL instead of arrays.
    """
    results = {
        "failed": [],
        "redirected": [],
        "excluded": [],
        "timeouts": [],
    }

    # fail_map contains failed/errored URLs
    fail_map = data.get("fail_map", {})
    for url, info in fail_map.items():
        if isinstance(info, dict):
            results["failed"].append(
                {
                    "url": url,
                    "status": info.get("status", 0),
                    "status_text": info.get("status_text", ""),
                    "error": info.get("error", "Unknown error"),
                    "file": info.get("file", "unknown"),
                    "line": info.get("line", 0),
                }
            )
        else:
            results["failed"].append(
                {
                    "url": url,
                    "status": 0,
                    "status_text": "",
                    "error": str(info),
                    "file": "unknown",
                    "line": 0,
                }
            )

    # redirects are in suggestion_map
    suggestion_map = data.get("suggestion_map", {})
    for url, info in suggestion_map.items():
        if isinstance(info, dict):
            redirect_url = info.get("suggestion") or info.get("redirect_url")
            if redirect_url:
                results["redirected"].append(
                    {
                        "url": url,
                        "status": info.get("status", 302),
                        "status_text": info.get("status_text", "Redirect"),
                        "redirect_url": redirect_url,
                        "file": info.get("file", "unknown"),
                        "line": info.get("line", 0),
                    }
                )

    # excluded_map contains excluded URLs
    excluded_map = data.get("excluded_map", {})
    for url, info in excluded_map.items():
        if isinstance(info, dict):
            results["excluded"].append(
                {
                    "url": url,
                    "pattern": info.get("pattern", "unknown"),
                    "file": info.get("file", "unknown"),
                    "line": info.get("line", 0),
                }
            )
        else:
            results["excluded"].append(
                {
                    "url": url,
                    "pattern": str(info),
                    "file": "unknown",
                    "line": 0,
                }
            )

    return results


def generate_summary(data: dict[str, Any]) -> str:
    """Generate a detailed markdown summary from lychee JSON output."""
    if "error" in data:
        return f"## ❌ Link Checker Error\n\n```\n{data['error']}\n```"

    # Lychee 0.15.0+ JSON structure:
    total = data.get("total", 0)
    successful = data.get("successful", 0)
    unknown = data.get("unknown", 0)
    unsupported = data.get("unsupported", 0)
    timeouts = data.get("timeouts", 0)
    redirects = data.get("redirects", 0)
    excludes = data.get("excludes", 0)
    errors = data.get("errors", 0)
    unique = data.get("unique", total)

    # Extract detailed results from maps
    detailed = extract_detailed_results(data)
    failed_links = detailed["failed"]
    redirected_links = detailed["redirected"]
    excluded_links = detailed["excluded"]
    timeout_links = detailed["timeouts"]

    summary_parts = ["## Link Checker Summary\n"]

    # Status table
    summary_parts.append("| Status | Count |\n")
    summary_parts.append("| --- | --- |\n")
    summary_parts.append(f"| 🔍 Total | {total} |\n")
    summary_parts.append(f"| 🔗 Unique | {unique} |\n")
    summary_parts.append(f"| ✅ Successful | {successful} |\n")
    summary_parts.append(f"| ⏳ Timeouts | {timeouts} |\n")
    summary_parts.append(f"| 🔀 Redirected | {redirects} |\n")
    summary_parts.append(f"| 👻 Excluded | {excludes} |\n")
    summary_parts.append(f"| ❓ Unknown | {unknown} |\n")
    summary_parts.append(f"| 🚫 Errors | {errors} |\n")
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
            pattern = item["pattern"]
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
    if successful > 0:
        summary_parts.append(f"## ✅ Successful ({successful})\n")
        summary_parts.append(
            f"*{successful} links passed successfully. Not listed for brevity.*\n\n"
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
    print("Loading lychee results...", file=sys.stderr)
    data = load_results()

    # Debug: print raw data structure to stderr
    print(f"Lychee data keys: {list(data.keys())}", file=sys.stderr)

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
    fail_map = data.get("fail_map", {})
    if fail_map and isinstance(data, dict) and "error" not in data:
        sys.exit(1)


if __name__ == "__main__":
    main()
