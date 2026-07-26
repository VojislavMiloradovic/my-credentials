import csv
import os
import re
from datetime import datetime, timezone

from archiver import RAW_BASE_DEFAULT, generate_platform_archive

CSV_PATH = "data/aws-training-activity.csv"
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "aws-skills"
PLATFORM_NAME = "AWS Skill Builder"

MARKER_START = "<!-- AWS_SKILLS_START -->"
MARKER_END = "<!-- AWS_SKILLS_END -->"

CLOUD_QUEST_STATS = {
    "Builder Level": 12,
    "Reputation Level": 95,
    "Pets Unlocked": 17,
    "Vehicles Unlocked": 2,
    "Role": "Cloud Practitioner / Generative AI Practitioner",
    "Total Solutions Built": 20,
}

MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "june": "06", "july": "07", "august": "08", "september": "09",
    "october": "10", "november": "11", "december": "12",
}


def get_field(row: dict, possible_keys: list[str], default: str = "") -> str:
    """Case-insensitive column accessor."""
    clean_row = {}
    for k, v in row.items():
        if k and v:
            clean_row[str(k).strip().lower()] = str(v).strip()

    for key in possible_keys:
        target = key.strip().lower()
        if target in clean_row:
            return clean_row[target]

    return default


def parse_and_clean_date(raw_date_str: str) -> tuple[datetime, str]:
    """Parses raw date strings into a timezone-aware datetime and formatted string."""
    min_date = datetime.min.replace(tzinfo=timezone.utc)
    if not raw_date_str or not isinstance(raw_date_str, str):
        return min_date, "N/A"

    clean_str = raw_date_str.strip()
    if not clean_str:
        return min_date, "N/A"

    # 1. Month Year string (e.g. "Feb 2026", "March 2026")
    match = re.match(r"^([a-zA-Z]+)\s+(\d{4})$", clean_str)
    if match:
        m_name, y_str = match.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            formatted = f"{y_str}-{m_num}"
            try:
                dt = datetime.strptime(f"{formatted}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return dt, formatted
            except ValueError:
                pass

    # 2. Standard numeric formats
    for fmt in ["%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]:
        try:
            dt = datetime.strptime(clean_str, fmt).replace(tzinfo=timezone.utc)
            if fmt == "%Y-%m":
                return dt, dt.strftime("%Y-%m")
            return dt, dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return min_date, clean_str


def load_csv_rows(filepath: str) -> list[dict]:
    """Loads CSV rows cleanly using Python's standard csv.DictReader."""
    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = [row for row in reader if row]
                if rows:
                    return rows
        except Exception:
            continue
    return []


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: {CSV_PATH} not found!")
        return

    rows = load_csv_rows(CSV_PATH)

    title_keys = ["Name", "Activity Name", "Activity Title", "Course Name", "Title"]
    type_keys = ["Authority", "Type", "Activity Type", "Category"]
    date_keys = ["Finished On", "Started On", "Completion Date", "Completed Date", "Date"]
    duration_keys = ["Duration", "Hours", "Time Spent"]

    parsed_data = []

    for r in rows:
        title = get_field(r, title_keys, default="Course")
        type_val = get_field(r, type_keys, default="Course").title()
        raw_date = get_field(r, date_keys, default="")
        dt, formatted_date = parse_and_clean_date(raw_date)
        duration = get_field(r, duration_keys, default="N/A")

        parsed_data.append({
            "title": title,
            "type": type_val,
            "dt": dt,
            "date_str": formatted_date,
            "duration": duration,
        })

    sorted_data = sorted(parsed_data, key=lambda x: x["dt"], reverse=True)

    formatted_rows = []
    for item in sorted_data:
        clean_title = item["title"].replace("|", "\\|")
        row_text = f"| {clean_title} | {item['type']} | {item['date_str']} | {item['duration']} |"
        formatted_rows.append((row_text, item["date_str"]))

    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    index_filename = f"{PLATFORM_PREFIX}-index.md"
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    index_raw = f"{RAW_BASE_DEFAULT}/{index_filename}"
    latest_chunk_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-{now_ym}-part-01.md"

    md = [
        "### AWS Skill Builder Summary",
        f"- **Total Completed Courses/Activities:** {len(sorted_data):,}\n",
        "### AWS Cloud Quest Status",
        f"- **Role:** {CLOUD_QUEST_STATS['Role']}",
        f"- **Builder Level:** {CLOUD_QUEST_STATS['Builder Level']} | **Reputation Level:** {CLOUD_QUEST_STATS['Reputation Level']}",
        f"- **Total Solutions Built:** {CLOUD_QUEST_STATS['Total Solutions Built']}",
        f"- **Pets Unlocked:** {CLOUD_QUEST_STATS['Pets Unlocked']} | **Vehicles Unlocked:** {CLOUD_QUEST_STATS['Vehicles Unlocked']}\n",
        "### Recent AWS Learning Activities",
        f"Showing latest 10 of {len(sorted_data):,} activities. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n",
    ]

    for item in sorted_data[:10]:
        md.append(f"- **{item['title']}** ({item['type']} | Earned: {item['date_str']})")

    generate_platform_archive(
        platform_prefix=PLATFORM_PREFIX,
        platform_name=PLATFORM_NAME,
        table_headers=["Activity / Course Title", "Type / Authority", "Date Earned", "Duration"],
        table_alignments=[":---", ":---", ":---:", ":---:"],
        formatted_rows=formatted_rows,
        readme_lines=md,
        marker_start=MARKER_START,
        marker_end=MARKER_END,
        archive_dir=ARCHIVE_DIR,
        readme_path=README_PATH,
    )


if __name__ == "__main__":
    main()
