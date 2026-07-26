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
    """Case-insensitive, whitespace-resilient, and quote-safe column accessor."""
    norm_row = {}
    for k, v in row.items():
        if k is not None and v is not None:
            clean_k = str(k).strip(" \t\n\r\"'").lower()
            clean_v = str(v).strip(" \t\n\r\"'")
            if clean_v:
                norm_row[clean_k] = clean_v

    for key in possible_keys:
        target = key.strip().lower()
        val = norm_row.get(target)
        if val:
            return val

    for key in possible_keys:
        target = key.strip().lower()
        for k, v in norm_row.items():
            if target in k:
                return v

    return default


def parse_and_clean_date(raw_date_str: str) -> tuple[datetime, str]:
    """Parses raw date strings into a timezone-aware datetime and formatted string in a locale-independent manner."""
    min_date = datetime.min.replace(tzinfo=timezone.utc)
    if not raw_date_str or not isinstance(raw_date_str, str):
        return min_date, "N/A"

    clean_str = raw_date_str.split("T")[0].strip(" \t\n\r\"'")
    if not clean_str:
        return min_date, "N/A"

    # 1. Locale-independent month name check (e.g. "Feb 2026", "March 2026")
    month_year_match = re.match(r"^([a-zA-Z]+)\s+(\d{4})$", clean_str)
    if month_year_match:
        m_name, y_str = month_year_match.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            formatted = f"{y_str}-{m_num}"
            try:
                dt = datetime.strptime(f"{formatted}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return dt, formatted
            except ValueError:
                pass

    # 2. Standard numeric date formats (YYYY-MM-DD, MM/DD/YYYY, YYYY-MM)
    date_formats = [
        "%Y-%m-%d",
        "%Y-%m",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(clean_str, fmt).replace(tzinfo=timezone.utc)
            if fmt == "%Y-%m":
                return dt, dt.strftime("%Y-%m")
            return dt, dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 3. Regex fallback for YYYY-MM-DD or YYYY/MM/DD
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", clean_str)
    if match:
        y, m, d = match.groups()
        formatted = f"{y}-{int(m):02d}-{int(d):02d}"
        try:
            dt = datetime.strptime(formatted, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt, formatted
        except ValueError:
            pass

    return min_date, clean_str if clean_str else "N/A"


def load_csv_rows(filepath: str) -> list[dict]:
    """Fail-safe CSV loader that handles line endings, encodings, and delimiter detection."""
    content = ""
    for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if not content.strip():
        return []

    lines = [line for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return []

    header_line = lines[0]
    counts = {
        ",": header_line.count(","),
        "\t": header_line.count("\t"),
        ";": header_line.count(";"),
        "|": header_line.count("|"),
    }
    best_delim = max(counts, key=counts.get)
    delimiter = best_delim if counts[best_delim] > 0 else ","

    reader = csv.DictReader(lines, delimiter=delimiter)
    rows = list(reader)

    # Secondary check: If single-column key detected, attempt fallback splitting
    if rows and len(rows[0]) == 1:
        single_key = list(rows[0].keys())[0]
        for alt_delim in [",", "\t", ";", "|"]:
            if alt_delim in single_key and alt_delim != delimiter:
                alt_reader = csv.DictReader(lines, delimiter=alt_delim)
                alt_rows = list(alt_reader)
                if alt_rows and len(alt_rows[0]) > 1:
                    return alt_rows

    return rows


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: {CSV_PATH} not found!")
        return

    rows = load_csv_rows(CSV_PATH)

    title_keys = ["Name", "Activity Name", "Activity Title", "Course Name", "Title", "Transcript Item Name"]
    type_keys = ["Authority", "Type", "Activity Type", "Category", "Item Type"]
    date_keys = ["Finished On", "Started On", "Completion Date", "Completed Date", "Date"]
    duration_keys = ["Duration", "Duration (Hours)", "Hours", "Time Spent", "Length"]

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
