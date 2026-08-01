import glob
import os
import re
from datetime import datetime

ARCHIVE_DIR = "archives"
LLMS_PATH = "llms.txt"

# Defined technical domain patterns (checked in sequential order)
DOMAIN_PATTERNS = [
    (
        "🤖 AI, Machine Learning & Data",
        re.compile(
            r"\b(ai|genai|llm|copilot|gemini|agent|bedrock|rag|bigquery|machine learning|data science|vision api|deep learning|neural|openai|vertex|tensorflow|pytorch|prompt|langchain|vector|nlp|sql|data analysis)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "🛡️ DevOps, Security & Governance",
        re.compile(
            r"\b(entra|security|ci/cd|cicd|git|github|kubernetes|k8s|docker|container|active directory|byok|encryption|threat|iam|governance|compliance|devops|pipeline|terraform|sentinel|cybersecurity|zero trust)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "☁️ Cloud & Infrastructure",
        re.compile(
            r"\b(azure|aws|gcp|google cloud|vpc|netapp|networking|serverless|cloud run|storage|ec2|s3|infrastructure|virtual machine|load balancer|dns|route 53|cloud architecture|hybrid|virtual network)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "💻 App Engineering & Software Development",
        re.compile(
            r"\b(android|unity|streamlit|mongodb|python|codelabs|power platform|alm|c#|java|javascript|typescript|react|api|rest|graphql|flutter|web dev|node|app engine|frontend|backend)\b",
            re.IGNORECASE,
        ),
    ),
]

FALLBACK_DOMAIN = "👔 Enterprise & Professional Development"


def calculate_domain_breakdown():
    """Scans all complete archive files and categorizes credentials into 5 domains."""
    domain_counts = {name: 0 for name, _ in DOMAIN_PATTERNS}
    domain_counts[FALLBACK_DOMAIN] = 0
    total_parsed = 0

    monolith_files = glob.glob(os.path.join(ARCHIVE_DIR, "*-complete.md"))

    for filepath in monolith_files:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line_str = line.strip()
            # Parse table rows or bullet points containing titles
            if (line_str.startswith("|") and not any(h in line_str for h in ["---", "Date", "Metric", "Stat", "Achievement Title", "Activity / Course"])) or line_str.startswith(("- ", "* ")):
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
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    domain_counts, total_parsed = calculate_domain_breakdown()

    # Base overview counts (extracted from latest state)
    content = f"""# Vojislav Miloradovic - Machine-Readable Credentials Archive

> **Last Generated:** {timestamp}
> Curated, structured, and token-optimized record of professional certifications, badges, and learning achievements across Microsoft Learn, AWS, Google Cloud, Credly, LinkedIn, and Google Developer.

## Portfolio Overview & Total Counts
- **Microsoft Learn**: 35,424 completed units | 4,780 total achievements
- **Google Cloud Skills**: 338 Badges | 198,577 total points
- **AWS Skill Builder**: 480 completed courses/activities
- **Credly**: 482 credentials | 1838 mapped skills
- **LinkedIn**: 1,297 verified external certifications
- **Google Developer**: 171 milestone badges | 1,446 codelabs & activities

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
