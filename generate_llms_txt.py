import sys
from datetime import datetime, timezone

# Import shared parser engine from generate_jsonld to guarantee 100% count parity
try:
    from generate_jsonld import parse_archive_monoliths
except ImportError:
    print("❌ Error: generate_jsonld.py not found in the working directory.", file=sys.stderr)
    sys.exit(1)

LLMS_TXT_PATH = "llms.txt"

PROFILE_LINKS = [
    ("Microsoft Learn", "https://learn.microsoft.com/en-us/users/vojislavmiloradovic/"),
    ("Google Skills", "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"),
    ("AWS Skill Builder", "https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic"),
    ("Credly", "https://www.credly.com/users/vojislavmiloradovic"),
    ("LinkedIn", "https://www.linkedin.com/in/vojislavmiloradovic"),
    ("Google Developer", "https://g.dev/VojislavMiloradovic"),
]


def generate_llms_txt():
    print("🚀 Running generate_llms_txt.py...")

    # Extract complete credentials list via shared parser
    credentials = parse_archive_monoliths()
    total_count = len(credentials)

    # Group credentials by Issuer / Platform
    by_issuer = {}
    for c in credentials:
        issuer = c.get("recognizedBy", {}).get("name", "Other")
        by_issuer.setdefault(issuer, []).append(c)

    lines = []

    # -------------------------------------------------------------------------
    # Header & Meta
    # -------------------------------------------------------------------------
    lines.append("# Vojislav Miloradović - Verified Credentials & Achievements")
    lines.append(f"> LLM-Optimized Complete Registry | Total Verified Credentials: {total_count:,}")
    lines.append(f"> Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n")

    # Live Profiles
    lines.append("## Official Profile Links")
    for name, url in PROFILE_LINKS:
        lines.append(f"- **{name}**: {url}")
    lines.append("")

    # Platform Breakdown Summary Table
    lines.append("## Summary Breakdown")
    lines.append("| Platform / Issuer | Credential Count |")
    lines.append("|---|---|")
    for issuer_name, items in sorted(by_issuer.items(), key=lambda x: len(x[1]), reverse=True):
        lines.append(f"| {issuer_name} | {len(items):,} |")
    lines.append(f"| **Total** | **{total_count:,}** |")
    lines.append("")

    # -------------------------------------------------------------------------
    # Detailed Catalog Grouped by Platform
    # -------------------------------------------------------------------------
    lines.append("## Detailed Credential Catalog")
    lines.append("")

    for issuer_name, items in sorted(by_issuer.items(), key=lambda x: x[0]):
        lines.append(f"### {issuer_name} ({len(items):,})")
        lines.append("")

        for item in items:
            name = item.get("name", "Untitled")
            date = item.get("dateCreated", "")
            cat = item.get("credentialCategory", "")
            url = item.get("url", "")
            cred_id = item.get("identifier", "")

            meta_parts = []
            if cat and cat not in ["Badge/Certification", "Badge"]:
                meta_parts.append(f"Type: {cat}")
            if date:
                meta_parts.append(f"Date: {date}")
            if cred_id:
                meta_parts.append(f"ID: {cred_id}")

            meta_str = f" *({', '.join(meta_parts)})*" if meta_parts else ""

            if url:
                lines.append(f"- [{name}]({url}){meta_str}")
            else:
                lines.append(f"- {name}{meta_str}")

        lines.append("")

    content = "\n".join(lines)

    # Output llms.txt
    with open(LLMS_TXT_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n✅ Successfully generated {LLMS_TXT_PATH} with {total_count:,} credentials across {len(by_issuer)} platforms.")


if __name__ == "__main__":
    generate_llms_txt()
