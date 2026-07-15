import os
import csv
import re
from datetime import datetime

# File Paths
CSV_PATH = "data/aws-training-activity.csv"
README_PATH = "README.md"
AWS_ACHIEVEMENTS_PATH = "data/aws_achievements.md"

MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

# --- 1. AWS CLOUD QUEST & SIMULEARN STATS ---
# Update these manually in this script when you hit new milestones!
CLOUD_QUEST_STATS = {
    "Builder Level": 12,
    "Reputation Level": 4,
    "Pets Unlocked": 3,
    "Vehicles Unlocked": 2,
    "Role": "Cloud Practitioner / Solutions Architect"
}

def normalize_header(header):
    """Clean headers to easily find matching fields despite capitalization or extra spaces."""
    return "".join(header.lower().split()).replace("_", "").replace("-", "")

def find_column_indices(headers):
    """Dynamically map column headers to standard fields."""
    mapping = {"title": None, "date": None, "type": None, "duration": None}
    
    for i, h in enumerate(headers):
        norm = normalize_header(h)
        if any(keyword in norm for keyword in ["title", "activityname", "coursename", "subject"]):
            mapping["title"] = i
        elif any(keyword in norm for keyword in ["date", "completedon", "completiondate", "finished"]):
            mapping["date"] = i
        elif any(keyword in norm for keyword in ["type", "activitytype", "deliverymethod"]):
            mapping["type"] = i
        elif any(keyword in norm for keyword in ["duration", "hours", "time", "length"]):
            mapping["duration"] = i
            
    return mapping

def parse_csv_date(date_str):
    """Standardize different CSV date strings into ISO format (YYYY-MM-DD)."""
    if not date_str:
        return ""
    # Try common CSV date formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%b %d, %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()

def main():
    print(f"Opening AWS data file: {CSV_PATH}...")
    if not os.path.exists(CSV_PATH):
        print(f"⚠️ Warning: {CSV_PATH} not found! Skipping AWS update.")
        return

    activities = []
    
    # Read and parse CSV
    with open(CSV_PATH, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            print("❌ Error: AWS CSV file is empty.")
            return
            
        col_map = find_column_indices(headers)
        
        # Verify required columns exist
        if col_map["title"] is None:
            print("❌ Error: Could not detect an 'Activity Title' column in the CSV.")
            return

        for row in reader:
            if not row or len(row) <= max(filter(None, col_map.values())):
                continue
                
            title = row[col_map["title"]].strip()
            if not title:
                continue
                
            raw_date = row[col_map["date"]].strip() if col_map["date"] is not None else ""
            date_completed = parse_csv_date(raw_date)
            
            activity_type = row[col_map["type"]].strip() if col_map["type"] is not None else "Training"
            duration = row[col_map["duration"]].strip() if col_map["duration"] is not None else "N/A"
            
            activities.append({
                "title": title,
                "date": date_completed,
                "type": activity_type,
                "duration": duration
            })

    # Sort achievements (newest completed first)
    activities.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    # Calculate summary metrics
    total_completions = len(activities)
    labs_count = sum(1 for a in activities if "lab" in a["type"].lower())
    courses_count = sum(1 for a in activities if "course" in a["type"].lower() or "digital" in a["type"].lower())
    games_count = sum(1 for a in activities if "game" in a["type"].lower() or "quest" in a["type"].lower())

    # Build Markdown Summary for the README.md
    md = []
    md.append("### AWS Skill Builder Summary")
    md.append(f"**Public Profile:** [Verify AWS Profile](https://skillsprofile.skillbuilder.aws/user/vojislavmiloradovic)  \n")
    
    md.append("#### Platform Progress Summary")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total Completed Activities** | {total_completions:,} |")
    md.append(f"| **Digital Courses** | {courses_count:,} |")
    md.append(f"| **Self-Paced Builder Labs** | {labs_count:,} |")
    md.append(f"| **In-Game Simulations (Cloud Quest)** | {games_count:,} |")
    md.append("\n")

    md.append("#### AWS Cloud Quest Stats")
    md.append("| Stat | Level / Value |")
    md.append("| :--- | :--- |")
    for key, val in CLOUD_QUEST_STATS.items():
        md.append(f"| **{key}** | {val} |")
    md.append("\n")

    md.append("#### Recent AWS Achievements")
    md.append(f"Showing the latest 10 activities. See the complete log of completed trainings in our [AWS achievements archive](./data/aws_achievements.md).\n")
    md.append("| Activity Title | Type | Date Completed | Duration |")
    md.append("| :--- | :--- | :--- | :--- |")
    for act in activities[:10]:
        md.append(f"| **{act['title']}** | {act['type']} | *{act['date']}* | {act['duration']} |")
    md.append("\n")

    # Update README.md
    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()

        if MARKER_START in readme_content and MARKER_END in readme_content:
            parts_before = readme_content.split(MARKER_START)[0]
            parts_after = readme_content.split(MARKER_END)[1]
            new_readme = f"{parts_before}{MARKER_START}\n" + "\n".join(md) + f"{MARKER_END}{parts_after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_readme)
            print("Successfully updated README.md with AWS data!")
        else:
            print("Could not find AWS HTML tags in README.md.")
    else:
        print("README.md not found.")

    # Write Complete Log to data/aws_achievements.md
    print(f"Generating complete AWS archive in {AWS_ACHIEVEMENTS_PATH}...")
    archive_md = []
    archive_md.append("# Complete AWS Skill Builder Achievements Archive\n")
    archive_md.append(f"This document contains a complete, historical audit trail of all {total_completions} AWS learning items, digital courses, games, and labs completed on AWS Skill Builder.\n")
    archive_md.append("| Activity Title | Type | Date Completed | Duration | Certificate |")
    archive_md.append("| :--- | :--- | :--- | :--- | :--- |")

    for act in activities:
        title_clean = act["title"].replace("|", "\\|")
        # Every completed training comes with a cert (though not all are Credly badges)
        archive_md.append(f"| {title_clean} | {act['type']} | {act['date']} | {act['duration']} | 🎓 Available on Profile |")

    with open(AWS_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("Complete AWS Archive updated successfully!")

if __name__ == "__main__":
    main()
