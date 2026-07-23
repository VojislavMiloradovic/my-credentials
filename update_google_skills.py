import json
import os
import re
import glob
import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "google-cloud-skills"
RAW_BASE = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"

INTERNAL_STATS = {
    "Course": 337,
    "Check": 1782,
    "Classroom": 0,
    "Game": 6,
    "Lab": 237,
    "Lesson": 4847
}

def to_iso_date(raw_date_str):
    if not raw_date_str:
        return "N/A"
    clean = re.sub(r'^Earned\s+', '', raw_date_str, flags=re.IGNORECASE)
    clean = re.sub(r'\s+[A-Z]{3,4}$', '', clean).strip()
    
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    for fmt in ("%b %Y", "%B %Y", "%Y-%m"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m")
        except ValueError:
            continue
            
    return clean

def parse_badge_text(raw_text):
    if not raw_text:
        return "Unknown Badge", "N/A"
    text = re.sub(r'\s+', ' ', raw_text).strip()
    match = re.search(r"^(.*?)(Earned\s+[A-Za-z]{3}\s+\d{1,2},\s+\d{4}.*)$", text)
    if match:
        title = match.group(1).strip()
        raw_date = match.group(2).strip()
        return title, to_iso_date(raw_date)
    return text, "N/A"

def clean_old_chunks():
    pattern = os.path.join(ARCHIVE_DIR, f"{PLATFORM_PREFIX}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass

def fetch_skills():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to load page: Status {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')
    
    total_points = "188,404"
    try:
        points_match = re.search(r'\b(\d{1,3}(?:[,\.]\d{3})+|\d{4,9})\s*(?:points|pts)\b', soup.get_text(), re.IGNORECASE)
        if points_match:
            raw_points = points_match.group(1).strip().replace(".", ",")
            if "," not in raw_points and raw_points.isdigit():
                total_points = f"{int(raw_points):,}"
            else:
                total_points = raw_points
    except Exception as e:
        print(f"Could not dynamically scrape points: {e}")

    badges = []
    badge_elements = soup.find_all("div", class_="profile-badge") or soup.find_all("div", class_="badge-card")
    
    if not badge_elements:
        badge_elements = [div for div in soup.find_all("div") if div.find("p") and ("earned" in div.get_text().lower() or "skill badge" in div.get_text().lower())]

    for elem in badge_elements:
        img_elem = elem.find("img")
        img_url = None
        if img_elem:
            img_url = img_elem.get("src") or img_elem.get("data-src") or img_elem.get("srcset")
            if img_url and "," in img_url:
                img_url = img_url.split(",")[0].strip().split(" ")[0]

        text_elem = elem.find("h3") or elem.find("h4") or elem.find("p") or elem
        raw_text = text_elem.get_text(" ", strip=True) if text_elem else ""
        
        if "earned" in raw_text.lower():
            title, date_earned = parse_badge_text(raw_text)
            if title:
                link_elem = elem if elem.name == "a" else elem.find("a")
                badge_url = URL
                if link_elem and link_elem.get("href"):
                    href = link_elem.get("href")
                    if href.startswith("/"):
                        badge_url = f"https://www.skills.google{href}"
                    elif href.startswith("http"):
                        badge_url = href

                badges.append({
                    "title": title,
                    "date_earned": date_earned,
                    "image_url": img_url,
                    "verification_url": badge_url
                })

    unique_badges = []
    seen = set()
    for b in badges:
        if b["title"].lower() not in seen:
            seen.add(b["title"].lower())
            unique_badges.append(b)

    unique_badges.sort(key=lambda x: x["date_earned"] or "0000-00-00", reverse=True)

    profile_data = {
        "profile_url": URL,
        "total_points": total_points,
        "internal_stats": INTERNAL_STATS,
        "total_badges": len(unique_badges),
        "badges": unique_badges
    }
    with open("google_skills.json", "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)

    update_readme_and_archive(unique_badges, total_points)

def update_readme_and_archive(badges, total_points):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    clean_old_chunks()
    
    now_ym = datetime.now().strftime("%Y-%m")

    # 1. Monolithic Complete File
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    monolith_path = os.path.join(ARCHIVE_DIR, monolith_filename)
    
    mono_md = "# Google Cloud Skills Boost — Full Credentials Archive\n\n"
    mono_md += f"**Public Profile:** [Verify Profile]({URL})  \n"
    mono_md += f"**Total Lifetime Points:** {total_points}  \n"
    mono_md += f"**Total Badges:** {len(badges)}\n\n"
    mono_md += "#### All Earned Badges\n"
    mono_md += "| Date Earned | Badge Title |\n|:---:|---|\n"
    
    formatted_rows = []
    for b in badges:
        row = f"| {b['date_earned']} | **{b['title']}** |"
        formatted_rows.append((row, b['date_earned']))
        mono_md += f"{row}\n"
        
    mono_md += f"\n\n[← Back to Index](./{PLATFORM_PREFIX}-index.md) | [← README](../README.md)\n"
    
    with open(monolith_path, "w", encoding="utf-8") as f:
        f.write(mono_md)

    # 2. Chunking Logic (~10 KB per chunk)
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
        c_md.append("archive_platform: Google Cloud Skills Boost")
        c_md.append(f"chunk_part: {i} of {total_chunks}")
        c_md.append(f"date_range: {start_date} to {end_date}")
        c_md.append(f"total_entries: {len(chunk_rows)}")
        c_md.append(f"raw_url: {RAW_BASE}/{chunk_filename}")
        c_md.append("---\n")
        
        c_md.append(f"# Google Cloud Skills — Part {i:02d}\n")
        c_md.append(f"> **Navigation:** Prev: {prev_link} | [Index](./{PLATFORM_PREFIX}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n")
        c_md.append("| Date Earned | Badge Title |")
        c_md.append("| :---: | :--- |")
        
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
    idx_md.append("# Google Cloud Skills Archive Index\n")
    idx_md.append("This directory provides chunked, AI-readable historical records for Google Cloud Skills Boost badges.\n")
    idx_md.append("## Archive Overview\n")
    idx_md.append(f"- **Total Badges Archived:** {len(badges)}")
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
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            readme_content = f.read()
    except FileNotFoundError:
        return

    badge_md = f"\n### Google Cloud Skills Boost ({len(badges)} Badges)\n\n"
    badge_md += f"**Public Profile:** [Verify Profile]({URL})  \n"
    badge_md += f"**Total Lifetime Points:** {total_points}\n\n"
    
    badge_md += "#### Platform Progress Summary\n"
    badge_md += "| Metric | Count |\n|---|---|\n"
    for metric, count in INTERNAL_STATS.items():
        badge_md += f"| **{metric}** | {count:,} |\n"
    badge_md += "\n"

    latest_chunk_raw = chunk_meta[0]['raw_url'] if chunk_meta else f"{RAW_BASE}/{monolith_filename}"
    index_raw = f"{RAW_BASE}/{index_filename}"

    if not badges:
        badge_md += "*No Google Skills badges detected dynamically yet (checking daily).*\n"
    else:
        badge_md += "#### Latest Earned Badges\n"
        badge_md += "| Date Earned | Badge Title |\n|:---:|---| \n"
        for b in badges[:10]:
            badge_md += f"| *{b['date_earned']}* | **{b['title']}** |\n"
        badge_md += "\n"
        badge_md += f"👉 **[View Platform Index](./archives/{index_filename})** ([Raw Index]({index_raw}) | [Part 01 Raw]({latest_chunk_raw}) | [Complete Monolith](./archives/{monolith_filename}))\n\n"

    start_tag = "<!-- GOOGLE_SKILLS_START -->"
    end_tag = "<!-- GOOGLE_SKILLS_END -->"
    
    if start_tag in readme_content and end_tag in readme_content:
        parts_before = readme_content.split(start_tag)[0]
        parts_after = readme_content.split(end_tag)[1]
        new_readme = f"{parts_before}{start_tag}{badge_md}{end_tag}{parts_after}"
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new_readme)

if __name__ == "__main__":
    fetch_skills()
