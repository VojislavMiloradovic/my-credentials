import os
import csv
import re
import sys
import glob
from datetime import datetime

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "aws-skills"
RAW_BASE = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"

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
    if not date_str:
        return "N/A"
    
    cleaned_date = re.sub(r'\s+', ' ', date_str.strip())
    
    full_formats = (
        "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"
    )
    for fmt in full_formats:
        try:
            return datetime.strptime(cleaned_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

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

def clean_old_chunks():
    pattern = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

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

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    clean_old_chunks()

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
    now_ym = datetime.now().strftime("%Y-%m")

    # 1. Monolithic Complete Archive
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    monolith_path = os.path.join(ARCHIVE_DIR, monolith_filename)

    archive_md = []
    archive_md.append("# Complete AWS Skill Builder Achievements Archive\n")
    archive_md.append(f"This document contains a complete, historical audit trail of all {total_completions} AWS learning items completed on AWS Skill Builder.\n")
    archive_md.append("| Activity Title | Type | Date Completed | Duration | Certificate |")
    archive_md.append("| :--- | :--- | :--- | :--- | :--- |")

    formatted_rows = []
    for act in activities:
        title_clean = act["title"].replace("|", "\\|")
        row = f"| {title_clean} | {act['type']} | {act['date']} | {act['duration']} | 🎓 Available on Profile |"
        formatted_rows.append((row, act['date']))
        archive_md.append(row)

    archive_md.append(f"\n\n[← Back to Index](./{PLATFORM_PREFIX}-index.md) | [← README](../README.md)\n")
    with open(monolith_path, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))

    # 2. Chunking Logic (~10 KB limit per file)
    chunks = []
    current_chunk_rows = []
    current_chunk_bytes = 0
    MAX_BYTES = 9500

    for row_text, row_date in formatted_rows:
        row_len = len(row_text.encode("utf-8")) + 1
        if current_chunk_bytes + row_len > MAX_BYTES and current_chunk_rows:
            chunks.append(current_chunk_rows)
            current_chunk_rows = []
            current_chunk_bytes = 0
        current_chunk_rows.append((row_text, row_date))
        current_chunk_bytes += row_len
    if current_chunk_rows:
        chunks.append(current_chunk_rows)

    total_chunks = len(chunks)
    chunk_meta = []

    for i, chunk_rows in enumerate(chunks, start=1):
        chunk_filename = f"{PLATFORM_PREFIX}-{now_ym}-part-{i:02d}.md"
        chunk_path = os.path.join(ARCHIVE_DIR, chunk_filename)
        
        start_date = chunk_rows[-1][1]
        end_date = chunk_rows[0][1]
        
        prev_link = f"[{PLATFORM_PREFIX}-{now_ym}-part-{i-1:02d}.md]({PLATFORM_PREFIX}-{now_ym}-part-{i-1:02d}.md)" if i > 1 else "None"
        next_link = f"[{PLATFORM_PREFIX}-{now_ym}-part-{i+1:02d}.md]({PLATFORM_PREFIX}-{now_ym}-part-{i+1:02d}.md)" if i < total_chunks else "None"
        
        c_md = []
        c_md.append("---")
        c_md.append(f"archive_platform: AWS Skill Builder")
        c_md.append(f"chunk_part: {i} of {total_chunks}")
        c_md.append(f"date_range: {start_date} to {end_date}")
        c_md.append(f"total_entries: {len(chunk_rows)}")
        c_md.append(f"raw_url: {RAW_BASE}/{chunk_filename}")
        c_md.append("---\n")
        
        c_md.append(f"# AWS Skill Builder Achievements — Part {i:02d}\n")
        c_md.append(f"> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n")
        c_md.append("| Activity Title | Type | Date Completed | Duration | Certificate |")
        c_md.append("| :--- | :--- | :--- | :--- | :--- |")
        
        for r_text, _ in chunk_rows:
            c_md.append(r_text)
            
        c_md.append(f"\n---\n> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link}\n")
        
        content = "\n".join(c_md)
        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        file_size_kb = round(len(content.encode("utf-8")) / 1024, 2)
        est_tokens = int(len(content) / 4)
        chunk_meta.append({
            "filename": chunk_filename,
            "part": i,
            "date_range": f"{start_date} to {end_date}",
            "size_kb": file_size_kb,
            "tokens": est_tokens,
            "entries": len(chunk_rows),
            "raw_url": f"{RAW_BASE}/{chunk_filename}"
        })

    # 3. Master Platform Index File
    index_filename = f"{PLATFORM_PREFIX}-index.md"
    index_path = os.path.join(ARCHIVE_DIR, index_filename)
    
    mono_bytes = os.path.getsize(monolith_path) if os.path.exists(monolith_path) else 0
    mono_kb = round(mono_bytes / 1024, 2)
    mono_tokens = int(mono_bytes / 4)

    idx_md = []
    idx_md.append(f"# AWS Skill Builder Archive Index\n")
    idx_md.append(f"This directory provides chunked, AI-readable historical records for AWS Skill Builder training activities.\n")
    idx_md.append(f"## Archive Overview\n")
    idx_md.append(f"- **Total Activities Archived:** {total_completions}")
    idx_md.append(f"- **Monolithic File Size:** ~{mono_kb} KB (~{mono_tokens:,} tokens)")
    idx_md.append(f"- **Total Chunk Parts:** {total_chunks} chunk(s)\n")
    
    idx_md.append(f"### Monolithic Archive (Complete)\n")
    idx_md.append(f"| File Name | Size (KB) | Est. Tokens | Recommended For | Direct Raw URL |")
    idx_md.append(f"| :--- | :---: | :---: | :--- | :--- |")
    idx_md.append(f"| [`{monolith_filename}`](./{monolith_filename}) | {mono_kb} KB | ~{mono_tokens:,} | Large Context Windows (>100k tokens) | [Raw Link]({RAW_BASE}/{monolith_filename}) |\n")
    
    idx_md.append(f"### Chunked Archive Parts (~10 KB Slices)\n")
    idx_md.append(f"| Part | File Name | Date Range | Entries | Size (KB) | Est. Tokens | Direct Raw URL |")
    idx_md.append(f"| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
    
    for cm in chunk_meta:
        idx_md.append(f"| Part {cm['part']:02d} | [`{cm['filename']}`](./{cm['filename']}) | `{cm['date_range']}` | {cm['entries']} | {cm['size_kb']} KB | ~{cm['tokens']} | [Raw URL]({cm['raw_url']}) |")

    idx_md.append(f"\n\n[← Back to Main README](../README.md)\n")
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(idx_md))

    # 4. Update README.md
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

    latest_chunk_raw = chunk_meta[0]['raw_url'] if chunk_meta else f"{RAW_BASE}/{monolith_filename}"
    index_raw = f"{RAW_BASE}/{index_filename}"

    md.append("#### Recent AWS Achievements")
    md.append(f"Showing latest 10 activities. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n")
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

if __name__ == "__main__":
    main()
