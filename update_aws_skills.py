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


def norm_key(s: str) -> str:
    """Normalizes string keys by stripping all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_and_clean_date(raw_date_str: str) -> tuple[datetime, str]:
    """Parses raw date strings into a timezone-aware datetime and formatted string in a locale-independent manner."""
    min_date = datetime.min.replace(tzinfo=timezone.utc)
    if not raw_date_str or not isinstance(raw_date_str, str):
        return min_date, "N/A"

    clean_str = raw_date_str.split("T")[0].strip(" \t\n\r\"'")
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

    # 3. Regex fallback
    date_match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", clean_str)
    if date_match:
        y, m, d = date_match.groups()
        formatted = f"{y}-{int(m):02d}-{int(d):02d}"
        try:
            dt = datetime.strptime(formatted, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt, formatted
        except ValueError:
            pass

    return min_date, clean_str if clean_str else "N/A"


def read_file_safely(filepath: str) -> str:
    """Reads file content handling UTF-8 BOM, UTF-16, and various encodings safely."""
    with open(filepath, "rb") as f:
        raw = f.read()

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        try:
            return raw.decode("utf-16", errors="replace")
        except Exception:
            pass

    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

    return raw.decode("latin-1", errors="replace")


def load_csv_rows(filepath: str) -> list[dict]:
    """Fail-safe CSV loader that creates dictionary headers and positional backup keys."""
    content = read_file_safely(filepath)
    lines = [line.strip() for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return []

    # Find the line that actually looks like a CSV header
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        line_lower = line.lower()
        if "name" in line_lower or "title" in line_lower or "authority" in line_lower or "started" in line_lower:
            header_idx = i
            break

    data_lines = lines[header_idx:]
    header_line = lines[header_idx]

    counts = {
        ",": header_line.count(","),
        "\t": header_line.count("\t"),
        ";": header_line.count(";"),
    }
    delimiter = max(counts, key=counts.get) if max(counts.values()) > 0 else ","

    reader = csv.reader(data_lines, delimiter=delimiter)
    raw_rows = list(reader)
    if not raw_rows:
        return []

    headers = [h.strip(" \t\n\r\"'\ufeff") for h in raw_rows[0]]
    rows = []

    for row in raw_rows[1:]:
        if not row or not any(field.strip() for field in row):
            continue

        row_dict = {}
        for col_i, val in enumerate(row):
            clean_val = val.strip(" \t\n\r\"'")
            if col_i < len(headers) and headers[col_i]:
                row_dict[headers[col_i]] = clean_val
            # Store positional backup key
            row_dict[f"__col_{col_i}"] = clean_val

        rows.append(row_dict)

    return rows


def extract_row_fields(row: dict) -> tuple[str, str, str, str]:
    """Extracts title, authority/type, date, and duration with header and positional fallbacks."""
    # 1. Title Extraction
    title = ""
    for k, v in row.items():
        if k.startswith("__col_") or not v:
            continue
        nk = norm_key(k)
        if nk in ["name", "title", "coursename", "activityname", "transcriptitemname", "activitytitle"]:
            title = v
            break

    if not title:
        for k, v in row.items():
            if k.startswith("__col_") or not v:
                continue
            nk = norm_key(k)
            if "name" in nk or "title" in nk or "course" in nk:
                title = v
                break

    # Positional Fallback: Column 0 is Title
    if not title:
        title = row.get("__col_0", "Course")

    # 2. Type / Authority Extraction
    type_val = ""
    for k, v in row.items():
        if k.startswith("__col_") or not v:
            continue
        nk = norm_key(k)
        if nk in ["authority", "type", "activitytype", "category", "itemtype", "provider", "issuer"]:
            type_val = v
            break

    if not type_val:
        for k, v in row.items():
            if k.startswith("__col_") or not v:
                continue
            nk = norm_key(k)
            if "authority" in nk or "type" in nk or "category" in nk or "provider" in nk or "issuer" in nk:
                type_val = v
                break

    # Positional Fallback: Column 2 is Authority / Type
    if not type_val:
        type_val = row.get("__col_2", "Course")

    # 3. Date Extraction
    raw_date = ""
    date_candidates = []
    for k, v in row.items():
        if k.startswith("__col_") or not v:
            continue
        nk = norm_key(k)
        if "started" in nk or "completion" in nk or "finished" in nk or "date" in nk or "earned" in nk:
            date_candidates.append((nk, v))

    for pattern in ["started", "completion", "earned", "finished", "date"]:
        for nk, v in date_candidates:
            if pattern in nk and v:
                raw_date = v
                break
        if raw_date:
            break

    # Positional Fallback: Column 3 (Started On) or Column 4 (Finished On)
    if not raw_date:
        raw_date = row.get("__col_3", "") or row.get("__col_4", "")

    # 4. Duration Extraction
    duration = ""
    for k, v in row.items():
        if k.startswith("__col_") or not v:
            continue
        nk = norm_key(k)
        if "duration" in nk or "hours" in nk or "time" in nk or "length" in nk:
            duration = v
            break

    if not duration:
        duration = row.get("__col_5", "N/A") if len(row) > 5 and not row.get("__col_5", "").isalnum() else "N/A"

    return title, type_val.title(), raw_date, duration


def main():
    if not os.path.exists(CSV_PATH):
        print(f"❌ Error: {CSV_PATH} not found!")
        return

    rows = load_csv_rows(CSV_PATH)
    parsed_data = []

    for r in rows:
        title, type_val, raw_date, duration = extract_row_fields(r)
        dt, formatted_date = parse_and_clean_date(raw_date)

        parsed_data.append({
            "title": title,
            "type": type_val if type_val else "Course",
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
