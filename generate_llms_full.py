"""
generate_llms_full.py
---------------------
Generates llms-full.txt by consolidating:
1. README.md (full content)
2. All *-complete.md archive files from archives/
3. Structured machine-readable references (credentials.jsonld, credentials.feed.json, credentials.ndjson)

This provides a single large context file for LLMs with large context windows.
"""

import argparse
import os
import sys
import tempfile
from datetime import UTC, datetime

# Layer manifest integration
from layer_manifest import get_platforms_with_l2_artifact

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
JSONLD_PATH = "credentials.jsonld"
FEED_JSON_PATH = "credentials.feed.json"
FEED_NDJSON_PATH = "credentials.ndjson"
LLMS_FULL_PATH = "llms-full.txt"


def _atomic_write_text(filepath: str, content: str) -> None:
    """Atomically write text content via a same-directory temp file and os.replace."""
    parent_dir = os.path.dirname(filepath) or "."
    os.makedirs(parent_dir, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent_dir,
            prefix=f".{os.path.basename(filepath)}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(content)
            tmp_file.flush()
        try:
            os.replace(tmp_path, filepath)
        except OSError:
            if os.name != "nt" or not os.path.exists(filepath):
                raise
            backup_path = f"{filepath}.bak"
            os.replace(filepath, backup_path)
            try:
                os.replace(tmp_path, filepath)
            except OSError:
                if not os.path.exists(filepath) and os.path.exists(backup_path):
                    os.replace(backup_path, filepath)
                raise
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _get_monolith_configs():
    """Get monolith configs from layer manifest for L2_published artifacts with archive_complete."""
    platform_keys = get_platforms_with_l2_artifact("archive_complete")
    configs = []
    for platform_key in platform_keys:
        configs.append(
            (
                f"{platform_key}-complete.md",
                f"archives/{platform_key}-complete.md",
            )
        )
    return sorted(configs)


MONOLITH_CONFIGS = _get_monolith_configs()


def read_file_safe(filepath: str) -> str:
    """Read file content, return empty string if not found."""
    if not os.path.exists(filepath):
        return f"\n\n<!-- {filepath} not found -->\n"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"\n\n<!-- Error reading {filepath}: {e} -->\n"


def generate_llms_full():
    print("Starting llms-full.txt generation...")
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    content_parts = [
        "=" * 72,
        "  VOJISLAV MILORADOVIC - CONSOLIDATED CREDENTIALS ARCHIVE (llms-full.txt)",
        "=" * 72,
        "",
        f"> **Last Generated:** {timestamp}",
        "",
        "--- BEGIN FILE: README.md ---",
        "",
    ]

    # 1. README.md full content
    readme_content = read_file_safe(README_PATH)
    content_parts.append(readme_content)
    content_parts.append("")
    content_parts.append("--- END FILE: README.md ---")
    content_parts.append("")

    # 2. All complete archive files
    for filename, _ in MONOLITH_CONFIGS:
        filepath = os.path.join(ARCHIVE_DIR, filename)
        if os.path.exists(filepath):
            content_parts.append(f"--- BEGIN FILE: archives/{filename} ---")
            content_parts.append("")
            archive_content = read_file_safe(filepath)
            content_parts.append(archive_content)
            content_parts.append("")
            content_parts.append(f"--- END FILE: archives/{filename} ---")
            content_parts.append("")
            print(f"  Included: {filepath}")
        else:
            print(f"  Missing: {filepath}")

    # 3. Structured linked data and compact machine feed references (not embedded to avoid duplication)
    raw_base = (
        "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main"
    )
    jsonld_name = os.path.basename(JSONLD_PATH)
    feed_json_name = os.path.basename(FEED_JSON_PATH)
    feed_ndjson_name = os.path.basename(FEED_NDJSON_PATH)

    content_parts.append(
        "--- BEGIN SECTION: STRUCTURED DATA & COMPACT MACHINE FEEDS ---"
    )
    content_parts.append("")
    content_parts.append(
        "All structured outputs below are generated directly from normalized L1 records (`for_validation/*.json`) "
        "and preserve stable `sourceRecordId`, deterministic `sourceHash`, ISO-8601 dates, retirement metadata, "
        "`evidenceLevel`, `verificationStatus`, `verificationUrlKind`, and TTL-cached `lastVerifiedAt` timestamps. "
        "They are referenced here rather than embedded verbatim to avoid duplicating the markdown archive tables above."
    )
    content_parts.append("")
    content_parts.append(
        f"- **Schema.org JSON-LD (`{jsonld_name}`)**: Available at [{jsonld_name}]({raw_base}/{jsonld_name}). "
        "Full `ProfilePage` / `EducationalOccupationalCredential` graph for Semantic Web and JSON-LD consumers."
    )
    content_parts.append(
        f"- **Compact JSON Machine Feed (`{feed_json_name}`)**: Available at [{feed_json_name}]({raw_base}/{feed_json_name}). "
        "Minified, token-optimized single-file JSON with `countsByPlatform` and lean records (no repeated `@context`/`@type` boilerplate)."
    )
    content_parts.append(
        f"- **Streaming NDJSON Machine Feed (`{feed_ndjson_name}`)**: Available at [{feed_ndjson_name}]({raw_base}/{feed_ndjson_name}). "
        "Newline-delimited JSON with one compact credential record per line for streaming parsers, `jq`, and RAG chunking."
    )
    content_parts.append("")
    content_parts.append("--- END SECTION: STRUCTURED DATA & COMPACT MACHINE FEEDS ---")
    content_parts.append("")

    final_content = "\n".join(content_parts)
    _atomic_write_text(LLMS_FULL_PATH, final_content)

    file_size_kb = os.path.getsize(LLMS_FULL_PATH) / 1024
    print(f"Successfully written {LLMS_FULL_PATH} ({file_size_kb:.2f} KB).")


def main(argv: list[str] | None = None) -> None:
    global \
        README_PATH, \
        ARCHIVE_DIR, \
        JSONLD_PATH, \
        FEED_JSON_PATH, \
        FEED_NDJSON_PATH, \
        LLMS_FULL_PATH
    parser = argparse.ArgumentParser(description="Generate llms-full.txt export.")
    parser.add_argument("--readme", default=None)
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--jsonld", default=None)
    parser.add_argument("--feed-json", default=None)
    parser.add_argument("--feed-ndjson", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args([] if argv is None else argv)

    if args.readme:
        README_PATH = args.readme
    if args.archive_dir:
        ARCHIVE_DIR = args.archive_dir
    if args.jsonld:
        JSONLD_PATH = args.jsonld
    if args.feed_json:
        FEED_JSON_PATH = args.feed_json
    if args.feed_ndjson:
        FEED_NDJSON_PATH = args.feed_ndjson
    if args.output:
        LLMS_FULL_PATH = args.output

    generate_llms_full()


if __name__ == "__main__":
    main(sys.argv[1:])
