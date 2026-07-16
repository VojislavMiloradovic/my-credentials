import os
import sys
import requests

USERNAME = "vojislavmiloradovic"
README_PATH = "README.md"

# 1. Dynamically check for folder casing so we never fail on Linux runners
ARCHIVE_DIR = "archives"
if os.path.isdir("Archives"):
    ARCHIVE_DIR = "Archives"
    
ARCHIVE_PATH = os.path.join(ARCHIVE_DIR, "credly-badges.md")

MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"

def main():
    url = f"https://www.credly.com/users/{USERNAME}/badges.json"
    print(f"📡 Fetching public Credly profile for '{USERNAME}'...")
    
    # Send browser-like headers to prevent Cloudflare from blocking the GitHub runner
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"❌ Error fetching Credly data: {e}")
        sys.exit(1)

    badges_raw = data.get("data", [])
    if not badges_raw:
        print("❌ No public badges found on your profile.")
        sys.exit(1)

    print(f"✅ Found {len(badges_raw)} badges!")

    badges = []
    all_skills_set = set()

    for item in badges_raw:
        badge_id = item.get("id")
        issued_at = item.get("issued_at_date") or item.get("issued_at", "N/A")
        
        template = item.get("badge_template", {})
        name = template.get("name", "Unknown Badge")
        
        raw_skills = template.get("skills", [])
        badge_skills = []
        for s in raw_skills:
            skill_name = s.get("name") if isinstance(s, dict) else str(s)
            if skill_name:
                badge_skills.append(skill_name)
                all_skills_set.add(skill_name)
        
        issuer = template.get("issuer", {})
        issuer_name = issuer.get("summary") or "Verified Issuer"
        
        verify_url = f"https://www.credly.com/badges/{badge_id}"

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "skills": badge_skills
        })

    total_badges = len(badges)
    unique_skills = sorted(list(all_skills_set))
    total_skills = len(unique_skills)

    # Generate clean text-only README metadata
    readme_md = []
    readme_md.append("### Credly Verified Credentials\n")
    readme_md.append(f"**Public Profile:** [Verify Credly Profile](https://www.credly.com/users/{USERNAME})  \n")
    readme_md.append(f"**Total Verified Badges:** {total_badges}  \n")
    readme_md.append(f"**Total Verified Skills Mapped:** {total_skills}\n\n")
    
    readme_md.append("#### Latest Earned Credentials\n")
    readme_md.append("| Date Earned | Credential Name | Issuer |\n|:---:|---|---|\n")
    for b in badges[:10]:
        readme_md.append(f"| *{b['date']}* | **{b['name']}** | {b['issuer']} |\n")
    
    readme_md.append(f"\n👉 **[View all {total_badges} badges and {total_skills} verified skills in the full archive](./{ARCHIVE_DIR}/credly-badges.md)**\n\n")

    # Update README
    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        if MARKER_START in content and MARKER_END in content:
            before = content.split(MARKER_START)[0]
            after = content.split(MARKER_END)[1]
            new_content = f"{before}{MARKER_START}\n" + "".join(readme_md) + f"{MARKER_END}{after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("✅ Successfully updated README.md with clean text-only Credly metadata!")
        else:
            print("❌ Error: Credly markers not found in README.md.")
    
    # Generate structured archives file
    archive_md = []
    archive_md.append("# Complete Credly Badges & Mapped Skills Archive\n")
    archive_md.append(f"This document represents a verifiable list of all {total_badges} digital credentials and {total_skills} mapped professional skills parsed directly from my [public Credly profile](https://www.credly.com/users/{USERNAME}).\n\n")
    
    archive_md.append("## Mapped Professional Skills\n")
    archive_md.append("These skill keywords are programmatically extracted from metadata verified by issuers. They are grouped alphabetically for simple semantic indexing.\n\n")
    archive_md.append(", ".join([f"`{skill}`" for skill in unique_skills]))
    archive_md.append("\n\n---\n\n")

    archive_md.append("## Verified Badges Archive\n")
    archive_md.append("| Date Earned | Credential Title | Verified Issuer | Verification Link |\n|:---:|---|---|:---:|\n")
    for b in badges:
        clean_name = b['name'].replace("|", "\\|")
        archive_md.append(f"| {b['date']} | **{clean_name}** | {b['issuer']} | [Verify Credential]({b['verify']}) |\n")
    
    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("".join(archive_md))
    print(f"✅ Complete Credly archive written successfully to {ARCHIVE_PATH}!")

if __name__ == "__main__":
    main()
