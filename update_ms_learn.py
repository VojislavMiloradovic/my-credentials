import os
import json
import re
import glob
from datetime import datetime

JSON_PATH = "data/microsoft-learn.json"
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "microsoft-learn"

RAW_BASE = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
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

def clean_old_chunks():
    pattern = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

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

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    clean_old_chunks()

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

    now_ym = datetime.now().strftime("%Y-%m")

    # 1. Monolithic Complete File
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    monolith_path = os.path.join(ARCHIVE_DIR, monolith_filename)
    
    mono_md = []
    mono_md.append("# Complete Microsoft Learn Achievements Archive\n")
    mono_md.append(f"This document contains a complete, chronological record of all {format_num(len(sorted_achievements))} achievements earned on Microsoft Learn.\n")
    mono_md.append("| Achievement Title | Category | Date Earned | Verification Link |")
    mono_md.append("| :--- | :--- | :--- | :--- |")

    formatted_rows = []
    for item in sorted_achievements:
        title = item.get("title", "Completed Module").replace("|", "\\|")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = format_verify_url(item.get("url", ""))
        verify_cell = f"[Verify]({verify_url})" if verify_url else "N/A"
        row = f"| {title} | {cat} | {date} | {verify_cell} |"
        formatted_rows.append((row, date))
        mono_md.append(row)

    mono_md.append(f"\n\n[← Back to Index](./{PLATFORM_PREFIX}-index.md) | [← README](../README.md)\n")
    with open(monolith_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mono_md))

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
        c_md.append("archive_platform: Microsoft Learn")
        c_md.append(f"chunk_part: {i} of {total_chunks}")
        c_md.append(f"date_range: {start_date} to {end_date}")
        c_md.append(f"total_entries: {len(chunk_rows)}")
        c_md.append(f"raw_url: {RAW_BASE}/{chunk_filename}")
        c_md.append("---\n")
        
        c_md.append(f"# Microsoft Learn Achievements — Part {i:02d}\n")
        c_md.append(f"> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n")
        c_md.append("| Achievement Title | Category | Date Earned | Verification Link |")
        c_md.append("| :--- | :--- | :--- | :--- |")
        
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
    idx_md.append("# Microsoft Learn Archive Index\n")
    idx_md.append("This directory provides chunked, AI-readable historical records for Microsoft Learn achievements. Large language models and AI scrapers can utilize raw links to consume precise date segments without exceeding context fetch limits.\n")
    idx_md.append("## Archive Overview\n")
    idx_md.append(f"- **Total Achievements Archived:** {format_num(len(sorted_achievements))}")
    idx_md.append(f"- **Monolithic File Size:** ~{mono_kb} KB (~{mono_tokens:,} tokens)")
    idx_md.append(f"- **Total Chunk Parts:** {total_chunks} chunk(s)\n")
    
    idx_md.append("### Monolithic Archive (Complete)\n")
    idx_md.append("| File Name | Size (KB) | Est. Tokens | Recommended For | Direct Raw URL |")
    idx_md.append("| :--- | :---: | :---: | :--- | :--- |")
    idx_md.append(f"| [`{monolith_filename}`](./{monolith_filename}) | {mono_kb} KB | ~{mono_tokens:,} | Large Context Windows (>100k tokens) | [Raw Link]({RAW_BASE}/{monolith_filename}) |\n")
    
    idx_md.append("### Chunked Archive Parts (~10 KB Slices)\n")
    idx_md.append("| Part | File Name | Date Range | Entries | Size (KB) | Est. Tokens | Direct Raw URL |")
    idx_md.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
    
    for cm in chunk_meta:
        idx_md.append(f"| Part {cm['part']:02d} | [`{cm['filename']}`](./{cm['filename']}) | `{cm['date_range']}` | {cm['entries']} | {cm['size_kb']} KB | ~{cm['tokens']} | [Raw URL]({cm['raw_url']}) |")

    idx_md.append("\n\n[← Back to Main README](../README.md)\n")
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(idx_md))

    # 4. Update Main README.md
    md = []
    md.append("### Microsoft Learn Summary")
    md.append(f"- **Total Experience Points (XP):** {format_num(total_xp)}")
    md.append(f"- **Current Learning Level:** Level {current_level}")
    md.append(f"- **Badges Earned (Profile):** {format_num(badges_count)}")
    md.append(f"- **Trophies Earned (Profile):** {format_num(trophies_count)}")
    md.append(f"- **Completed Learning Paths (Active Tracker):** {format_num(len(learning_paths))}")
    md.append(f"- **Completed Modules (Active Tracker):** {format_num(len(modules))}")
    md.append(f"- **Completed Individual Units:** {format_num(len(completed_units))}\n")

    if verifiable_list:
        md.append("### Verifiable Applied Skills & Credentials")
        md.extend(verifiable_list)
        md.append("")

    md.append("### Recent Achievements & Completed Badges")
    latest_chunk_raw = chunk_meta[0]['raw_url'] if chunk_meta else f"{RAW_BASE}/{monolith_filename}"
    index_raw = f"{RAW_BASE}/{index_filename}"
    
    md.append(f"Showing latest 10 of {format_num(len(sorted_achievements))} achievements. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n")
    
    for item in sorted_achievements[:10]:
        title = item.get("title", "Completed Module")
        cat = item.get("category", "module").title()
        date = clean_iso_date(item.get("grantedOn", ""))
        verify_url = format_verify_url(item.get("url", ""))
        verify_str = f" | [Verify Credential]({verify_url})" if verify_url else ""
        md.append(f"- **{title}** ({cat} | Earned: {date}{verify_str})")

    if not os.path.exists(README_PATH):
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(f"{MARKER_START}\n{MARKER_END}\n")

    with open(README_PATH, "r", encoding="utf-8") as f:
        readme_content = f.read()

    if MARKER_START not in readme_content or MARKER_END not in readme_content:
        readme_content += f"\n\n{MARKER_START}\n{MARKER_END}\n"

    split_start = readme_content.split(MARKER_START)
    split_end = split_start[1].split(MARKER_END)
    
    updated_readme = (
        split_start[0] + 
        MARKER_START + "\n" + 
        "\n".join(md) + "\n" + 
        MARKER_END + 
        split_end[1]
    )

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated_readme)

if __name__ == "__main__":
    main()
