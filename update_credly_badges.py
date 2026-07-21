import os
import sys
import time
import re
import requests

USERNAME = "vojislavmiloradovic"
USER_ID = "752aee40-7358-4ade-9a49-81e8b6f49225"
README_PATH = "README.md"

ARCHIVE_DIR = "archives"
if os.path.isdir("Archives"):
    ARCHIVE_DIR = "Archives"
    
ARCHIVE_PATH = os.path.join(ARCHIVE_DIR, "credly-badges.md")

MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"

def normalize_iso_date(raw_date):
    """Parses Credly API dates into strict ISO format (YYYY-MM-DD or YYYY-MM)."""
    if not raw_date or raw_date == "N/A":
        return "N/A"
    clean = str(raw_date).split("T")[0].strip()
    match = re.search(r'^\d{4}-\d{2}(-\d{2})?', clean)
    if match:
        return match.group(0)
    return clean

def fetch_paginated_data(url_template, headers, page_size=48):
    all_items = []
    page = 1
    total_pages = 1
    
    while page <= total_pages:
        url = url_template.format(page=page, page_size=page_size)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception:
            break

        page_items = data.get("data", [])
        if not page_items:
            break

        all_items.extend(page_items)
        metadata = data.get("metadata", {})
        if "total_pages" in metadata:
            total_pages = metadata["total_pages"]
        elif len(page_items) < page_size:
            total_pages = page
        else:
            total_pages = max(total_pages, page + 1)
        
        page += 1
        time.sleep(0.5)
        
    return all_items

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    native_url_template = "https://www.credly.com/users/" + USERNAME + "/badges.json?page={page}"
    native_raw = fetch_paginated_data(native_url_template, headers)

    external_url_template = "https://www.credly.com/api/v1/users/" + USER_ID + "/external_badges/open_badges/public?page={page}&page_size={page_size}"
    external_raw = fetch_paginated_data(external_url_template, headers)

    badges = []
    all_skills_set = set()

    for item in native_raw:
        badge_id = item.get("id")
        issued_at = normalize_iso_date(item.get("issued_at_date") or item.get("issued_at", "N/A"))
        
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

    for item in external_raw:
        ext = item.get("external_badge", {})
        name = ext.get("badge_name") or item.get("name") or "Unknown Certification"
        issuer_name = ext.get("issuer_name") or item.get("issuer") or "Third-Party Issuer"
        issued_at = normalize_iso_date(ext.get("issued_at_date") or item.get("issued_at_date") or "N/A")

        verify_url = ext.get("badge_url") or item.get("verification_url") or f"https://www.credly.com/users/{USERNAME}"

        raw_skills = item.get("skills", [])
        badge_skills = []
        if isinstance(raw_skills, list):
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

    badges.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    total_badges = len(badges)
    unique_skills = sorted(list(all_skills_set))
    total_skills = len(unique_skills)

    native_count = sum(1 for b in badges if b["type"] == "Credly Verified")
    external_count = sum(1 for b in badges if b["type"] == "External/Imported")

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
    
    archive_md = []
    archive_md.append("# Complete Credly Badges & Mapped Skills Archive\n")
    archive_md.append(f"This document represents a unified, verifiable list of all {total_badges} digital credentials ({native_count} native, {external_count} external) and {total_skills} mapped professional skills parsed from my [public Credly profile](https://www.credly.com/users/{USERNAME}).\n\n")
    
    archive_md.append("## Mapped Professional Skills\n")
    archive_md.append("These skill keywords are programmatically extracted from metadata verified by issuers.\n\n")
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

if __name__ == "__main__":
    main()
