import os
import sys
import time
import requests

USERNAME = "vojislavmiloradovic"
README_PATH = "README.md"

# Dynamically check for folder casing so we never fail on Linux runners
ARCHIVE_DIR = "archives"
if os.path.isdir("Archives"):
    ARCHIVE_DIR = "Archives"
    
ARCHIVE_PATH = os.path.join(ARCHIVE_DIR, "credly-badges.md")

MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"

def fetch_paginated_data(endpoint_name, headers):
    """Utility to fetch all pages of data from a given Credly user endpoint."""
    all_items = []
    page = 1
    total_pages = 1
    
    print(f"📡 Fetching '{endpoint_name}' for '{USERNAME}'...")
    
    while page <= total_pages:
        url = f"https://www.credly.com/users/{USERNAME}/{endpoint_name}?page={page}"
        print(f"   -> Fetching page {page} of {total_pages}...")
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"❌ Error fetching {endpoint_name} page {page}: {e}")
            break

        page_items = data.get("data", [])
        if not page_items:
            break

        all_items.extend(page_items)

        # Update total pages from metadata
        metadata = data.get("metadata", {})
        total_pages = metadata.get("total_pages", total_pages)
        
        page += 1
        time.sleep(0.5)
        
    return all_items

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    # 1. Fetch Native Badges
    native_raw = fetch_paginated_data("badges.json", headers)
    print(f"✅ Found {len(native_raw)} native platform badges.")

    # 2. Fetch External/Other Badges
    external_raw = fetch_paginated_data("external_badges.json", headers)
    print(f"✅ Found {len(external_raw)} external/imported badges.")

    badges = []
    all_skills_set = set()

    # Process Native Badges
    for item in native_raw:
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
            "type": "Credly Verified",
            "skills": badge_skills
        })

    # Process External Badges (Defensively parsed)
    for item in external_raw:
        # Check standard fields, with fallbacks for nested template structures
        name = item.get("title") or item.get("name")
        if not name and "badge_template" in item:
            name = item.get("badge_template", {}).get("name") or item.get("badge_template", {}).get("title")
        name = name or "Unknown Certification"

        issuer_name = item.get("issuer") or item.get("issuer_name")
        if not issuer_name and "badge_template" in item:
            template = item.get("badge_template", {})
            issuer_obj = template.get("issuer", {})
            issuer_name = issuer_obj.get("summary") if isinstance(issuer_obj, dict) else str(issuer_obj)
        issuer_name = issuer_name or "Third-Party Issuer"

        issued_at = item.get("issued_at_date") or item.get("issued_at") or item.get("earned_at") or "N/A"
        
        # Clean up timestamp strings to just dates (YYYY-MM-DD) if possible
        if issued_at and "T" in issued_at:
            issued_at = issued_at.split("T")[0]

        # External certifications usually don't link to a unique credly verification page,
        # so we point to your public profile for manual verification.
        verify_url = f"https://www.credly.com/users/{USERNAME}"

        # Parse skills if available
        raw_skills = item.get("skills", []) or item.get("badge_template", {}).get("skills", [])
        badge_skills = []
        for s in raw_skills:
            skill_name = s.get("name") if isinstance(s, dict) else str(s)
            if skill_name:
                badge_skills.append(skill_name)
                all_skills_set.add(skill_name)

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "type": "External/Imported",
            "skills": badge_skills
        })

    # Sort all unified badges chronologically (newest first)
    badges.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    total_badges = len(badges)
    unique_skills = sorted(list(all_skills_set))
    total_skills = len(unique_skills)

    # Count breakdowns
    native_count = sum(1 for b in badges if b["type"] == "Credly Verified")
    external_count = sum(1 for b in badges if b["type"] == "External/Imported")

    # 1. Update main README.md
    readme_md = []
    readme_md.append("### Credly Verified Credentials\n")
    readme_md.append(f"**Public Profile:** [Verify Credly Profile](https://www.credly.com/users/{USERNAME})  \n")
    readme_md.append(f"**Total Portfolio Credentials:** {total_badges} ({native_count} Credly Verified, {external_count} External/Imported)  \n")
    readme_md.append(f"**Total Verified Skills Mapped:** {total_skills}\n\n")
    
    readme_md.append("#### Latest Earned Credentials\n")
    readme_md.append("| Date Earned | Credential Name | Issuer | Verification Type |\n|:---:|---|---|:---:|\n")
    for b in badges[:10]:
        readme_md.append(f"| *{b['date']}* | **{b['name']}** | {b['issuer']} | `{b['type']}` |\n")
    
    readme_md.append(f"\n👉 **[View all {total_badges} credentials and {total_skills} verified skills in the full archive](./{ARCHIVE_DIR}/credly-badges.md)**\n\n")

    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        if MARKER_START in content and MARKER_END in content:
            before = content.split(MARKER_START)[0]
            after = content.split(MARKER_END)[1]
            new_content = f"{before}{MARKER_START}\n" + "".join(readme_md) + f"{MARKER_END}{after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("✅ Successfully updated README.md with unified Credly metadata!")
        else:
            print("❌ Error: Credly markers not found in README.md.")
    
    # 2. Update archives/credly-badges.md
    archive_md = []
    archive_md.append("# Complete Credly Badges & Mapped Skills Archive\n")
    archive_md.append(f"This document represents a unified, verifiable list of all {total_badges} digital credentials ({native_count} native, {external_count} external) and {total_skills} mapped professional skills parsed from my [public Credly profile](https://www.credly.com/users/{USERNAME}).\n\n")
    
    archive_md.append("## Mapped Professional Skills\n")
    archive_md.append("These skill keywords are programmatically extracted from metadata verified by issuers. They are grouped alphabetically for simple semantic indexing.\n\n")
    archive_md.append(", ".join([f"`{skill}`" for skill in unique_skills]))
    archive_md.append("\n\n---\n\n")

    archive_md.append("## Verified Credentials Archive\n")
    archive_md.append("| Date Earned | Credential Title | Verified Issuer | Type | Verification Link |\n|:---:|---|---|:---:|:---:|\n")
    for b in badges:
        clean_name = b['name'].replace("|", "\\|")
        archive_md.append(f"| {b['date']} | **{clean_name}** | {b['issuer']} | `{b['type']}` | [Verify]({b['verify']}) |\n")
    
    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("".join(archive_md))
    print(f"✅ Complete unified Credly archive written successfully to {ARCHIVE_PATH}!")

if __name__ == "__main__":
    main()
