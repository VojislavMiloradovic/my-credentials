"""
Custom link checker wrapper for GitHub Actions.
Runs lychee with JSON output and generates a concise summary
to avoid the 1MB step summary limit.
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
    """Generate a concise markdown summary from lychee JSON output."""
    if "error" in data:
        return f"## ❌ Link Checker Error\n\n```\n{data['error']}\n```"

    summary_parts = ["## 🔗 Link Check Results\n"]

    # Overall stats
    total = data.get("total", 0)
    ok = data.get("ok", 0)
    errors = data.get("errors", 0)
    excluded = data.get("excluded", 0)

    summary_parts.append(
        f"**Total:** {total} | **✅ OK:** {ok} | **❌ Errors:** {errors} | **⏭️ Excluded:** {excluded}\n"
    )

    # Failed links details
    failed_links = data.get("failed", [])
    if failed_links:
        summary_parts.append(f"### ❌ Failed Links ({len(failed_links)})\n")
        summary_parts.append("| URL | Status | Error |\n")
        summary_parts.append("| --- | --- | --- |\n")

        # Limit to first 50 failed links to keep summary small
        for link in failed_links[:50]:
            url = link.get("url", "N/A")
            status = str(link.get("status", "N/A"))
            error = link.get("error", "Unknown error")[:200]  # Truncate long errors
            # Escape pipes in URL for markdown table
            url = url.replace("|", "\\|")
            error = error.replace("|", "\\|")
            summary_parts.append(f"| {url} | {status} | {error} |\n")

        if len(failed_links) > 50:
            summary_parts.append(
                f"\n*... and {len(failed_links) - 50} more failed links*\n"
            )
    else:
        summary_parts.append("### ✅ All links passed!\n")

    # Excluded links summary
    excluded_links = data.get("excluded", [])
    if excluded_links:
        # Group by pattern
        patterns = {}
        for link in excluded_links:
            pattern = link.get("pattern", "unknown")
            patterns[pattern] = patterns.get(pattern, 0) + 1

        summary_parts.append(f"### ⏭️ Excluded Patterns ({len(excluded_links)} links)\n")
        for pattern, count in sorted(patterns.items(), key=lambda x: -x[1]):
            summary_parts.append(f"- `{pattern}`: {count} links\n")

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
    failed = data.get("failed", [])
    if failed and isinstance(data, dict) and "error" not in data:
        sys.exit(1)


if __name__ == "__main__":
    main()
