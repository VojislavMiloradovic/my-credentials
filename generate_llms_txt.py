import os
import glob
from datetime import datetime, timezone

ARCHIVE_DIR = "archives"
README_PATH = "README.md"
LLMS_TXT_PATH = "llms.txt"
LLMS_FULL_PATH = "llms-full.txt"

RAW_BASE_ROOT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main"

def get_token_estimate(text_content):
    """Rough token count estimation (~4 chars per token)."""
    return len(text_content) // 4

def generate_llms_txt():
    """Generates the standard-compliant llms.txt sitemap for AI agents."""
    
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    lines = []
    lines.append("# Vojislav Miloradovic - Machine-Readable Credentials Archive\n")
    lines.append(f"> **Last Generated:** {now_utc}")
    lines.append("> Curated, structured, and token-optimized record of professional certifications, badges, and learning achievements across Microsoft Learn, AWS, Google Cloud, Credly, LinkedIn, and Google Developer.\n")
    
    lines.append("## Platform Master Indexes")
    lines.append("Use these index files to navigate chunked historical records without exceeding context limits.\n")
    
    # 1. Platform Index Files
    index_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*-index.md")))
    for idx_file in index_files:
        filename = os.path.basename(idx_file)
        platform_name = filename.replace("-index.md", "").replace("-", " ").title()
        raw_url = f"{RAW_BASE_ROOT}/{ARCHIVE_DIR}/{filename}"
        lines.append(f"- [{platform_name} Index](./{ARCHIVE_DIR}/{filename}): Master navigation index for {platform_name} chunked archives. Raw: {raw_url}")
    
    lines.append("\n## Complete Monolithic Datasets")
    lines.append("Recommended for models with large context windows (>100k tokens).\n")
    
    # Track seen filenames to avoid duplicates
    seen_files = set()
    
    all_md_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*.md")))
    monolith_files = [f for f in all_md_files if f.endswith("-complete.md")]
    standalone_files = [f for f in all_md_files if not f.endswith("-complete.md") and not f.endswith("-index.md") and "-part-" not in f]

    for filepath in monolith_files + standalone_files:
        filename = os.path.basename(filepath)
        if filename in seen_files:
            continue
        seen_files.add(filename)
        
        size_kb = round(os.path.getsize(filepath) / 1024, 2)
        with open(filepath, "r", encoding="utf-8") as f:
            tokens = get_token_estimate(f.read())
            
        clean_name = filename.replace(".md", "").replace("-", " ").title()
        raw_url = f"{RAW_BASE_ROOT}/{ARCHIVE_DIR}/{filename}"
        lines.append(f"- [{clean_name}](./{ARCHIVE_DIR}/{filename}): Full dataset (~{size_kb} KB, ~{tokens:,} tokens). Raw: {raw_url}")

    lines.append("\n## Latest Chunked Slices (~10 KB per slice)")
    lines.append("Optimized for lower-capacity context tools or fast targeted queries.\n")

    # 3. Target latest part-01 chunk for each platform
    part_ones = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*-part-01.md")))
    for part in part_ones:
        filename = os.path.basename(part)
        platform_key = filename.split("-20")[0].replace("-", " ").title()
        raw_url = f"{RAW_BASE_ROOT}/{ARCHIVE_DIR}/{filename}"
        lines.append(f"- [{platform_key} Latest Slice](./{ARCHIVE_DIR}/{filename}): Most recent achievements for {platform_key}. Raw: {raw_url}")

    lines.append("\n## Structured Machine-Readable Data")
    lines.append("- [Schema.org JSON-LD Credentials](./credentials.jsonld): Semantic linked data representation of all achievements. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/credentials.jsonld")

    lines.append("\n## Full Consolidated Export")
    lines.append(f"- [llms-full.txt](./{LLMS_FULL_PATH}): Single file combining the repository overview, all complete platform datasets, and linked data. Raw: {RAW_BASE_ROOT}/{LLMS_FULL_PATH}\n")

    content = "\n".join(lines)
    with open(LLMS_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"✅ Generated {LLMS_TXT_PATH} successfully.")

def generate_llms_full_txt():
    """Generates a single concatenated dataset file for large-context models."""

    now_utc_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    full_content = []
    full_content.append("================================================================================")
    full_content.append(" VOJISLAV MILORADOVIC — CONSOLIDATED CREDENTIALS ARCHIVE (llms-full.txt)")
    full_content.append("================================================================================\n")

    full_content.append(f"> **Last Generated:** {now_utc_full}")
    
    # 1. Include Root README
    if os.path.exists(README_PATH):
        full_content.append("--- BEGIN FILE: README.md ---")
        with open(README_PATH, "r", encoding="utf-8") as f:
            full_content.append(f.read())
        full_content.append("--- END FILE: README.md ---\n\n")

    # 2. Include Complete / Monolithic Datasets from Archives
    all_md_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*.md")))
    monolith_files = [f for f in all_md_files if f.endswith("-complete.md")]
    standalone_files = [f for f in all_md_files if not f.endswith("-complete.md") and not f.endswith("-index.md") and "-part-" not in f]
    
    seen_files = set()
    for filepath in monolith_files + standalone_files:
        filename = os.path.basename(filepath)
        if filename in seen_files:
            continue
            
        seen_files.add(filename)
        full_content.append(f"--- BEGIN FILE: {ARCHIVE_DIR}/{filename} ---")
        with open(filepath, "r", encoding="utf-8") as f:
            full_content.append(f.read())
        full_content.append(f"--- END FILE: {ARCHIVE_DIR}/{filename} ---\n\n")

    combined_text = "\n".join(full_content)
    with open(LLMS_FULL_PATH, "w", encoding="utf-8") as f:
        f.write(combined_text)
        
    size_kb = round(len(combined_text.encode("utf-8")) / 1024, 2)
    tokens = get_token_estimate(combined_text)
    print(f"✅ Generated {LLMS_FULL_PATH} (~{size_kb} KB, ~{tokens:,} tokens) successfully.")

if __name__ == "__main__":
    generate_llms_txt()
    generate_llms_full_txt()
