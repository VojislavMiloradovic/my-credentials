import os
import csv
import re
import sys
from datetime import datetime

README_PATH = "README.md"
AWS_ACHIEVEMENTS_PATH = "archives/aws-skills.md" 

MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

CLOUD_QUEST_STATS = {
    "Builder Level": 12,
    "Reputation Level": 95,
    "Pets Unlocked": 17,
    "Vehicles Unlocked": 2,
    "Role": "Cloud Practitioner / Generative AI Practitioner",
    "Total Solutions Built": 20
}

def normalize_header(header):
    return "".join(header.lower().split()).replace("_", "").replace("-", "")

def find_column_indices(headers):
    mapping = {"title": None, "date": None, "type": None, "duration": None}
    
    for i, h in enumerate(headers):
        norm = normalize_header(h)
        if any(keyword in norm for keyword in ["title", "activityname", "coursename", "subject", "learningobject", "trainingname"]):
            if "type" not in norm: 
                mapping["title"] = i
        if any(keyword in norm for keyword in ["date", "completedon", "completiondate", "finished", "grantedon", "awardedon"]):
            mapping["date"] = i
        if any(keyword in norm for keyword in ["type", "activitytype", "deliverymethod", "category"]):
            mapping["type"] = i
        if any(keyword in norm for keyword in ["duration", "hours", "time", "length"]):
            mapping["duration"] = i

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
    """Standardize CSV date strings into strict ISO formats (YYYY-MM-DD or YYYY-MM)."""
    if not date_str:
        return "N/A"
    
    cleaned_date = re.sub(r'\s+', ' ', date_str.strip())
    
    # Check YYYY-MM-DD formats first
    full_formats = (
        "%Y-%m-%d", 
        "%B %d, %Y", 
        "%b %d, %Y", 
        "%m/%d/%Y", 
        "%d/%m/%Y", 
        "%Y-%m-%dT%H:%M:%S", 
        "%d.%m.%Y"
    )
    for fmt in full_formats:
        try:
            return datetime.strptime(cleaned_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Check YYYY-MM formats if day is missing
    month_formats = ("%B %Y", "%b %Y", "%Y-%m")
    for fmt in month_formats:
        try:
            return datetime.strptime(cleaned_date, fmt).strftime("%Y-%m")
        except ValueError:
            continue
            
    return date_str.strip()

def is_garbage_row(title):
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
        
    if title_lower in ["title", "activity name", "name", "subject", "training name"]:
        return True
        
    return False

def main():
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

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_idx = -1
    delimiter = ","
    
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in ["activity name", "activity title", "course name", "training name", "completion date", "completed on", "title"]):
            header_idx = idx
            if ";" in line and line.count(";") > line.count(","):
                delimiter = ";"
            break
            
    if header_idx == -1:
        for idx, line in enumerate(lines):
            if "," in line or ";" in line:
                header_idx = idx
                if ";" in line and line.count(";") > line.count(","):
                    delimiter = ";"
                break
                
    if header_idx == -1:
        sys.exit(1)

    clean_csv_lines = lines[header_idx:]
    reader = csv.reader(clean_csv_lines, delimiter=delimiter)
    headers = next(reader)
    col_map = find_column_indices(headers)

    activities = []
    courses_count = 0
    labs_count = 0
    games_count = 0

    for row in reader:
        if not row:
            continue
            
        max_idx = max(filter(lambda x: x is not None, col_map.values()))
        if len(row) <= max_idx:
            continue
            
        title = row[col_map["title"]].strip()
        if is_garbage_row(title):
            continue
            
        raw_date = row[col_map["date"]].strip() if col_map["date"] is not None else ""
        date_completed = parse_csv_date(raw_date)
        
        raw_type = row[col_map["type"]].strip() if col_map["type"] is not None else "Training"
        duration = row[col_map["duration"]].strip() if col_map["duration"] is not None else "N/A"
        if not duration or duration.lower() == "null":
            duration = "N/A"

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

    activities.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)
    total_completions = len(activities)

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
    md.append(f"Showing the latest 10 activities. See the complete log of completed trainings in our [AWS achievements archive](./archives/aws-skills.md).\n")
    md.append("| Activity Title | Type | Date Completed | Duration |")
    md.append("| :--- | :--- | :--- | :--- |")
    for act in activities[:10]:
        md.append(f"| **{act['title']}** | {act['type']} | *{act['date']}* | {act['duration']} |")
    md.append("\n")

    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()

        if MARKER_START in readme_content and MARKER_END in readme_content:
            parts_before = readme_content.split(MARKER_START)[0]
            parts_after = readme_content.split(MARKER_END)[1]
            new_readme = f"{parts_before}{MARKER_START}\n" + "\n".join(md) + f"{MARKER_END}{parts_after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_readme)

    archive_md = []
    archive_md.append("# Complete AWS Skill Builder Achievements Archive\n")
    archive_md.append(f"This document contains a complete, historical audit trail of all {total_completions} AWS learning items completed on AWS Skill Builder.\n")
    archive_md.append("| Activity Title | Type | Date Completed | Duration | Certificate |")
    archive_md.append("| :--- | :--- | :--- | :--- | :--- |")

    for act in activities:
        title_clean = act["title"].replace("|", "\\|")
        archive_md.append(f"| {title_clean} | {act['type']} | {act['date']} | {act['duration']} | 🎓 Available on Profile |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(AWS_ACHIEVEMENTS_PATH), exist_ok=True)
    with open(AWS_ACHIEVEMENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))

if __name__ == "__main__":
    main()
