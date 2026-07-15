import os
import csv
import re
import sys
from datetime import datetime

# File Paths
README_PATH = "README.md"
AWS_ACHIEVEMENTS_PATH = "data/aws_achievements.md"

MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

# --- 1. AWS CLOUD QUEST & SIMULEARN STATS ---
# Update these manually in this script when you hit new milestones!
CLOUD_QUEST_STATS = {
    "Builder Level": 12,
    "Reputation Level": 95,
    "Pets Unlocked": 17,
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
        # Match title / name fields
        if any(keyword in norm for keyword in ["title", "activityname", "coursename", "subject", "learningobject", "trainingname"]):
            if "type" not in norm:  # avoid matching 'activitytype'
                mapping["title"] = i
        # Match date fields
        if any(keyword in norm for keyword in ["date", "completedon", "completiondate", "finished", "grantedon", "awardedon"]):
            mapping["date"] = i
        # Match type fields
        if any(keyword in norm for keyword in ["type", "activitytype", "deliverymethod", "category"]):
            mapping["type"] = i
        # Match duration fields
        if any(keyword in norm for keyword in ["duration", "hours", "time", "length"]):
            mapping["duration"] = i

    # Broad fallback for title if not yet resolved
    if mapping["title"] is None:
        for i, h in enumerate(headers):
            norm = normalize_header(h)
            if "name" in norm:
                mapping["title"] = i
                break
        # Ultimate fallback to first column
        if mapping["title"] is None and len(headers) > 0:
            mapping["title"] = 0
            
    return mapping

def parse_csv_date(date_str):
    """Standardize different CSV date strings into ISO format (YYYY-MM-DD)."""
    if not date_str:
        return ""
    # Try common CSV date formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%b %d, %Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()

def main():
    # 1. Dynamically locate the CSV file (handling casing, typos like .cvs, and paths)
    possible_names = [
        "data/aws-training-activity.csv",
        "data/aws-training-activity.cvs",
        "data/aws-training-activity.CSV",
        "data/aws-training-activity.CVS",
        "aws-training-activity.csv",
        "aws-training-activity.cvs"
    ]
    csv_path = None
    for name in possible_names:
        if os.path.exists(name):
            csv_path = name
            break

    if not csv_path:
        print("❌ Error: AWS Training CSV file not found!")
        print("Looking inside 'data/' directory to help you debug:")
        if os.path.exists("data"):
            print(f"Contents of 'data/': {os.listdir('data')}")
        else:
            print("'data/' directory does not even exist in the workspace!")
        print("Please ensure your uploaded CSV is named exactly 'aws-training-activity.csv' (or .cvs) and placed inside the 'data/' folder.")
        sys.exit(1)

    print(f"✅ Found AWS data file at: {csv_path}")

    # 2. Detect delimiter (handles European Excel exports which use semicolons ';')
    delimiter = ","
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            first_line = f.readline()
            if ";" in first_line and first_line.count(";") > first_line.count(","):
                delimiter = ";"
                print("ℹ️ Detected semicolon (;) delimiter (likely a European Excel CSV export).")
            else:
                print("ℹ️ Detected standard comma (,) delimiter.")
    except Exception as e:
        print(f"❌ Error reading file to check delimiter: {e}")
        sys.exit(1)

    activities = []
    
    # 3. Read and parse CSV
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration:
            print("❌ Error: AWS CSV file is completely empty.")
            sys.exit(1)
            
        print(f"ℹ️ Row headers found in CSV: {headers}")
        col_map = find_column_indices(headers)
        print(f"ℹ️ Mapped Columns -> Title: Index {col_map['title']}, Date: Index {col_map['date']}, Type: Index {col_map['type']}, Duration: Index {col_map['duration']}")
        
        # Verify required columns exist
        if col_map["title"] is None:
            print("❌ Error: Could not detect an 'Activity Title' or 'Name' column in your CSV.")
            print(f"Headers present: {headers}")
            sys.exit(1)

        for row_num, row in enumerate(reader, start=2):
            if not row:
                continue
            # Handle potential short rows defensively
            max_idx = max(filter(lambda x: x is not None, col_map.values()))
            if len(row) <= max_idx:
                print(f"⚠️ Warning: Row {row_num} is shorter than expected index. Skipping: {row}")
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

    print(f"✅ Successfully parsed {len(activities)} AWS activities from CSV.")

    # Sort achievements (newest completed first)
    activities.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    # Calculate summary metrics
    total_completions = len(activities)
    labs_count = sum(1 for a in activities if "lab" in a["type"].lower() or "lab" in a["title"].lower())
    courses_count = sum(1 for a in activities if "course" in a["type"].lower() or "digital" in a["type"].lower() or "e-learning" in a["type"].lower())
    games_count = sum(1 for a in activities if any(k in a["type"].lower() or k in a["title"].lower() for k in ["game", "quest", "simulearn"]))

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
            print("✅ Successfully updated README.md with AWS data!")
        else:
            print("⚠️ Error: Could not find AWS HTML tags (<!-- AWS_SKILLS_START --> / <!-- AWS_SKILLS_END -->) in README.md.")
            sys.exit(1)
    else:
        print("❌ Error: README.md not found in the workspace.")
        sys.exit(1)

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

    # Ensure the data directory exists (just in case)
    os.makedirs(os.path.dirname(AWS_ACHIEVEMENTS_PATH), exist_ok=True)
    with open(AWS_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Complete AWS Archive updated successfully!")

if __name__ == "__main__":
    main()            })

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
