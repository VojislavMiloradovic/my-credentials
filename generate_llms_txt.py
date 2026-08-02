import glob
import os
import re
from datetime import datetime, timezone

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
LLMS_PATH = "llms.txt"

# Comprehensive domain regex patterns (checked in sequential order)
DOMAIN_PATTERNS = [
    (
        "🤖 AI, Machine Learning & Data",
        re.compile(
            r"\b(ai|genai|llm|copilot|gemini|agent|bedrock|rag|bigquery|machine learning|data science|vision api|deep learning|neural|openai|vertex|tensorflow|pytorch|prompt|langchain|vector|nlp|sql|data|database|analytics|power bi|fabric|synapse|databricks|reporting|pandas|spark|intelligence|predictive|etl|warehouse|insight)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "🛡️ DevOps, Security & Governance",
        re.compile(
            r"\b(entra|security|ci/cd|cicd|git|github|kubernetes|k8s|docker|container|active directory|byok|encryption|threat|iam|governance|compliance|devops|pipeline|terraform|sentinel|cybersecurity|zero trust|defender|purview|intune|identity|auth|authorization|rbac|policy|bicep|arm|powershell|cli|automation|monitor|log analytics|audit|risk|protection|vault)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "☁️ Cloud & Infrastructure",
        re.compile(
            r"\b(azure|aws|gcp|google cloud|vpc|netapp|networking|serverless|cloud run|storage|ec2|s3|infrastructure|virtual machine|load balancer|dns|route 53|cloud architecture|hybrid|virtual network|windows server|linux|vm|subnet|expressroute|firewall|compute|app service|backup|disaster recovery|migration|cluster|hyper-v|edge)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "💻 App Engineering & Software Development",
        re.compile(
            r"\b(android|unity|streamlit|mongodb|python|codelabs|power platform|power apps|power automate|alm|c#|dotnet|\.net|java|javascript|typescript|react|api|rest|graphql|flutter|web dev|node|app engine|frontend|backend|developer|development|code|visual studio|microservices|logic app|functions|sdk|html|css|json|xml)\b",
            re.IGNORECASE,
        ),
    ),
]

FALLBACK_DOMAIN = "👔 Enterprise & Professional Development"


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
    """Reads live counts directly from the just-updated archive index files and README.

    Fallback strategy: if a file is missing or the expected line is absent, the
    value is set to '[unavailable]' rather than a stale cached number.
    This makes gaps explicitly visible to consumers of llms.txt.
    """
    _TOTAL = re.compile(r"Total[^:]*:\**\s*([\d,]+)", re.IGNORECASE)

    counts = {
        # MS Learn: units and XP come from the README section written by
        # update_ms_learn.py earlier in the same workflow run.
        "ms_learn_units": "[unavailable]",
        "ms_learn_xp": "[unavailable]",
        "ms_learn_badges": "[unavailable]",
        "ms_learn_achievements": "[unavailable]",
        # Other platforms: pulled from their *-index.md files.
        "gcp_badges": "[unavailable]",
        "aws_activities": "[unavailable]",
        "credly_credentials": "[unavailable]",
        "linkedin_certs": "[unavailable]",
        "gdev_badges": "[unavailable]",
        "gdev_activities": "[unavailable]",
    }

    # --- MS Learn: parse README between its markers ---
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
        except Exception:
            pass

    # --- Archive index files ---
    counts["ms_learn_achievements"] = _scrape_index(
        "microsoft-learn-index.md", _TOTAL
    )
    counts["gcp_badges"] = _scrape_index(
        "google-cloud-skills-index.md", _TOTAL
    )
    counts["aws_activities"] = _scrape_index(
        "aws-skills-index.md", _TOTAL
    )
    counts["credly_credentials"] = _scrape_index(
        "credly-badges-index.md", _TOTAL
    )
    counts["linkedin_certs"] = _scrape_index(
        "linkedin-certifications-index.md", _TOTAL
    )
    # Google Developer index has two separate count lines.
    counts["gdev_badges"] = _scrape_index(
        "google-developer-index.md",
        re.compile(r"Total Public Badges.*?:\**\s*([\d,]+)", re.IGNORECASE),
    )
    counts["gdev_activities"] = _scrape_index(
        "google-developer-index.md",
        re.compile(r"Total Detailed Activities.*?:\**\s*([\d,]+)", re.IGNORECASE),
    )

    return counts


def calculate_domain_breakdown():
    """Scans all complete archive files and categorizes credentials into 5 domains."""
    domain_counts = {name: 0 for name, _ in DOMAIN_PATTERNS}
    domain_counts[FALLBACK_DOMAIN] = 0
    total_parsed = 0

    monolith_files = glob.glob(os.path.join(ARCHIVE_DIR, "*-complete.md"))

    for filepath in monolith_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue

        for line in lines:
            line_str = line.strip()
            # Parse table rows or bullet points containing titles
            if (
                line_str.startswith("|")
                and not any(
                    h in line_str
                    for h in [
                        "---",
                        "Date",
                        "Metric",
                        "Stat",
                        "Achievement Title",
                        "Activity / Course",
                    ]
                )
            ) or line_str.startswith(("- ", "* ")):
                matched = False
                for domain_name, pattern in DOMAIN_PATTERNS:
                    if pattern.search(line_str):
                        domain_counts[domain_name] += 1
                        matched = True
                        break

                if not matched:
                    domain_counts[FALLBACK_DOMAIN] += 1

                total_parsed += 1

    return domain_counts, total_parsed


def generate_llms_txt():
    """Generates a token-optimized, structured llms.txt index file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    domain_counts, total_parsed = calculate_domain_breakdown()
    pc = read_portfolio_counts()

    def _fmt(val: str) -> str:
        """Format a raw digit string with thousands separators, or pass '[unavailable]' through."""
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
- **Microsoft Learn**: {_fmt(pc['ms_learn_units'])} completed units | {_fmt(pc['ms_learn_achievements'])} total achievements | {_fmt(pc['ms_learn_xp'])} XP
- **Google Cloud Skills**: {_fmt(pc['gcp_badges'])} badges
- **AWS Skill Builder**: {_fmt(pc['aws_activities'])} completed courses/activities
- **Credly**: {_fmt(pc['credly_credentials'])} credentials
- **LinkedIn**: {_fmt(pc['linkedin_certs'])} verified external certifications
- **Google Developer**: {_fmt(pc['gdev_badges'])} milestone badges | {_fmt(pc['gdev_activities'])} codelabs & activities

## Domain Focus & Skill Taxonomy
Dynamic classification of ~{total_parsed:,} parsed portfolio achievements across 5 primary tech domains:

"""
    for domain, count in domain_counts.items():
        percentage = (count / total_parsed * 100) if total_parsed > 0 else 0
        content += f"- **{domain}**: {count:,} achievements ({percentage:.1f}%)\n"

    content += """
## Platform Master Indexes
Use these index files to navigate chunked historical records without exceeding context limits.

- [Aws Skills Index](./archives/aws-skills-index.md): Master navigation index for Aws Skills chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/aws-skills-index.md
- [Credly Badges Index](./archives/credly-badges-index.md): Master navigation index for Credly Badges chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-badges-index.md
- [Google Cloud Skills Index](./archives/google-cloud-skills-index.md): Master navigation index for Google Cloud Skills chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-cloud-skills-index.md
- [Google Developer Index](./archives/google-developer-index.md): Master navigation index for Google Developer chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-developer-index.md
- [Linkedin Certifications Index](./archives/linkedin-certifications-index.md): Master navigation index for Linkedin Certifications chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/linkedin-certifications-index.md
- [Microsoft Learn Index](./archives/microsoft-learn-index.md): Master navigation index for Microsoft Learn chunked archives. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/microsoft-learn-index.md

## Complete Monolithic Datasets
Recommended for models with large context windows (>100k tokens).

- [Aws Skills Complete](./archives/aws-skills-complete.md): Full dataset (~43.4 KB, ~11,105 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/aws-skills-complete.md
- [Credly Badges Complete](./archives/credly-badges-complete.md): Full dataset (~82.59 KB, ~21,134 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-badges-complete.md
- [Google Cloud Skills Complete](./archives/google-cloud-skills-complete.md): Full dataset (~21.71 KB, ~5,555 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-cloud-skills-complete.md
- [Google Developer Complete](./archives/google-developer-complete.md): Full dataset (~229.7 KB, ~58,780 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-developer-complete.md
- [Linkedin Certifications Complete](./archives/linkedin-certifications-complete.md): Full dataset (~264.98 KB, ~67,819 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/linkedin-certifications-complete.md
- [Microsoft Learn Complete](./archives/microsoft-learn-complete.md): Full dataset (~849.88 KB, ~217,558 tokens). Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/microsoft-learn-complete.md

## Latest Chunked Slices (~10 KB per slice)
Optimized for lower-capacity context tools or fast targeted queries.

- [Aws Skills Latest Slice](./archives/aws-skills-2026-07-part-01.md): Most recent achievements for Aws Skills. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/aws-skills-2026-07-part-01.md
- [Credly Badges Latest Slice](./archives/credly-badges-2026-08-part-01.md): Most recent achievements for Credly Badges. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-badges-2026-08-part-01.md
- [Google Cloud Skills Latest Slice](./archives/google-cloud-skills-2026-08-part-01.md): Most recent achievements for Google Cloud Skills. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-cloud-skills-2026-08-part-01.md
- [Google Developer Activities Latest Slice](./archives/google-developer-activities-2026-08-part-01.md): Most recent achievements for Google Developer Activities. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-developer-activities-2026-08-part-01.md
- [Google Developer Badges Latest Slice](./archives/google-developer-badges-2026-08-part-01.md): Most recent achievements for Google Developer Badges. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/google-developer-badges-2026-08-part-01.md
- [Linkedin Certifications Latest Slice](./archives/linkedin-certifications-2026-07-part-01.md): Most recent achievements for Linkedin Certifications. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/linkedin-certifications-2026-07-part-01.md
- [Microsoft Learn Latest Slice](./archives/microsoft-learn-2026-08-part-01.md): Most recent achievements for Microsoft Learn. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/microsoft-learn-2026-08-part-01.md

## Structured Machine-Readable Data
- [Schema.org JSON-LD Credentials](./credentials.jsonld): Semantic linked data representation of all achievements. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/credentials.jsonld

## Full Consolidated Export
- [llms-full.txt](./llms-full.txt): Single file combining the repository overview, all complete platform datasets, and linked data. Raw: https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/llms-full.txt
"""

    with open(LLMS_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ Generated {LLMS_PATH} with updated domain skill taxonomy.")


if __name__ == "__main__":
    generate_llms_txt()