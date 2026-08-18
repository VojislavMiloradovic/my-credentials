"""
generate_llms_full.py
---------------------
Generates llms-full.txt by consolidating:
1. README.md (full content)
2. All *-complete.md archive files from archives/
3. credentials.jsonld (Schema.org linked data)

This provides a single large context file for LLMs with large context windows.
"""

import os
from datetime import UTC, datetime

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
JSONLD_PATH = "credentials.jsonld"
LLMS_FULL_PATH = "llms-full.txt"

MONOLITH_CONFIGS = [
    ("aws-skills-complete.md", "archives/aws-skills-complete.md"),
    ("google-skills-complete.md", "archives/google-skills-complete.md"),
    ("google-developer-complete.md", "archives/google-developer-complete.md"),
    (
        "linkedin-certifications-complete.md",
        "archives/linkedin-certifications-complete.md",
    ),
    ("credly-complete.md", "archives/credly-complete.md"),
    ("microsoft-learn-complete.md", "archives/microsoft-learn-complete.md"),
]


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
    for filename, filepath in MONOLITH_CONFIGS:
        if os.path.exists(filepath):
            content_parts.append(f"--- BEGIN FILE: {filepath} ---")
            content_parts.append("")
            archive_content = read_file_safe(filepath)
            content_parts.append(archive_content)
            content_parts.append("")
            content_parts.append(f"--- END FILE: {filepath} ---")
            content_parts.append("")
            print(f"  Included: {filepath}")
        else:
            print(f"  Missing: {filepath}")

    # 3. credentials.jsonld reference (not embedded - same data as archives, different format)
    raw_base = (
        "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main"
    )
    content_parts.append("--- BEGIN FILE: credentials.jsonld (Schema.org JSON-LD) ---")
    content_parts.append("")
    content_parts.append(
        f"> **Structured Linked Data:** Available at [{JSONLD_PATH}]({raw_base}/{JSONLD_PATH})"
    )
    content_parts.append(
        "> Contains all credentials as Schema.org EducationalOccupationalCredential objects."
    )
    content_parts.append(
        "> Not embedded here to avoid duplication (same data as markdown archives)."
    )
    content_parts.append("")
    content_parts.append(f"--- END FILE: {JSONLD_PATH} ---")
    content_parts.append("")

    # Write output
    final_content = "\n".join(content_parts)
    with open(LLMS_FULL_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(final_content)

    file_size_kb = os.path.getsize(LLMS_FULL_PATH) / 1024
    print(f"Successfully written {LLMS_FULL_PATH} ({file_size_kb:.2f} KB).")


if __name__ == "__main__":
    generate_llms_full()
