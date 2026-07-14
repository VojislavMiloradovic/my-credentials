import os
import json
from datetime import datetime

# We target the already-repaired file directly in your repo
JSON_PATH = "data/microsoft-learn.json"
README_PATH = "README.md"
ALL_ACHIEVEMENTS_PATH = "data/all_achievements.md"

MARKER_START = "<!-- MS_LEARN_START -->"
MARKER_END = "<!-- MS_LEARN_END -->"

def format_num(val):
    """Safely format numbers with commas, handling strings and None gracefully."""
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "0"

def clean_uid(uid):
    """Convert raw UIDs like 'applied-skill.generate-reports' into clean, AI-readable titles."""
    if not uid:
        return ""
    parts = uid.replace("applied-skill.", "").replace("learn.wwl.", "").split("-")
    return " ".join(parts).title()

def main():
    print(f"Opening data file: {JSON_PATH}...")
    if not os.path.exists(JSON_PATH):
        print(f"❌ Error: {JSON_PATH} not found!")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"❌ Error parsing JSON: {e}")
            return

    # Extract sections defensively
    progress = data.get("Progress", {}) or {}
    xp_data = data.get("XP", {}) or {}
    skills = data.get("SkillAssessment", {}) or {}
    creds = data.get("VerifiableCredentials", {}) or {}

    # 1. Gather High-Level Stats
    completed_units = progress.get("completedLearningItems", [])
    learning_paths = progress.get("learningPathPasses", [])
    modules = progress.get("moduleAssessments", [])
    achievements = xp_data.get("achievements", []) or []
    
    xp_profile = xp_data.get("xp", {}) or {}
    total_xp = "0"
    current_level = "0"
    if isinstance(xp_profile, dict):
        total_xp = xp_profile.get("totalXp", xp_profile.get("xp", "0"))
        current_level = xp_profile.get("level", "0")

    # Sort achievements by date earned (newest first)
    def parse_date(x):
        try:
            return datetime.fromisoformat(x.get("grantedOn", "").replace("Z", "+00:00"))
        except:
            return datetime.min

    sorted_achievements = sorted(achievements, key=parse_date, reverse=True)

    # 2. Extract Verifiable Credentials (Applied Skills & Certifications)
    user_creds = creds.get("userCredentials", []) or []
    verifiable_list = []
    for cred in user_creds:
        name = clean_uid(cred.get("sourceUid", ""))
        cred_id = cred.get("credentialId", "N/A")
        raw_date = cred.get("awardedOn", "")
        date_earned = raw_date.split("T")[0] if "T" in raw_date else raw_date
        status = cred.get("credentialStatus", "Active")
        verifiable_list.append(f"- **{name}** (Credential ID: `{cred_id}` | Earned: {date_earned} | Status: {status})")

    # 3. Build AI-Optimized Markdown for the main README.md
    md = []
    md.append("### Microsoft Learn Summary")
    md.append(f"- **Total Experience Points (XP):** {format_num(total_xp)}")
    md.append(f"- **Current Learning Level:** {current_level}")
    md.append(f"- **Completed Learning Paths:** {format_num(len(learning_paths))}")
    md.append(f"- **Completed Modules:** {format_num(len(modules))}")
    md.append(f"- **Completed Individual Units:** {format_num(len(completed_units))}\n")

    if verifiable_list:
        md.append("### Verifiable Applied Skills & Credentials")
        md.extend(verifiable_list)
        md.append("")

    md.append("### Recent Achievements & Completed Badges")
    md.append(f"Showing the latest 50 of {format_num(len(sorted_achievements))} total achievements. The complete list is fully archived and searchable in our [complete achievements archive](./data/all_achievements.md).\n")
    
    for item in sorted_achievements[:50]:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        raw_date = item.get("grantedOn", "")
        date = raw_date.split("T")[0] if "T" in raw_date else raw_date
        verify_url = item.get("url", "")
        if verify_url and not verify_url.startswith("http"):
            verify_url = f"https://learn.microsoft.com{verify_url}"
        
        md.append(f"- **{title}** ({cat} | Earned: {date} | [Verify Credential]({verify_url}))")

    # 4. Update the README.md file safely
    if not os.path.exists(README_PATH):
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(f"{MARKER_START}\n{MARKER_END}\n")

    with open(README_PATH, "r", encoding="utf-8") as f:
        readme_content = f.read()

    if MARKER_START not in readme_content or MARKER_END not in readme_content:
        readme_content += f"\n\n{MARKER_START}\n{MARKER_END}\n"

    split_start = readme_content.split(MARKER_START)
    split_end = split_start[1].split(MARKER_END)
    
    updated_readme = (
        split_start[0] + 
        MARKER_START + "\n" + 
        "\n".join(md) + "\n" + 
        MARKER_END + 
        split_end[1]
    )

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated_readme)
    print("README.md updated successfully!")

    # 5. Write the COMPLETE backlog of all achievements to data/all_achievements.md
    print(f"Generating complete archive in {ALL_ACHIEVEMENTS_PATH}...")
    archive_md = []
    archive_md.append("# Complete Microsoft Learn Achievements Archive\n")
    archive_md.append(f"This document contains a complete, chronological record of all {format_num(len(sorted_achievements))} achievements earned on Microsoft Learn. This file is highly structured to allow LLMs, search engine indexes, and automated parsers to easily read, index, and verify historical credentials.\n")
    archive_md.append("| Achievement Title | Category | Date Earned | Verification Link |")
    archive_md.append("| :--- | :--- | :--- | :--- |")

    for item in sorted_achievements:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        raw_date = item.get("grantedOn", "")
        date = raw_date.split("T")[0] if "T" in raw_date else raw_date
        verify_url = item.get("url", "")
        if verify_url and not verify_url.startswith("http"):
            verify_url = f"https://learn.microsoft.com{verify_url}"
        
        # Clean up text for markdown table safety
        title_clean = title.replace("|", "\\|")
        archive_md.append(f"| {title_clean} | {cat} | {date} | [Verify]({verify_url}) |")

    with open(ALL_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("Complete archive file updated successfully!")

if __name__ == "__main__":
    main()
