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
    "Role": "Cloud Practitioner / Generative AI Practitioner",
    "Total Solutions Built": 20
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
        if mapping["title"] is None and len(headers) > 0:
            mapping["title"] = 0
            
    return mapping

def parse_csv_date(date_str):
    """Standardize different CSV date strings into ISO format (YYYY-MM-DD)."""
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%b %d, %Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()

def is_garbage_row(title):
    """Identify and filter out metadata, headers, or footers parsed as courses."""
    title_lower = title.lower().strip()
    if not title_lower:
        return True
    
    trash_keywords = [
        "generated on", "total rows", "report name", "filter", 
        "aws skill builder", "activity name", "activity title", 
        "confidential", "copyright", "page ", "export", "run date"
    ]
    if any(k in title_lower for k in trash_keywords):
        return True
        
    # If the title is literally just the column header text
    if title_lower in ["title", "activity name", "name", "subject", "training name"]:
        return True
        
    return False

def main():
    # 1. Locate the CSV file
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
        sys.exit(1)

    print(f"✅ Found AWS data file at: {csv_path}")

    # 2. Read lines to skip metadata and find the TRUE header row
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        sys.exit(1)

    header_idx = -1
    delimiter = ","
    
    # Scan for a line containing recognizable table headers
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["activity name", "activity title", "course name", "training name", "completion date", "completed on", "title"]):
            header_idx = idx
            if ";" in line and line.count(";") > line.count(","):
                delimiter = ";"
            break
            
    if header_idx == -1:
        # Fallback: find the first line with multiple columns
        for idx, line in enumerate(lines):
            if "," in line or ";" in line:
                header_idx = idx
                if ";" in line and line.count(";") > line.count(","):
                    delimiter = ";"
                break
                
    if header_idx == -1:
        print("❌ Error: Could not locate table headers in CSV.")
        sys.exit(1)

    print(f"ℹ️ Actual table headers found on Line {header_idx + 1}. Using delimiter: '{delimiter}'")

    # 3. Parse data starting from the discovered header row
    clean_csv_lines = lines[header_idx:]
    reader = csv.reader(clean_csv_lines, delimiter=delimiter)
    
    try:
        headers = next(reader)
    except StopIteration:
        print("❌ Error: Header parsing failed.")
        sys.exit(1)

    col_map = find_column_indices(headers)
    print(f"ℹ️ Column Mapping -> Title: {col_map['title']}, Date: {col_map['date']}, Type: {col_map['type']}, Duration: {col_map['duration']}")

    activities = []
    courses_count = 0
    labs_count = 0
    games_count = 0

    for row_num, row in enumerate(reader, start=header_idx + 2):
        if not row:
            continue
            
        max_idx = max(filter(lambda x: x is not None, col_map.values()))
        if len(row) <= max_idx:
            continue
            
        title = row[col_map["title"]].strip()
        
        # Skip metadata/header replicas
        if is_garbage_row(title):
            continue
            
        raw_date = row[col_map["date"]].strip() if col_map["date"] is not None else ""
        date_completed = parse_csv_date(raw_date)
        
        raw_type = row[col_map["type"]].strip() if col_map["type"] is not None else "Training"
        duration = row[col_map["duration"]].strip() if col_map["duration"] is not None else "N/A"
        if not duration or duration.lower() == "null":
            duration = "N/A"

        # --- SMART CLASSIFICATION ENGINE ---
        is_lab = any(k in raw_type.lower() or k in title.lower() for k in ["lab", "hands-on", "builder lab", "sandbox"])
        is_game = any(k in raw_type.lower() or k in title.lower() for k in ["game", "quest", "simulearn", "simulation"])

        if is_game:
            games_count += 1
            display_type = "Game / Quest"
        elif is_lab:
            labs_count += 1
            display_type = "Self-Paced Lab"
        else:
            courses_count += 1
            display_type = "Digital Course"

        activities.append({
            "title": title,
            "date": date_completed,
            "type": display_type,
            "duration": duration
        })

    print(f"✅ Successfully parsed {len(activities)} valid AWS activities.")

    # Sort achievements (newest completed first)
    activities.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)
    total_completions = len(activities)

    # 4. Build Markdown Summary for the README.md
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
            print("✅ Successfully updated README.md with clean AWS data!")
        else:
            print("❌ Error: Could not find AWS HTML tags in README.md.")
            sys.exit(1)
    else:
        print("❌ Error: README.md not found.")
        sys.exit(1)

    # 5. Write Complete Log to data/aws_achievements.md
    print(f"Generating complete AWS archive in {AWS_ACHIEVEMENTS_PATH}...")
    archive_md = []
    archive_md.append("# Complete AWS Skill Builder Achievements Archive\n")
    archive_md.append(f"This document contains a complete, historical audit trail of all {total_completions} AWS learning items, digital courses, games, and labs completed on AWS Skill Builder.\n")
    archive_md.append("| Activity Title | Type | Date Completed | Duration | Certificate |")
    archive_md.append("| :--- | :--- | :--- | :--- | :--- |")

    for act in activities:
        title_clean = act["title"].replace("|", "\\|")
        archive_md.append(f"| {title_clean} | {act['type']} | {act['date']} | {act['duration']} | 🎓 Available on Profile |")

    os.makedirs(os.path.dirname(AWS_ACHIEVEMENTS_PATH), exist_ok=True)
    with open(AWS_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Complete AWS Archive updated successfully!")

if __name__ == "__main__":
    main()
