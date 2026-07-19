import os
import sys
import re
import json
import requests
from datetime import datetime, timezone
from urllib.parse import unquote

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"
ACTIVITY_JSON_PATH = "google_activity.json"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def analyze_badge_list(lst, parsed_badges):
    """Deeply inspects an active data block list to extract paired award badges and timestamps."""
    strings = []
    numbers = []
    
    def walk(element):
        if isinstance(element, str):
            strings.append(element)
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
        
    # Locate valid Unix timestamp boundaries matching realistic calendar years
    epoch = None
    for num in numbers:
        if 946684800 <= num <= 2500000000:  # Seconds format
            epoch = num
            break
        elif 946684800000 <= num <= 2500000000000:  # Milliseconds format
            epoch = num / 1000.0
            break
            
    date_str = "N/A"
    if epoch:
        try:
            date_str = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%d')
        except:
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
    """Traverses down the matrix hierarchy layers ensuring item context remains intact."""
    if isinstance(data, list):
        analyze_badge_list(data, parsed_badges)
        for item in data:
            find_badges_in_matrix(item, parsed_badges)
    elif isinstance(data, dict):
        for val in data.values():
            find_badges_in_matrix(val, parsed_badges)

def fetch_gdev_badges_rpc():
    """Requests Google's batch RPC execution framework using the precise structural matrix."""
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
    
    print(f"📡 Dispatching structured RPC batch execution request...")
    try:
        response = requests.post(url, params=params, data=payload, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"❌ Server returned unexpected gateway code: {response.status_code}")
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
                                    except:
                                        pass
                except:
                    continue
                    
        return parsed_badges
    except Exception as network_error:
        print(f"❌ Connection pipeline failure: {network_error}")
        return None

def main():
    badges = fetch_gdev_badges_rpc()
    if not badges:
        print("❌ Error: Failed to extract structured badges via public RPC handshake.")
        sys.exit(1)
        
    total_public_badges = len(badges)
    total_codelabs_completed = 0
    
    # Optional local file integration check to include verbose activity log records safely
    if os.path.exists(ACTIVITY_JSON_PATH):
        try:
            with open(ACTIVITY_JSON_PATH, "r", encoding="utf-8") as f:
                activity_data = json.load(f)
                
            # Assume activity file contains a list of tracking elements or an explicit counter key
            if isinstance(activity_data, list):
                total_codelabs_completed = len(activity_data)
                for entry in activity_data:
                    title = entry.get("title", "Completed Codelab Task").title()
                    if not any(b['title'] == title for b in badges):
                        badges.append({
                            "title": title,
                            "description": entry.get("description", "Verified custom learning module activity completion log record."),
                            "date": entry.get("date", "N/A")
                        })
            elif isinstance(activity_data, dict):
                total_codelabs_completed = activity_data.get("total_codelabs", 0) or activity_data.get("count", 0)
            print(f"📂 Integrated offline history profile: Found {total_codelabs_completed} verbose codelab rows.")
        except Exception as file_err:
            print(f"⚠️ Activity log integration parsing note: {file_err}")

    # Sort chronologically, gracefully preserving N/A entries below recent milestones
    badges.sort(key=lambda x: x.get("date", "0000-00-00") if x.get("date") != "N/A" else "0000-00-00", reverse=True)
    
    # 1. Update Main Repository README.md Container
    md = []
    md.append("### Google Developer Profile Summary")
    md.append("**Public Profile:** [Verify Developer Profile](https://g.dev/vojislavmiloradovic)  \n")
    
    md.append("#### Platform Progress")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total Milestones & Milestone Badges** | {total_public_badges:,} |")
    if total_codelabs_completed > 0:
        md.append(f"| **Total Codelabs Completed** | {total_codelabs_completed:,} |")
    md.append("\n")

    md.append("#### Latest Achievements")
    md.append("Showing the latest 10 items. View complete historical logs in [Google Developer archive](./archives/google-developer.md).\n")
    md.append("| Date Earned | Badge Title | Description |")
    md.append("| :---: | :--- | :--- |")
    
    for badge in badges[:10]:
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
            print("✅ Main README.md container updated dynamically.")

    # 2. Update Master Historical Archive Log File
    archive_md = []
    archive_md.append("# Complete Google Developer Badges Archive\n")
    archive_md.append(f"Historical record tracking platform achievements earned.\n")
    archive_md.append("| Date Earned | Badge Title | Description |")
    archive_md.append("| :---: | :--- | :--- |")

    for badge in badges:
        clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
        clean_title = badge['title'].replace("|", "\\|")
        archive_md.append(f"| {badge['date']} | **{clean_title}** | {clean_desc} |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Comprehensive historical asset archive refreshed successfully!")

if __name__ == "__main__":
    main()
