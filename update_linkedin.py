import os
import sys
import csv
import re
import glob
from datetime import datetime

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "linkedin-certifications"
CERTIFICATIONS_CSV_PATH = "data/Certifications.csv"
RAW_BASE = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"

MARKER_START = "<!-- LINKEDIN_START -->"
MARKER_END = "<!-- LINKEDIN_END -->"

MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
}

def parse_linkedin_date(date_str):
    if not date_str or str(date_str).strip().lower() in ['null', 'none', '']:
        return "N/A"
    
    clean_str = str(date_str).strip().lower()
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', clean_str)
    if iso_match:
        return iso_match.group(1)
        
    match = re.search(r'([a-z]{3,})\s+(\d{4})', clean_str)
    if match:
        month_part = match.group(1)[:3]
        year_part = match.group(2)
        month_num = MONTH_MAP.get(month_part, "00")
        return f"{year_part}-{month_num}"
    
    return "N/A"

def clean_old_chunks():
    pattern = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

def parse_certifications_csv():
    if not os.path.exists(CERTIFICATIONS_CSV_PATH):
        return []

    certs = []
    current_year_month = "2026-07"

    with open(CERTIFICATIONS_CSV_PATH, mode='r', encoding='utf-8-sig') as f:
        content = f.read()
        if not content.strip():
            return []
            
        delimiter = '\t' if '\t' in content.splitlines()[0] else ','
        f.seek(0)
        
        reader = csv.DictReader(f, delimiter=delimiter)
        for idx, row in enumerate(reader):
            name = row.get('Name') or row.get('name')
            if not name:
                continue
                
            authority = row.get('Authority') or row.get('authority') or "Unknown Issuer"
            url = row.get('Url') or row.get('url') or ""
            license_num = row.get('License Number') or row.get('license number') or ""
            
            started = row.get('Started On') or row.get('started on')
            finished = row.get('Finished On') or row.get('finished on')
            
            issued_date = parse_linkedin_date(started)
            expiry_date = parse_linkedin_date(finished)
            
            if issued_date != "N/A" and issued_date > current_year_month:
                if expiry_date != "N/A" and expiry_date <= current_year_month:
                    issued_date, expiry_date = expiry_date, issued_date
                else:
                    expiry_date = issued_date
                    issued_date = current_year_month
            
            certs.append({
                "name": name.strip(),
                "authority": authority.strip(),
                "issued": issued_date,
                "url": url.strip(),
                "license": license_num.strip(),
                "original_order": idx
            })
            
    return certs

def main():
    certs = parse_certifications_csv()
    if not certs:
        sys.exit(1)

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    clean_old_chunks()

    total_certs = len(certs)
    certs.sort(key=lambda x: x["original_order"], reverse=True)
    certs.sort(key=lambda x: x.get("issued") if x.get("issued") != "N/A" else "0000-00", reverse=True)
    
    now_ym = datetime.now().strftime("%Y-%m")

    # 1. Monolithic Complete Archive
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    monolith_path = os.path.join(ARCHIVE_DIR, monolith_filename)

    archive_md = []
    archive_md.append("# Master LinkedIn Certifications History Log\n")
    archive_md.append(f"Historical record cataloging all {total_certs} verified external professional credentials.\n\n")
    archive_md.append("| Date Completed | Certification Title | Issuing Authority | Verification Reference |")
    archive_md.append("| :---: | :--- | :--- | :--- |")
    
    formatted_rows = []
    for c in certs:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "Verified Account Entry")
        row = f"| {c['issued']} | **{clean_name}** | {clean_auth} | {ref} |"
        formatted_rows.append((row, c['issued']))
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
        c_md.append("archive_platform: LinkedIn Certifications")
        c_md.append(f"chunk_part: {i} of {total_chunks}")
        c_md.append(f"date_range: {start_date} to {end_date}")
        c_md.append(f"total_entries: {len(chunk_rows)}")
        c_md.append(f"raw_url: {RAW_BASE}/{chunk_filename}")
        c_md.append("---\n")
        
        c_md.append(f"# LinkedIn Certifications — Part {i:02d}\n")
        c_md.append(f"> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n")
        c_md.append("| Date Completed | Certification Title | Issuing Authority | Verification Reference |")
        c_md.append("| :---: | :--- | :--- | :--- |")
        
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
    idx_md.append("# LinkedIn Certifications Archive Index\n")
    idx_md.append("This directory provides chunked, AI-readable historical records for LinkedIn certifications.\n")
    idx_md.append("## Archive Overview\n")
    idx_md.append(f"- **Total Certifications Archived:** {total_certs}")
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

    # 4. Update README.md
    md = []
    md.append("### LinkedIn Professional Certifications Summary")
    md.append("#### Progress Metrics")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total External Certifications Verified** | {total_certs:,} |")
    md.append("\n")
    
    latest_chunk_raw = chunk_meta[0]['raw_url'] if chunk_meta else f"{RAW_BASE}/{monolith_filename}"
    index_raw = f"{RAW_BASE}/{index_filename}"

    md.append("#### Recent Certifications")
    md.append(f"Showing latest 10 items. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n")
    md.append("| Date | Certification Title | Issuing Authority | Credentials Reference |")
    md.append("| :---: | :--- | :--- | :--- |")
    
    for c in certs[:10]:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "N/A")
        md.append(f"| *{c['issued']}* | **{clean_name}** | {clean_auth} | {ref} |")
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
