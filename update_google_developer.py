import os
import sys
import re
import json
import requests
from datetime import datetime, timezone
from urllib.parse import unquote

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"
LEARNINGS_TXT_PATH = "data/google_learnings.txt"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

SERBIAN_MONTHS = {
    'јан': '01', 'јануар': '01', 'јануара': '01',
    'феб': '02', 'фебруар': '02', 'фебруара': '02',
    'мар': '03', 'март': '03', 'марта': '03',
    'апр': '04', 'април': '04', 'априла': '04',
    'мај': '05', 'маја': '05',
    'јун': '06', 'јуна': '06',
    'јул': '07', 'јула': '07',
    'авг': '08', 'август': '08', 'августа': '08',
    'сеп': '09', 'септембар': '09', 'септембара': '09',
    'окт': '10', 'октобар': '10', 'октобара': '10',
    'нов': '11', 'новембар': '11', 'новембара': '11',
    'дец': '12', 'децембар': '12', 'децембара': '12'
}

def parse_local_learnings_txt():
    if not os.path.exists(LEARNINGS_TXT_PATH):
        return []
    
    with open(LEARNINGS_TXT_PATH, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        
    learnings = []
    i = 0
    while i < len(lines):
        line = lines[i]
        date_match = re.match(r'^(\d+)\.\s+([^\s\d]+)\s+(\d{4})\.?$', line)
        if date_match and i > 0:
            day = date_match.group(1).zfill(2)
            month_str = date_match.group(2).lower().replace('.', '')
            year = date_match.group(3)
            
            month_num = "00"
            for k, v in SERBIAN_MONTHS.items():
                if month_str.startswith(k):
                    month_num = v
                    break
                    
            iso_date = f"{year}-{month_num}-{day}"
            
            title = lines[i-1]
            if title in ["Учење", "check_circle_outline You have this badge!"] and i > 1:
                title = lines[i-2]
                
            if title not in ["Учење", "check_circle_outline You have this badge!"] and not title.startswith("http"):
                if not any(l['title'] == title for l in learnings):
                    learnings.append({
                        "title": title.strip(),
                        "date": iso_date,
                        "description": "Verified Google Developer granular learning activity module milestone."
                    })
        i += 1
    return learnings

def analyze_badge_list(lst, parsed_badges):
    strings = []
    numbers = []
    
    def walk(element):
        if isinstance(element, str):
            strings.append(element)
            if element.isdigit():
                numbers.append(float(element))
        elif isinstance(element, (int, float)):
            numbers.append(element)
        elif isinstance(element, list):
            for x in element:
                walk(x)
        elif isinstance(element, dict):
            for x in element.values():
                walk(x)
                
    walk(lst)
    
    award_strs = [s for s in strings if "/awards/" in s]
    if not award_strs:
        return False
        
    epoch = None
    for num in numbers:
        if 946684800 <= num <= 2500000000:
            epoch = num
            break
        elif 946684800000 <= num <= 2500000000000:
            epoch = num / 1000.0
            break
            
    date_str = "N/A"
    if epoch:
        try:
            date_str = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d')
        except Exception:
            pass
            
    for award_str in award_strs:
        parts = award_str.split("/awards/")
        if len(parts) > 1:
            badge_path = unquote(parts[1])
            slug = badge_path.split("/")[-1].split("?")[0]
            
            title = slug.replace("-", " ").replace("_", " ").title()
            title = title.replace("Gdg", "GDG").replace("Gcp", "GCP").replace("Aws", "AWS")
            
            category = "Community" if "community" in badge_path else "Learning Pathway"
            description = f"Official Google Developer platform achievement ({category}: {slug.replace('-', ' ')})."
            
            existing = next((b for b in parsed_badges if b['title'] == title), None)
            if existing:
                if existing['date'] == "N/A" and date_str != "N/A":
                    existing['date'] = date_str
            else:
                parsed_badges.append({
                    "title": title,
                    "description": description,
                    "date": date_str
                })
    return True

def find_badges_in_matrix(data, parsed_badges):
    if isinstance(data, list):
        analyze_badge_list(data, parsed_badges)
        for item in data:
            find_badges_in_matrix(item, parsed_badges)
    elif isinstance(data, dict):
        for val in data.values():
            find_badges_in_matrix(val, parsed_badges)

def fetch_gdev_badges_rpc():
    url = "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute"
    params = {
        "rpcids": "gQeJTc,RwSpuf",
        "source-path": "/u/vojislavmiloradovic",
        "bl": "boq_gdp-builders-ui_20260713.05_p0",
        "f.sid": "8705607390718843222",
        "hl": "en",
        "_reqid": "252198",
        "rt": "c"
    }
    
    profile_id = "110772055890077594470"
    f_req_structure = [[
        ["gQeJTc", f"[\"{profile_id}\"]", None, "3"],
        ["RwSpuf", f"[\"{profile_id}\"]", None, "4"]
    ]]
    
    payload = {
        "f.req": json.dumps(f_req_structure),
        "at": "AFAd0eBgurpIT_evlsPSzRjypGkH:1784464194335"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "*/*",
        "Origin": "https://developers.google.com",
        "Referer": "https://developers.google.com/profile/u/vojislavmiloradovic"
    }
    
    try:
        response = requests.post(url, params=params, data=payload, headers=headers, timeout=15)
        if response.status_code != 200:
            return None
            
        raw_text = response.text
        parsed_badges = []
        
        for line in raw_text.splitlines():
            if "gQeJTc" in line or "RwSpuf" in line:
                clean_line = re.sub(r'^\d+', '', line).strip()
                try:
                    outer_data = json.loads(clean_line)
                    for chunk in outer_data:
                        if isinstance(chunk, list):
                            for element in chunk:
                                if isinstance(element, str) and (element.startswith("[") or element.startswith("{")):
                                    try:
                                        badge_matrix = json.loads(element)
                                        find_badges_in_matrix(badge_matrix, parsed_badges)
                                    except Exception:
                                        pass
                except Exception:
                    continue
        return parsed_badges
    except Exception:
        return None

def main():
    public_badges = fetch_gdev_badges_rpc()
    if not public_badges:
        sys.exit(1)
        
    total_public = len(public_badges)
    public_badges.sort(key=lambda x: x.get("date", "0000-00-00") if x.get("date") != "N/A" else "0000-00-00", reverse=True)
    
    detailed_learnings = parse_local_learnings_txt()
    total_detailed = len(detailed_learnings)
    detailed_learnings.sort(key=lambda x: x.get("date", "0000-00-00"), reverse=True)
    
    combined_feed = []
    combined_feed.extend(public_badges)
    for dl in detailed_learnings:
        if not any(b['title'] == dl['title'] for b in combined_feed):
            combined_feed.append(dl)
    combined_feed.sort(key=lambda x: x.get("date", "0000-00-00") if x.get("date") != "N/A" else "0000-00-00", reverse=True)

    md = []
    md.append("### Google Developer Profile Summary")
    md.append("**Public Profile:** [Verify Developer Profile](https://g.dev/vojislavmiloradovic)  \n")
    
    md.append("#### Platform Progress")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total Milestones & Milestone Badges** | {total_public:,} |")
    if total_detailed > 0:
        md.append(f"| **Total Codelabs & Learning Activities** | {total_detailed:,} |")
    md.append("\n")

    md.append("#### Latest Achievements")
    md.append("Showing the latest 10 merged activities. View complete historical logs in [Google Developer archive](./archives/google-developer.md).\n")
    md.append("| Date Earned | Title | Description |")
    md.append("| :---: | :--- | :--- |")
    
    for badge in combined_feed[:10]:
        clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
        clean_title = badge['title'].replace("|", "\\|")
        md.append(f"| *{badge['date']}* | **{clean_title}** | {clean_desc} |")
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

    archive_md = []
    archive_md.append("# Complete Google Developer Badges Archive\n")
    archive_md.append(f"Historical verified record tracking all achievements.\n\n")
    
    archive_md.append(f"## Milestone & Pathway Badges ({total_public})\n")
    archive_md.append("| Date Earned | Badge Title | Description |")
    archive_md.append("| :---: | :--- | :--- |")
    for badge in public_badges:
        clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
        clean_title = badge['title'].replace("|", "\\|")
        archive_md.append(f"| {badge['date']} | **{clean_title}** | {clean_desc} |")
        
    if total_detailed > 0:
        archive_md.append(f"\n## Detailed Learning Activities & Codelabs ({total_detailed})\n")
        archive_md.append("| Date Earned | Codelab / Activity Title | Description |")
        archive_md.append("| :---: | :--- | :--- |")
        for badge in detailed_learnings:
            clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
            clean_title = badge['title'].replace("|", "\\|")
            archive_md.append(f"| {badge['date']} | **{clean_title}** | {clean_desc} |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))

if __name__ == "__main__":
    main()
