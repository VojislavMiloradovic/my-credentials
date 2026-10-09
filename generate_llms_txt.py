"""generate_llms_txt.py
-----------------------
Generates a structured, token-optimized llms.txt index file from the credentials archive.

Scrapes live counts from README.md and archive index files, categorizes achievements
into tech domains, and produces a machine-readable index with platform master indexes.
"""

import glob
import os
import re
from datetime import UTC, datetime

from archiver import count_tokens
from layer_manifest import get_platforms_with_l2_artifact

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
LLMS_PATH = "llms.txt"
RAW_BASE_URL = (
    "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
)

DOMAIN_PATTERNS = [
    (
        "[AI]  AI, Machine Learning & Data",
        re.compile(
            r"\b(ai|genai|llm|copilot|gemini|agent|bedrock|rag|bigquery|machine learning|data science|vision api|deep learning|neural|openai|vertex|tensorflow|pytorch|prompt|langchain|vector|nlp|sql|data|database|analytics|power bi|fabric|synapse|databricks|reporting|pandas|spark|intelligence|predictive|etl|warehouse|insight)\b",
            re.IGNORECASE,
        ),
    ),
    (
        " DevOps, Security & Governance",
        re.compile(
            r"\b(entra|security|ci/cd|cicd|git|github|kubernetes|k8s|docker|container|active directory|byok|encryption|threat|iam|governance|compliance|devops|pipeline|terraform|sentinel|cybersecurity|zero trust|defender|purview|intune|identity|auth|authorization|rbac|policy|bicep|arm|powershell|cli|automation|monitor|log analytics|audit|risk|protection|vault)\b",
            re.IGNORECASE,
        ),
    ),
    (
        " Cloud & Infrastructure",
        re.compile(
            r"\b(azure|aws|gcp|google cloud|vpc|netapp|networking|serverless|cloud run|storage|ec2|s3|infrastructure|virtual machine|load balancer|dns|route 53|cloud architecture|hybrid|virtual network|windows server|linux|vm|subnet|expressroute|firewall|compute|app service|backup|disaster recovery|migration|cluster|hyper-v|edge)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "[Dev]  App Engineering & Software Development",
        re.compile(
            r"\b(android|unity|streamlit|mongodb|python|codelabs|power platform|power apps|power automate|alm|c#|dotnet|\.net|java|javascript|typescript|react|api|rest|graphql|flutter|web dev|node|app engine|frontend|backend|developer|development|code|visual studio|microservices|logic app|functions|sdk|html|css|json|xml)\b",
            re.IGNORECASE,
        ),
    ),
]

FALLBACK_DOMAIN = "[Biz]  Enterprise & Professional Development"


def _get_monolith_configs():
    """Get monolith configs from layer manifest for L2_published artifacts with archive_complete."""
    platform_keys = get_platforms_with_l2_artifact("archive_complete")
    configs = []
    for platform_key in platform_keys:
        platform_name = platform_key.replace("-", " ").title()
        configs.append((f"{platform_name} Complete", f"{platform_key}-complete.md"))
    return sorted(configs)


def _get_slice_configs():
    """Get slice configs from layer manifest for L2_published artifacts with archive_index."""
    platform_keys = get_platforms_with_l2_artifact("archive_index")
    configs = []
    for platform_key in platform_keys:
        platform_name = platform_key.replace("-", " ").title()
        configs.append(
            (
                f"{platform_name} Latest Slice",
                platform_key,
                f"Most recent achievements for {platform_name}.",
            )
        )
    return sorted(configs)


MONOLITH_CONFIGS = _get_monolith_configs()
SLICE_CONFIGS = _get_slice_configs()


def _get_file_stats(filepath: str) -> tuple[float, int]:
    """Calculates exact file size in KB and exact BPE token count using tiktoken."""
    if not os.path.exists(filepath):
        return 0.0, 0
    try:
        size_kb = round(os.path.getsize(filepath) / 1024, 2)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        tokens = count_tokens(content)
        return size_kb, tokens
    except Exception as e:
        print(f" Warning reading stats for {filepath}: {e}")
        return 0.0, 0


def _scrape_index(filename: str, pattern: re.Pattern) -> str:
    """Reads one archive index file and returns the first regex match group, or '[unavailable]'."""
    path = os.path.join(ARCHIVE_DIR, filename)
    if not os.path.exists(path):
        return "[unavailable]"
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    return m.group(1).replace(",", "")
    except Exception:
        return "[unavailable]"
    return "[unavailable]"


def read_portfolio_counts() -> dict:
    """Reads live counts directly from archive index files and README, with explicit logging."""
    print(" Scraping portfolio counts from README.md and archive indexes...")

    _TOTAL = re.compile(r"Total[^:]*:\**\s*([\d,]+)", re.IGNORECASE)

    counts = {
        "ms_learn_units": "[unavailable]",
        "ms_learn_xp": "[unavailable]",
        "ms_learn_badges": "[unavailable]",
        "ms_learn_achievements": "[unavailable]",
        "gcp_badges": "[unavailable]",
        "aws_activities": "[unavailable]",
        "credly_credentials": "[unavailable]",
        "linkedin_certs": "[unavailable]",
        "gdev_badges": "[unavailable]",
        "gdev_activities": "[unavailable]",
    }

    if os.path.exists(README_PATH):
        try:
            with open(README_PATH, "r", encoding="utf-8") as f:
                readme = f.read()
            block_match = re.search(
                r"<!--\s*MS_LEARN_START\s*-->(.+?)<!--\s*MS_LEARN_END\s*-->",
                readme,
                re.DOTALL,
            )
            if block_match:
                block = block_match.group(1)
                for label, key in [
                    (r"Total Experience Points.*?:\**\s*([\d,]+)", "ms_learn_xp"),
                    (r"Completed Individual Units.*?:\**\s*([\d,]+)", "ms_learn_units"),
                    (r"Badges Earned.*?:\**\s*([\d,]+)", "ms_learn_badges"),
                ]:
                    m = re.search(label, block, re.IGNORECASE)
                    if m:
                        counts[key] = m.group(1).replace(",", "")
        except Exception as e:
            print(f" Warning reading {README_PATH}: {e}")
    else:
        print(f" {README_PATH} not found.")

    index_targets = [
        ("ms_learn_achievements", "microsoft-learn-index.md", _TOTAL),
        ("gcp_badges", "google-skills-index.md", _TOTAL),
        ("aws_activities", "aws-skills-index.md", _TOTAL),
        ("credly_credentials", "credly-index.md", _TOTAL),
        ("linkedin_certs", "linkedin-certifications-index.md", _TOTAL),
        (
            "gdev_badges",
            "google-developer-index.md",
            re.compile(r"Total Public Badges.*?:\**\s*([\d,]+)", re.IGNORECASE),
        ),
        (
            "gdev_activities",
            "google-developer-index.md",
            re.compile(r"Total Detailed Activities.*?:\**\s*([\d,]+)", re.IGNORECASE),
        ),
    ]

    for key, filename, pattern in index_targets:
        counts[key] = _scrape_index(filename, pattern)

    resolved = sum(1 for v in counts.values() if v != "[unavailable]")
    total = len(counts)
    unavail_count = total - resolved

    print(
        f" Portfolio Counts Scraped: {resolved}/{total} resolved ({unavail_count} marked [unavailable])"
    )
    for k, v in counts.items():
        if v == "[unavailable]":
            print(f"    {k}: [unavailable]")

    return counts


def extract_dataset_items(lines: list[str]) -> list[str]:
    """Extracts data strings from markdown table data rows and bullet points using separator anchoring."""
    items = []
    cleaned_lines = [line.strip() for line in lines]
    separator_re = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")

    i = 0
    while i < len(cleaned_lines):
        line = cleaned_lines[i]
        if line.startswith("|") and line.endswith("|"):
            if (i + 1) < len(cleaned_lines) and separator_re.match(
                cleaned_lines[i + 1]
            ):
                i += 2  # Skip header row and separator row
                while i < len(cleaned_lines):
                    row_line = cleaned_lines[i]
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    if separator_re.match(row_line):
                        i += 1
                        continue
                    items.append(row_line)
                    i += 1
                continue
            elif separator_re.match(line):
                i += 1
                continue
        elif line.startswith(("- ", "* ")):
            items.append(line)
        i += 1

    return items


def calculate_domain_breakdown():
    """Scans all complete archive files and categorizes credentials into 5 domains."""
    print(
        "[Files]  Scanning monolithic archive files (*-complete.md) for domain breakdown..."
    )

    domain_counts = {name: 0 for name, _ in DOMAIN_PATTERNS}
    domain_counts[FALLBACK_DOMAIN] = 0
    total_parsed = 0
    total_skipped = 0

    monolith_files = glob.glob(os.path.join(ARCHIVE_DIR, "*-complete.md"))

    if not monolith_files:
        print(f" No monolithic complete archive files found in {ARCHIVE_DIR}/")
        return domain_counts, 0

    for filepath in sorted(monolith_files):
        filename = os.path.basename(filepath)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f" Error reading {filepath}: {e}")
            continue

        items = extract_dataset_items(lines)
        file_parsed = len(items)
        file_skipped = len(lines) - file_parsed

        for line_str in items:
            matched = False
            for domain_name, pattern in DOMAIN_PATTERNS:
                if pattern.search(line_str):
                    domain_counts[domain_name] += 1
                    matched = True
                    break

            if not matched:
                domain_counts[FALLBACK_DOMAIN] += 1

        total_parsed += file_parsed
        total_skipped += file_skipped
        print(
            f"  - {filename}: {file_parsed} items categorized ({file_skipped} header/empty lines skipped)"
        )

    print(
        f" Categorized {total_parsed} total achievements across {len(monolith_files)} dataset files:"
    )
    for domain, count in domain_counts.items():
        percentage = (count / total_parsed * 100) if total_parsed > 0 else 0
        print(f"    {domain}: {count:,} ({percentage:.1f}%)")

    return domain_counts, total_parsed


