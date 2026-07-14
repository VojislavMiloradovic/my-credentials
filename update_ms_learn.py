import os
import json
from datetime import datetime

# Configuration
DATA_DIR = "./ms_learn_data"
COMBINED_FILE = "microsoft_learn_profile.json"  # If merged
README_PATH = "./README.md"
MARKER_START = "<!-- MS_LEARN_START -->"
MARKER_END = "<!-- MS_LEARN_END -->"
BASE_URL = "https://learn.microsoft.com"

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {filepath}: {e}")
    return None

def main():
    # 1. Load data defensively from combined or separate files
    print("Loading Microsoft Learn data...")
    combined = load_json(COMBINED_FILE)
    
    if combined:
        progress = combined.get("Progress", {})
        xp_data = combined.get("XP", {})
        skills = combined.get("SkillAssessment", {})
        creds = combined.get("VerifiableCredentials", {})
    else:
        progress = load_json(os.path.join(DATA_DIR, "Progress.json")) or {}
        xp_data = load_json(os.path.join(DATA_DIR, "XP.json")) or {}
        skills = load_json(os.path.join(DATA_DIR, "SkillAssessment.json")) or {}
        creds = load_json(os.path.join(DATA_DIR, "VerifiableCredentials.json")) or {}

    # Extract metrics
    completed_items = progress.get("completedLearningItems", [])
    learning_paths = progress.get("learningPathPasses", [])
    modules = progress.get("moduleAssessments", [])
    achievements = xp_data.get("achievements", [])
    
    # Safely get XP values
    xp_profile = xp_data.get("xp", {})
    total_xp = "N/A"
    current_level = "N/A"
    if isinstance(xp_profile, dict):
        total_xp = xp_profile.get("totalXp", xp_profile.get("xp", "N/A"))
        current_level = xp_profile.get("level", "N/A")

    print(f"Found {len(achievements)} achievements, {len(learning_paths)} learning paths, and {len(modules)} modules.")

    # Sort achievements by granted date (newest first)
    def get_granted_date(x):
        try:
            return datetime.fromisoformat(x.get("grantedOn", "").replace("Z", "+00:00"))
        except:
            return datetime.min
            
    sorted_achievements = sorted(achievements, key=get_granted_date, reverse=True)

    # 2. Build the Markdown Showcase
    md = []
    md.append("## 🏆 Microsoft Learn Portfolio")
    
    # Stats Banner Table
    md.append("\n### 📊 Learning Stats\n")
    md.append("| 🟢 Total XP | ⭐ Level | 🛣️ Learning Paths | 📦 Modules | 📝 Completed Units |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    md.append(f"| **{total_xp:,}** | **{current_level}** | **{len(learning_paths):,}** | **{len(modules):,}** | **{len(completed_items):,}** |\n")

    # High-Value Skills & Creds / Labs
    lab_reports = skills.get("labSessionScoreReports", [])
    passed_labs = [lab for lab in lab_reports if lab.get("passed") or lab.get("scored") == "Passed"]
    
    if passed_labs:
        md.append("### 🛠️ Passed Applied Skills & Assessment Labs\n")
        md.append("| Lab Assessment | Completed Date | Score |")
        md.append("| :--- | :--- | :--- |")
        for lab in passed_labs[:10]:  # Show top 10
            title = lab.get("labProfileName", "Interactive Assessment")
            date_str = lab.get("endTime", "").split("T")[0]
            score = lab.get("score", "Passed")
            md.append(f"| **{title}** | {date_str} | `{score}%` |")
        md.append("\n")

    # Beautiful Recent Badges Grid (12 items)
    md.append("### 🏅 Recent Achievements\n")
    md.append("<table>")
    cols = 4
    recent_badges = sorted_achievements[:12]
    
    for i in range(0, len(recent_badges), cols):
        row_items = recent_badges[i:i+cols]
        # Image row
        md.append("  <tr>")
        for item in row_items:
            img_path = item.get("imageUrl", "/learn/achievements/generic-badge.svg")
            img_url = img_path if img_path.startswith("http") else f"{BASE_URL}{img_path}"
            title = item.get("title", "Module Badge")
            md.append(f'    <td align="center" width="180px"><img src="{img_url}" width="80px" alt="{title}"/><br/><strong>{title}</strong></td>')
        # Pad empty columns if row is short
        if len(row_items) < cols:
            for _ in range(cols - len(row_items)):
                md.append('    <td width="180px"></td>')
        md.append("  </tr>")
        
    md.append("</table>\n")

    # Collapsible Backlog for search engines and deep dive
    if len(sorted_achievements) > 12:
        md.append("<details>")
        md.append(f"<summary>🔍 Click to view remaining {len(sorted_achievements) - 12:,} Achievements & Badges</summary>\n")
        md.append("| Title | Category | Earned On | Profile Link |")
        md.append("| :--- | :--- | :--- | :--- |")
        for item in sorted_achievements[12:]:
            title = item.get("title", "Module Completer")
            cat = item.get("category", "module").title()
            date = item.get("grantedOn", "").split("T")[0]
            raw_url = item.get("url", "")
            url = raw_url if raw_url.startswith("http") else f"{BASE_URL}{raw_url}"
            md.append(f"| {title} | {cat} | {date} | [Verify]({url}) |")
        md.append("\n</details>\n")

    # 3. Write updates directly into README
    if not os.path.exists(README_PATH):
        print(f"No {README_PATH} found, generating a brand new one...")
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(f"{MARKER_START}\n{MARKER_END}\n")

    with open(README_PATH, "r", encoding="utf-8") as f:
        readme_content = f.read()

    if MARKER_START not in readme_content or MARKER_END not in readme_content:
        print("Markers not found in README. Append them to target the injection.")
        # Automatically inject markers at the end of the README if they don't exist
        readme_content += f"\n\n{MARKER_START}\n{MARKER_END}\n"

    split_start = readme_content.split(MARKER_START)
    split_end = split_start[1].split(MARKER_END)
    
    new_readme = (
        split_start[0] + 
        MARKER_START + "\n" + 
        "\n".join(md) + "\n" + 
        MARKER_END + 
        split_end[1]
    )

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_readme)
        
    print("README.md updated successfully with your latest credentials! 🎉")

if __name__ == "__main__":
    main()
