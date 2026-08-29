"""
Custom link checker wrapper for GitHub Actions.
Runs lychee with JSON output and generates a detailed summary
with status table and redirect chains for easy debugging.
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

    summary_parts = ["## Link Checker Summary\n"]

    # Status table (matching the requested format)
    total = data.get("total", 0)
    ok = data.get("ok", 0)
    errors = data.get("errors", 0)
    excluded = data.get("excluded", 0)
    timeouts = data.get("timeouts", 0)
    redirected = data.get("redirected", 0)
    unknown = data.get("unknown", 0)
    unsupported = data.get("unsupported", 0)

    summary_parts.append("| Status | Count |\n")
    summary_parts.append("| --- | --- |\n")
    summary_parts.append(f"| 🔍 Total | {total} |\n")
    summary_parts.append(f"| 🔗 Unique | {data.get('unique', 0)} |\n")
    summary_parts.append(f"| ✅ Successful | {ok} |\n")
    summary_parts.append(f"| ⏳ Timeouts | {timeouts} |\n")
    summary_parts.append(f"| 🔀 Redirected | {redirected} |\n")
    summary_parts.append(f"| 👻 Excluded | {excluded} |\n")
    summary_parts.append(f"| ❓ Unknown | {unknown} |\n")
    summary_parts.append(f"| 🚫 Errors | {errors} |\n")
    summary_parts.append(f"| ⛔ Unsupported | {unsupported} |\n")
    summary_parts.append("\n")

    # Redirects per input - detailed redirect chains
    redirected_links = data.get("redirected_links", [])
    if redirected_links:
        summary_parts.append("## Redirects per input\n")
        summary_parts.append("| Input URL | Redirect Chain |\n")
        summary_parts.append("| --- | --- |\n")

        # Group by input URL to show full chain
        redirect_chains = {}
        for link in redirected_links:
            url = link.get("url", "N/A")
            redirect_url = link.get("redirect_url", "")
            status = link.get("status", "")

            if url not in redirect_chains:
                redirect_chains[url] = []
            if redirect_url:
                redirect_chains[url].append(f"[{status}] {redirect_url}")

        for input_url, chain in sorted(redirect_chains.items()):
            # Escape pipes for markdown table
            escaped_url = input_url.replace("|", "\\|")
            chain_str = " → ".join(chain).replace("|", "\\|")
            summary_parts.append(f"| {escaped_url} | {chain_str} |\n")
        summary_parts.append("\n")

    # Failed links details
    failed_links = data.get("failed", [])
    if failed_links:
        summary_parts.append(f"## Failed Links ({len(failed_links)})\n")
        summary_parts.append("| URL | Status | Error |\n")
        summary_parts.append("| --- | --- | --- |\n")

        # Limit to first 100 failed links to keep summary manageable
        for link in failed_links[:100]:
            url = link.get("url", "N/A")
            status = str(link.get("status", "N/A"))
            error = link.get("error", "Unknown error")[:300]
            url = url.replace("|", "\\|")
            error = error.replace("|", "\\|")
            summary_parts.append(f"| {url} | {status} | {error} |\n")

        if len(failed_links) > 100:
            summary_parts.append(
                f"\n*... and {len(failed_links) - 100} more failed links*\n"
            )
        summary_parts.append("\n")

    # Excluded links summary
    excluded_links = data.get("excluded", [])
    if excluded_links:
        patterns = {}
        for link in excluded_links:
            pattern = link.get("pattern", "unknown")
            patterns[pattern] = patterns.get(pattern, 0) + 1

        summary_parts.append(f"## Excluded Patterns ({len(excluded_links)} links)\n")
        for pattern, count in sorted(patterns.items(), key=lambda x: -x[1]):
            summary_parts.append(f"- `{pattern}`: {count} links\n")
        summary_parts.append("\n")

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