def generate_llms_txt():
    """Generates a token-optimized, structured llms.txt index file."""
    print(" Starting llms.txt index generation...")
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    pc = read_portfolio_counts()
    domain_counts, total_parsed = calculate_domain_breakdown()

    def _fmt(val: str) -> str:
        if val == "[unavailable]":
            return val
        try:
            return f"{int(val):,}"
        except ValueError:
            return val

    content = f"""# Vojislav Miloradovic - Machine-Readable Credentials Archive

> **Last Generated:** {timestamp}
> Curated, structured, and token-optimized record of professional certifications, badges, and learning achievements across Microsoft Learn, AWS, Google Cloud, Credly, LinkedIn, and Google Developer.

## Portfolio Overview & Total Counts
- **Microsoft Learn**: {_fmt(pc["ms_learn_units"])} completed units | {_fmt(pc["ms_learn_achievements"])} total achievements | {_fmt(pc["ms_learn_xp"])} XP
- **Google Cloud Skills**: {_fmt(pc["gcp_badges"])} badges
- **AWS Skill Builder**: {_fmt(pc["aws_activities"])} completed courses/activities
- **Credly**: {_fmt(pc["credly_credentials"])} credentials
- **LinkedIn**: {_fmt(pc["linkedin_certs"])} certifications & learning courses
- **Google Developer**: {_fmt(pc["gdev_badges"])} milestone badges | {_fmt(pc["gdev_activities"])} codelabs & activities

## Domain Focus & Skill Taxonomy
Dynamic classification of ~{total_parsed:,} parsed portfolio achievements across 5 primary tech domains:

"""
    for domain, count in domain_counts.items():
        percentage = (count / total_parsed * 100) if total_parsed > 0 else 0
        content += f"- **{domain}**: {count:,} achievements ({percentage:.1f}%)\n"

    content += """
## Platform Master Indexes
Use these index files to navigate chunked historical records without exceeding context limits.

"""
    for title, filename, description in SLICE_CONFIGS:
        raw_url = f"{RAW_BASE_URL}/{filename}-index.md"
        content += f"- [{title}](./archives/{filename}-index.md): {description} Raw: {raw_url}\n"

    content += """
## Complete Platform Archives (Monolithic)
For tools with large context windows, complete datasets are available:

"""
    for title, filename in MONOLITH_CONFIGS:
        size_kb, tokens = _get_file_stats(os.path.join(ARCHIVE_DIR, filename))
        raw_url = f"{RAW_BASE_URL}/{filename}"
        content += f"- [{title}](./archives/{filename}) ({size_kb:.2f} KB, {tokens:,} tokens) Raw: {raw_url}\n"

    content += f"""
## JSON-LD Structured Data
Full Schema.org linked data available at [credentials.jsonld](../credentials.jsonld) (`{os.path.getsize("credentials.jsonld") / 1024:.2f} KB`)

---
*Generated automatically from live archive data. See [GitHub Actions](https://github.com/VojislavMiloradovic/my-credentials/actions) for build logs.*
"""
    with open(LLMS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    file_size_kb = os.path.getsize(LLMS_PATH) / 1024
    print(f"Successfully written {LLMS_PATH} ({file_size_kb:.2f} KB).")


if __name__ == "__main__":
    generate_llms_txt()
