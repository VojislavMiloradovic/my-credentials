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


def clean_iso_date(raw_date_str: str) -> str:
    if not raw_date_str or not isinstance(raw_date_str, str):
        return "N/A"
    clean = raw_date_str.split("T")[0].strip()
    match = re.search(r"^\d{4}-\d{2}(-\d{2})?", clean)
    if match:
        return match.group(0)
    return clean if clean else "N/A"


def parse_date(row: dict) -> datetime:
    min_date = datetime.min.replace(tzinfo=timezone.utc)
    date_str = row.get("Completion Date") or row.get("Completed On") or row.get("Date", "")
    if not date_str:
        return min_date
    try:
        clean_str = date_str.split("T")[0].strip()
        dt = datetime.strptime(clean_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return min_date


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: {CSV_PATH} not found!")
        return

    rows = []
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    sorted_rows = sorted(rows, key=parse_date, reverse=True)

    formatted_rows = []
    for r in sorted_rows:
        title = (r.get("Activity Name") or r.get("Title") or "AWS Course").replace("|", "\\|")
        type_val = (r.get("Type") or r.get("Activity Type") or "Course").strip().title()
        date = clean_iso_date(r.get("Completion Date") or r.get("Completed On") or r.get("Date", ""))
        duration = (r.get("Duration") or r.get("Hours") or "N/A").strip()

        row_text = f"| {title} | {type_val} | {date} | {duration} |"
        formatted_rows.append((row_text, date))

    # Construct README summary block
    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    index_filename = f"{PLATFORM_PREFIX}-index.md"
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    index_raw = f"{RAW_BASE_DEFAULT}/{index_filename}"
    latest_chunk_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-{now_ym}-part-01.md"

    md = [
        "### AWS Skill Builder Summary",
        f"- **Total Completed Courses/Activities:** {len(sorted_rows):,}\n",
        "### Recent AWS Learning Activities",
        f"Showing latest 10 of {len(sorted_rows):,} activities. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n",
    ]

    for r in sorted_rows[:10]:
        title = r.get("Activity Name") or r.get("Title") or "AWS Course"
        type_val = (r.get("Type") or r.get("Activity Type") or "Course").strip().title()
        date = clean_iso_date(r.get("Completion Date") or r.get("Completed On") or r.get("Date", ""))
        md.append(f"- **{title}** ({type_val} | Earned: {date})")

    # Delegate archiving and README injection to archiver module
    generate_platform_archive(
        platform_prefix=PLATFORM_PREFIX,
        platform_name=PLATFORM_NAME,
        table_headers=["Activity / Course Title", "Type", "Date Earned", "Duration"],
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
