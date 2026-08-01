import glob
import os
import re
from datetime import datetime, timezone

ARCHIVE_DIR = "archives"
README_PATH = "README.md"
LLMS_TXT_PATH = "llms.txt"
LLMS_FULL_PATH = "llms-full.txt"

RAW_BASE_ROOT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main"


def get_token_estimate(text_content):
    """Rough token count estimation (~4 chars per token)."""
    return len(text_content) // 4


def extract_readme_metrics(readme_path=README_PATH):
    """Extracts high-level summary metrics directly from README.md comment blocks."""
    # Default fallback values
    metrics = {
        "ms_learn": "35,424 completed units | 4,780 total achievements",
        "google_skills": "338 badges | 198,577 total points",
        "aws": "480 completed courses/activities",
        "credly": "482 verified credentials | 1,838 mapped skills",
        "linkedin": "1,297 verified external certifications",
        "google_dev": "171 milestone badges | 1,446 codelabs & learning activities",
    }

    if not os.path.exists(readme_path):
        return metrics

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Microsoft Learn
    units = re.search(r"Completed Individual Units:\*\*?\s*([\d,]+)", content)
    ms_total = re.search(r"Showing latest \d+ of ([\d,]+) achievements", content)
    if units and ms_total:
        metrics["ms_learn"] = f"{units.group(1)} completed units | {ms_total.group(1)} total achievements"

    # 2. Google Cloud Skills
    gskills_badges = re.search(r"Google Cloud Skills Boost \((\d+ Badges?)\)", content, re.I)
    gskills_points = re.search(r"Total Lifetime Points:\*\*?\s*([\d,]+)", content)
    if gskills_badges and gskills_points:
        metrics["google_skills"] = f"{gskills_badges.group(1)} | {gskills_points.group(1)} total points"

    # 3. AWS Skill Builder
    aws_count = re.search(r"Total Completed Courses/Activities:\*\*?\s*([\d,]+)", content)
    if aws_count:
        metrics["aws"] = f"{aws_count.group(1)} completed courses/activities"

    # 4. Credly
    credly_total = re.search(r"Total Portfolio Credentials:\*\*?\s*([^\n]+)", content)
    credly_skills = re.search(r"Total Verified Skills Mapped:\*\*?\s*([\d,]+)", content)
    if credly_total and credly_skills:
        # Strip trailing parenthetical notes for cleaner display
        total_clean = credly_total.group(1).split("(")[0].strip()
        metrics["credly"] = f"{total_clean} credentials | {credly_skills.group(1)} mapped skills"

    # 5. LinkedIn
    linkedin_count = re.search(r"Total External Certifications Verified\*\*?\s*\|\s*([\d,]+)", content)
    if linkedin_count:
        metrics["linkedin"] = f"{linkedin_count.group(1)} verified external certifications"

    # 6. Google Developer
    dev_badges = re.search(r"Total Milestones & Milestone Badges\*\*?\s*\|\s*([\d,]+)", content)
    dev_activities = re.search(r"Total Codelabs & Learning Activities\*\*?\s*\|\s*([\d,]+)", content)
    if dev_badges and dev_activities:
        metrics["google_dev"] = f"{dev_badges.group(1)} milestone badges | {dev_activities.group(1)} codelabs & activities"

    return metrics


def generate_llms_txt():
    """Generates the standard-compliant llms.txt sitemap for AI agents."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    metrics = extract_readme_metrics()

    lines = []
    lines.append("# Vojislav Miloradovic - Machine-Readable Credentials Archive\n")
    lines.append(f"> **Last Generated:** {now_utc}")
    lines.append("> Curated, structured, and token-optimized record of professional certifications, badges, and learning achievements across Microsoft Learn, AWS, Google Cloud, Credly, LinkedIn, and Google Developer.\n")

    # Executive Summary / Portfolio Metrics
    lines.append("## Portfolio Overview & Total Counts")
    lines.append(f"- **Microsoft Learn**: {metrics['ms_learn']}")
    lines.append(f"- **Google Cloud Skills**: {metrics['google_skills']}")
    lines.append(f"- **AWS Skill Builder**: {metrics['aws']}")
    lines.append(f"- **Credly**: {metrics['credly']}")
    lines.append(f"- **LinkedIn**: {metrics['linkedin']}")
    lines.append(f"- **Google Developer**: {metrics['google_dev']}\n")

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

    # 2. Complete Monoliths
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

    # 3. Latest part-01 chunk for each platform
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

    print(f"✅ Generated {LLMS_TXT_PATH} successfully with extracted portfolio metrics.")


def generate_llms_full_txt():
    """Generates a single concatenated dataset file for large-context models."""
    now_utc_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    full_content = []
    full_content.append("================================================================================")
    full_content.append(" VOJISLAV MILORADOVIC — CONSOLIDATED CREDENTIALS ARCHIVE (llms-full.txt)")
    full_content.append("================================================================巧\n")

    full_content.append(f"> **Last Generated:** {now_utc_full}")

    # Include Root README
    if os.path.exists(README_PATH):
        full_content.append("--- BEGIN FILE: README.md ---")
        with open(README_PATH, "r", encoding="utf-8") as f:
            full_content.append(f.read())
        full_content.append("--- END FILE: README.md ---\n\n")

    # Include Complete / Monolithic Datasets from Archives
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
