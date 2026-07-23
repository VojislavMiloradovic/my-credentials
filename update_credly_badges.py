import os
import time
import re
import glob
import requests
from datetime import datetime

USERNAME = "vojislavmiloradovic"
USER_ID = "752aee40-7358-4ade-9a49-81e8b6f49225"
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "credly-badges"
RAW_BASE = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"

MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"

def normalize_iso_date(raw_date):
    if not raw_date or raw_date == "N/A":
        return "N/A"
    clean = str(raw_date).split("T")[0].strip()
    match = re.search(r'^\d{4}-\d{2}(-\d{2})?', clean)
    if match:
        return match.group(0)
    return clean

def clean_old_chunks():
    pattern = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

def fetch_paginated_data(url_template, headers, page_size=48):
    all_items = []
    page = 1
    total_pages = 1
    
    while page <= total_pages:
        url = url_template.format(page=page, page_size=page_size)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception:
            break

        page_items = data.get("data", [])
        if not page_items:
            break

        all_items.extend(page_items)
        metadata = data.get("metadata", {})
        if "total_pages" in metadata:
            total_pages = metadata["total_pages"]
        elif len(page_items) < page_size:
            total_pages = page
        else:
            total_pages = max(total_pages, page + 1)
        
        page += 1
        time.sleep(0.5)
        
    return all_items

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    clean_old_chunks()

    native_url_template = "https://www.credly.com/users/" + USERNAME + "/badges.json?page={page}"
    native_raw = fetch_paginated_data(native_url_template, headers)

    external_url_template = "https://www.credly.com/api/v1/users/" + USER_ID + "/external_badges/open_badges/public?page={page}&page_size={page_size}"
    external_raw = fetch_paginated_data(external_url_template, headers)

    badges = []
    all_skills_set = set()

    for item in native_raw:
        badge_id = item.get("id")
        issued_at = normalize_iso_date(item.get("issued_at_date") or item.get("issued_at", "N/A"))
        
        template = item.get("badge_template", {})
        name = template.get("name", "Unknown Badge")
        
        raw_skills = template.get("skills", [])
        badge_skills = []
        for s in raw_skills:
            skill_name = s.get("name") if isinstance(s, dict) else str(s)
            if skill_name:
                badge_skills.append(skill_name)
                all_skills_set.add(skill_name)
        
        issuer = template.get("issuer", {})
        issuer_name = issuer.get("summary") or "Verified Issuer"
        verify_url = f"https://www.credly.com/badges/{badge_id}"

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "type": "Credly Verified",
            "skills": badge_skills
        })

    for item in external_raw:
        ext = item.get("external_badge", {})
        name = ext.get("badge_name") or item.get("name") or "Unknown Certification"
        issuer_name = ext.get("issuer_name") or item.get("issuer") or "Third-Party Issuer"
        issued_at = normalize_iso_date(ext.get("issued_at_date") or item.get("issued_at_date") or "N/A")

        verify_url = ext.get("badge_url") or item.get("verification_url") or f"https://www.credly.com/users/{USERNAME}"

        raw_skills = item.get("skills", [])
        badge_skills = []
        if isinstance(raw_skills, list):
            for s in raw_skills:
                skill_name = s.get("name") if isinstance(s, dict) else str(s)
                if skill_name:
                    badge_skills.append(skill_name)
                    all_skills_set.add(skill_name)

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "type": "External/Imported",
            "skills": badge_skills
        })

    badges.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)

    total_badges = len(badges)
    unique_skills = sorted(list(all_skills_set))
    total_skills = len(unique_skills)
    native_count = sum(1 for b in badges if b["type"] == "Credly Verified")
    external_count = sum(1 for b in badges if b["type"] == "External/Imported")

    now_ym = datetime.now().strftime("%Y-%m")

    # 1. Monolithic Complete File
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    monolith_path = os.path.join(ARCHIVE_DIR, monolith_filename)

    archive_md = []
    archive_md.append("# Complete Credly Badges & Mapped Skills Archive\n")
    archive_md.append(f"This document represents a unified, verifiable list of all {total_badges} digital credentials ({native_count} native, {external_count} external) and {total_skills} mapped professional skills parsed from my [public Credly profile](https://www.credly.com/users/{USERNAME}).\n\n")
    
    archive_md.append("## Mapped Professional Skills\n")
    archive_md.append(", ".join([f"`{skill}`" for skill in unique_skills]))
    archive_md.append("\n\n---\n\n")

    archive_md.append("## Verified Credentials Archive\n")
    archive_md.append("| Date Earned | Credential Title | Verified Issuer | Type | Verification Link |\n|:---:|---|---|:---:|:---:|\n")
    
    formatted_rows = []
    for b in badges:
        clean_name = b['name'].replace("|", "\\|")
        row = f"| {b['date']} | **{clean_name}** | {b['issuer']} | `{b['type']}` | [Verify]({b['verify']}) |\n"
        formatted_rows.append((row, b['date']))
        archive_md.append(row)
    
    archive_md.append(f"\n\n[← Back to Index](./{PLATFORM_PREFIX}-index.md) | [← README](../README.md)\n")
    with open(monolith_path, "w", encoding="utf-8") as f:
        f.write("".join(archive_md))

    # 2. Chunking Logic (~10 KB limit per file)
    chunks = []
    current_chunk_rows = []
    current_chunk_bytes = 0
    MAX_BYTES = 9500

    for row_text, row_date in formatted_rows:
        row_len = len(row_text.encode("utf-8"))
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
        c_md.append(f"archive_platform: Credly Verified Credentials")
        c_md.append(f"chunk_part: {i} of {total_chunks}")
        c_md.append(f"date_range: {start_date} to {end_date}")
        c_md.append(f"total_entries: {len(chunk_rows)}")
        c_md.append(f"raw_url: {RAW_BASE}/{chunk_filename}")
        c_md.append("---\n")
        
        c_md.append(f"# Credly Verified Badges — Part {i:02d}\n")
        c_md.append(f"> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n")
        c_md.append("| Date Earned | Credential Title | Verified Issuer | Type | Verification Link |")
        c_md.append("| :---: | :--- | :--- | :---: | :---: |")
        
        for r_text, _ in chunk_rows:
            c_md.append(r_text.strip())
            
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
    idx_md.append(f"# Credly Badges & Mapped Skills Index\n")
    idx_md.append(f"This directory provides chunked, AI-readable historical records for Credly badges and mapped skills.\n")
    idx_md.append(f"## Archive Overview\n")
    idx_md.append(f"- **Total Credentials Archived:** {total_badges} ({native_count} Credly Verified, {external_count} External/Imported)")
    idx_md.append(f"- **Total Mapped Skills:** {total_skills}")
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
    readme_md = []
    readme_md.append("### Credly Verified Credentials\n")
    readme_md.append(f"**Public Profile:** [Verify Credly Profile](https://www.credly.com/users/{USERNAME})  \n")
    readme_md.append(f"**Total Portfolio Credentials:** {total_badges} ({native_count} Credly Verified, {external_count} External/Imported)  \n")
    readme_md.append(f"**Total Verified Skills Mapped:** {total_skills}\n\n")
    
    readme_md.append("#### Latest Earned Credentials\n")
    readme_md.append("| Date Earned | Credential Name | Issuer | Verification Type |\n|:---:|---|---|:---:|\n")
    for b in badges[:10]:
        readme_md.append(f"| *{b['date']}* | **{b['name']}** | {b['issuer']} | `{b['type']}` |\n")
    
    latest_chunk_raw = chunk_meta[0]['raw_url'] if chunk_meta else f"{RAW_BASE}/{monolith_filename}"
    index_raw = f"{RAW_BASE}/{index_filename}"
    
    readme_md.append(f"\n👉 **[View Platform Index](./archives/{index_filename})** ([Raw Index]({index_raw}) | [Part 01 Raw]({latest_chunk_raw}) | [Complete Monolith](./archives/{monolith_filename}))\n\n")

    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        if MARKER_START in content and MARKER_END in content:
            before = content.split(MARKER_START)[0]
            after = content.split(MARKER_END)[1]
            new_content = f"{before}{MARKER_START}\n" + "".join(readme_md) + f"{MARKER_END}{after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)

if __name__ == "__main__":
    main()
