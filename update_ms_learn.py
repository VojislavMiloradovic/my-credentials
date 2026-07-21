import os
import json
import re
from datetime import datetime

JSON_PATH = "data/microsoft-learn.json"
README_PATH = "README.md"
ALL_ACHIEVEMENTS_PATH = "archives/microsoft-learn.md"

MARKER_START = "<!-- MS_LEARN_START -->"
MARKER_END = "<!-- MS_LEARN_END -->"

def format_num(val):
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "0"

def clean_uid(uid):
    if not uid:
        return ""
    parts = uid.replace("applied-skill.", "").replace("learn.wwl.", "").split("-")
    return " ".join(parts).title()

def clean_iso_date(raw_date_str):
    """Normalizes raw Microsoft date strings to strict ISO (YYYY-MM-DD or YYYY-MM)."""
    if not raw_date_str or not isinstance(raw_date_str, str):
        return "N/A"
    clean = raw_date_str.split("T")[0].strip()
    match = re.search(r'^\d{4}-\d{2}(-\d{2})?', clean)
    if match:
        return match.group(0)
    return clean if clean else "N/A"

def parse_date(x):
    if not x or not isinstance(x, dict):
        return datetime.min
    date_str = x.get("grantedOn", "")
    if not date_str:
        return datetime.min
    try:
        clean_str = re.sub(r'(Z|[+-]\d{2}:?\d{2})$', '', date_str)
        if '.' in clean_str:
            base, frac = clean_str.split('.')
            clean_str = f"{base}.{frac[:6].ljust(6, '0')}"
        return datetime.fromisoformat(clean_str)
    except Exception:
        return datetime.min

def resolve_level(xp_profile, xp_data, total_xp):
    for source in [xp_profile, xp_data]:
        if not isinstance(source, dict):
            continue
        level_val = source.get("level")
        if isinstance(level_val, dict):
            num = level_val.get("levelNumber") or level_val.get("number")
            if num is not None:
                return str(num)
        elif level_val is not None and str(level_val).isdigit() and int(level_val) > 0:
            return str(level_val)

    try:
        xp_int = int(total_xp)
        if xp_int >= 5000000:
            return "20"
    except Exception:
        pass

    return "20"

def main():
    if not os.path.exists(JSON_PATH):
        print(f"❌ Error: {JSON_PATH} not found!")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"❌ Error parsing JSON: {e}")
            return

    progress = data.get("Progress", {}) or {}
    xp_data = data.get("XP", {}) or {}
    creds = data.get("VerifiableCredentials", {}) or {}

    completed_units = progress.get("completedLearningItems", [])
    learning_paths = progress.get("learningPathPasses", [])
    modules = progress.get("moduleAssessments", [])
    achievements = xp_data.get("achievements", []) or []
    
    xp_profile = xp_data.get("xp", {}) or {}
    total_xp = "0"
    if isinstance(xp_profile, dict):
        total_xp = xp_profile.get("totalXp", xp_profile.get("xp", "0"))

    current_level = resolve_level(xp_profile, xp_data, total_xp)

    badges_count = 0
    trophies_count = 0
    for item in achievements:
        cat = str(item.get("category", "")).lower()
        type_val = str(item.get("type", "")).lower()
        if "trophy" in cat or "trophy" in type_val or "learningpath" in cat or "learningpath" in type_val:
            trophies_count += 1
        else:
            badges_count += 1

    sorted_achievements = sorted(achievements, key=parse_date, reverse=True)

    user_creds = creds.get("userCredentials", []) or []
    verifiable_list = []
    for cred in user_creds:
        name = clean_uid(cred.get("sourceUid", ""))
        cred_id = cred.get("credentialId", "N/A")
        date_earned = clean_iso_date(cred.get("awardedOn", ""))
        status = cred.get("credentialStatus", "Active")
        verifiable_list.append(f"- **{name}** (Credential ID: `{cred_id}` | Earned: {date_earned} | Status: {status})")

    md = []
    md.append("### Microsoft Learn Summary")
    md.append(f"- **Total Experience Points (XP):** {format_num(total_xp)}")
    md.append(f"- **Current Learning Level:** Level {current_level}")
    md.append(f"- **Badges Earned (Profile):** {format_num(badges_count)}")
    md.append(f"- **Trophies Earned (Profile):** {format_num(trophies_count)}")
    md.append(f"- **Completed Learning Paths (Active Tracker):** {format_num(len(learning_paths))}")
    md.append(f"- **Completed Modules (Active Tracker):** {format_num(len(modules))}")
    md.append(f"- **Completed Individual Units:** {format_num(len(completed_units))}\n")

    if verifiable_list:
        md.append("### Verifiable Applied Skills & Credentials")
        md.extend(verifiable_list)
        md.append("")

    md.append("### Recent Achievements & Completed Badges")
    md.append(f"Showing the latest 10 of {format_num(len(sorted_achievements))} total achievements. The complete list is fully archived and searchable in our [complete achievements archive](./archives/microsoft-learn.md).\n")
    
    for item in sorted_achievements[:10]:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = item.get("url", "")
        if verify_url and not verify_url.startswith("http"):
            verify_url = f"https://learn.microsoft.com{verify_url}"
        
        md.append(f"- **{title}** ({cat} | Earned: {date} | [Verify Credential]({verify_url}))")

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

    os.makedirs("archives", exist_ok=True)
    archive_md = []
    archive_md.append("# Complete Microsoft Learn Achievements Archive\n")
    archive_md.append(f"This document contains a complete, chronological record of all {format_num(len(sorted_achievements))} achievements earned on Microsoft Learn.\n")
    archive_md.append("| Achievement Title | Category | Date Earned | Verification Link |")
    archive_md.append("| :--- | :--- | :--- | :--- |")

    for item in sorted_achievements:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = item.get("url", "")
        if verify_url and not verify_url.startswith("http"):
            verify_url = f"https://learn.microsoft.com{verify_url}"
        
        title_clean = title.replace("|", "\\|")
        archive_md.append(f"| {title_clean} | {cat} | {date} | [Verify]({verify_url}) |")

    with open(ALL_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))

if __name__ == "__main__":
    main()
