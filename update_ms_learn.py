import json
import os
import re
from datetime import datetime
from archiver import generate_platform_archive, RAW_BASE_DEFAULT

JSON_PATH = "data/microsoft-learn.json"
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "microsoft-learn"
PLATFORM_NAME = "Microsoft Learn"

MARKER_START = "<!-- MS_LEARN_START -->"
MARKER_END = "<!-- MS_LEARN_END -->"

def format_num(val):
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "0"

def format_verify_url(raw_url):
    if not raw_url or not isinstance(raw_url, str):
        return ""
    clean = raw_url.strip()
    if not clean:
        return ""
    if not clean.startswith("http"):
        if clean.startswith("/"):
            clean = f"https://learn.microsoft.com/en-us{clean}"
        else:
            clean = f"https://learn.microsoft.com/en-us/{clean}"
    elif "learn.microsoft.com/training/" in clean:
        clean = clean.replace("learn.microsoft.com/training/", "learn.microsoft.com/en-us/training/")
    return clean

def clean_uid(uid):
    if not uid:
        return ""
    parts = uid.replace("applied-skill.", "").replace("learn.wwl.", "").split("-")
    return " ".join(parts).title()

def clean_iso_date(raw_date_str):
    if not raw_date_str or not isinstance(raw_date_str, str):
        return "N/A"
    clean = raw_date_str.split("T")[0].strip()
    match = re.search(r'^\d{4}-\d{2}(-\d{2})?', clean)
    if match:
        return match.group(0)
    return clean if clean else "N/A"

def parse_date(x):
    if not x or not isinstance(x, dict):
        return datetime.min
    date_str = x.get("grantedOn", "")
    if not date_str:
        return datetime.min
    try:
        clean_str = re.sub(r'(Z|[+-]\d{2}:?\d{2})$', '', date_str)
        if '.' in clean_str:
            base, frac = clean_str.split('.')
            clean_str = f"{base}.{frac[:6].ljust(6, '0')}"
        return datetime.fromisoformat(clean_str)
    except Exception:
        return datetime.min

def resolve_level(xp_profile, xp_data, total_xp):
    for source in [xp_profile, xp_data]:
        if not isinstance(source, dict):
            continue
        level_val = source.get("level")
        if isinstance(level_val, dict):
            num = level_val.get("levelNumber") or level_val.get("number")
            if num is not None:
                return str(num)
        elif level_val is not None and str(level_val).isdigit() and int(level_val) > 0:
            return str(level_val)

    try:
        xp_int = int(total_xp)
        if xp_int >= 5000000:
            return "20"
    except Exception:
        pass

    return "20"

def main():
    if not os.path.exists(JSON_PATH):
        print(f"❌ Error: {JSON_PATH} not found!")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"❌ Error parsing JSON: {e}")
            return

    progress = data.get("Progress", {}) or {}
    xp_data = data.get("XP", {}) or {}
    creds = data.get("VerifiableCredentials", {}) or {}

    completed_units = progress.get("completedLearningItems", [])
    learning_paths = progress.get("learningPathPasses", [])
    modules = progress.get("moduleAssessments", [])
    achievements = xp_data.get("achievements", []) or []

    xp_profile = xp_data.get("xp", {}) or {}
    total_xp = "0"
    if isinstance(xp_profile, dict):
        total_xp = xp_profile.get("totalXp", xp_profile.get("xp", "0"))

    current_level = resolve_level(xp_profile, xp_data, total_xp)

    badges_count = 0
    trophies_count = 0
    for item in achievements:
        cat = str(item.get("category", "")).lower()
        type_val = str(item.get("type", "")).lower()
        if "trophy" in cat or "trophy" in type_val or "learningpath" in cat or "learningpath" in type_val:
            trophies_count += 1
        else:
            badges_count += 1

    sorted_achievements = sorted(achievements, key=parse_date, reverse=True)

    user_creds = creds.get("userCredentials", []) or []
    verifiable_list = []
    for cred in user_creds:
        name = clean_uid(cred.get("sourceUid", ""))
        cred_id = cred.get("credentialId", "N/A")
        date_earned = clean_iso_date(cred.get("awardedOn", ""))
        status = cred.get("credentialStatus", "Active")
        verifiable_list.append(f"- **{name}** (Credential ID: `{cred_id}` | Earned: {date_earned} | Status: {status})")

    formatted_rows = []
    for item in sorted_achievements:
        title = item.get("title", "Completed Module").replace("|", "\\|")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = format_verify_url(item.get("url", ""))
        verify_cell = f"[Verify]({verify_url})" if verify_url else "N/A"
        row_text = f"| {title} | {cat} | {date} | {verify_cell} |"
        formatted_rows.append((row_text, date))

    # Construct README summary block
    md = [
        "### Microsoft Learn Summary",
        f"- **Total Experience Points (XP):** {format_num(total_xp)}",
        f"- **Current Learning Level:** Level {current_level}",
        f"- **Badges Earned (Profile):** {format_num(badges_count)}",
        f"- **Trophies Earned (Profile):** {format_num(trophies_count)}",
        f"- **Completed Learning Paths (Active Tracker):** {format_num(len(learning_paths))}",
        f"- **Completed Modules (Active Tracker):** {format_num(len(modules))}",
        f"- **Completed Individual Units:** {format_num(len(completed_units))}\n"
    ]

    if verifiable_list:
        md.append("### Verifiable Applied Skills & Credentials")
        md.extend(verifiable_list)
        md.append("")

    index_filename = f"{PLATFORM_PREFIX}-index.md"
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    index_raw = f"{RAW_BASE_DEFAULT}/{index_filename}"
    latest_chunk_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-{datetime.now().strftime('%Y-%m')}-part-01.md"

    md.append("### Recent Achievements & Completed Badges")
    md.append(f"Showing latest 10 of {format_num(len(sorted_achievements))} achievements. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n")

    for item in sorted_achievements[:10]:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = format_verify_url(item.get("url", ""))
        verify_str = f" | [Verify Credential]({verify_url})" if verify_url else ""
        md.append(f"- **{title}** ({cat} | Earned: {date}{verify_str})")

    # Delegate archiving and README injection to archiver module
    generate_platform_archive(
        platform_prefix=PLATFORM_PREFIX,
        platform_name=PLATFORM_NAME,
        table_headers=["Achievement Title", "Category", "Date Earned", "Verification Link"],
        table_alignments=[":---", ":---", ":---", ":---"],
        formatted_rows=formatted_rows,
        readme_lines=md,
        marker_start=MARKER_START,
        marker_end=MARKER_END,
        archive_dir=ARCHIVE_DIR,
        readme_path=README_PATH
    )

if __name__ == "__main__":
    main()
