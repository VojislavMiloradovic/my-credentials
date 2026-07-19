import os
import sys
import re
import json
import requests
from datetime import datetime, timezone
from urllib.parse import unquote

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def extract_badges_recursively(data, parsed_badges):
    """Recursively scans the unmarshalled JSON structure to locate and extract badge objects."""
    if isinstance(data, str):
        if "/awards/" in data:
            parts = data.split("/awards/")
            if len(parts) > 1:
                badge_path = unquote(parts[1])
                slug = badge_path.split("/")[-1]
                
                # Format clean, token-efficient text titles for AI readability
                title = slug.replace("-", " ").replace("_", " ").title()
                title = title.replace("Gdg", "GDG").replace("Gcp", "GCP").replace("Aws", "AWS")
                
                category = "Community" if "community" in badge_path else "Learning Pathway"
                description = f"Official Google Developer platform achievement ({category}: {slug.replace('-', ' ')})."
                
                if not any(b['title'] == title for b in parsed_badges):
                    parsed_badges.append({
                        "title": title,
                        "description": description,
                        "date": "N/A"
                    })
                    
    elif isinstance(data, list):
        # Look for instances where a timestamp signature is grouped alongside an award string
        has_award = False
        potential_epoch = None
        
        for item in data:
            if isinstance(item, str) and "/awards/" in item:
                has_award = True
            if isinstance(item, list) and len(item) == 1 and isinstance(item[0], (int, float)):
                potential_epoch = item[0]
            elif isinstance(item, (int, float)) and 1000000000 <= item <= 2000000000:
                potential_epoch = item
                
        if has_award:
            for item in data:
                if isinstance(item, str) and "/awards/" in item:
                    parts = item.split("/awards/")
                    if len(parts) > 1:
                        badge_path = unquote(parts[1])
                        slug = badge_path.split("/")[-1]
                        title = slug.replace("-", " ").replace("_", " ").title()
                        title = title.replace("Gdg", "GDG").replace("Gcp", "GCP").replace("Aws", "AWS")
                        
                        date_str = "N/A"
                        if potential_epoch:
                            try:
                                if potential_epoch > 100000000000:
                                    potential_epoch /= 1000.0
                                date_str = datetime.fromtimestamp(potential_epoch, tz=timezone.utc).strftime('%Y-%m-%d')
                            except:
                                pass
                                
                        category = "Community" if "community" in badge_path else "Learning Pathway"
                        description = f"Official Google Developer platform achievement ({category}: {slug.replace('-', ' ')})."
                        
                        if not any(b['title'] == title for b in parsed_badges):
                            parsed_badges.append({
                                "title": title,
                                "description": description,
                                "date": date_str
                            })
                            
        for item in data:
            extract_badges_recursively(item, parsed_badges)
            
    elif isinstance(data, dict):
        for value in data.values():
            extract_badges_recursively(value, parsed_badges)

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
        
        # Parse text chunks looking for serialized sub-JSON payloads across all batch headers
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
                                        extract_badges_recursively(badge_matrix, parsed_badges)
                                    except:
                                        pass
                except Exception:
                    continue
                    
        return parsed_badges

    except Exception as network_error:
        print(f"❌ Connection pipeline failure: {network_error}")
        return None

def main():
    badges = fetch_gdev_badges_rpc()
    
    if not badges:
        print("❌ Error: Failed to extract a valid structured badge collection using the RPC handshake.")
        sys.exit(1)
        
    total_badges = len(badges)
    print(f"✅ Successfully compiled {total_badges} active Google Developer profile achievements.")
    
    # Sort chronologically, dropping N/A instances to the bottom gracefully
    badges.sort(key=lambda x: x.get("date", "0000-00-00") if x.get("date") != "N/A" else "0000-00-00", reverse=True)
    
    # 1. Update Main Repository README.md Layout Container (AI Optimized, No Images)
    md = []
    md.append("### Google Developer Profile Summary")
    md.append("**Public Profile:** [Verify Developer Profile](https://g.dev/vojislavmiloradovic)  \n")
    
    md.append("#### Platform Progress")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total Badges Earned** | {total_badges:,} |")
    md.append("\n")

    md.append("#### Latest Badges")
    md.append("Showing the latest 10 achievements. View complete historical logs in [Google Developer archive](./archives/google-developer.md).\n")
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
        else:
            print("⚠️ Setup notice: Structural comment markers missing inside README.md target boundaries.")

    # 2. Update Master Historical Archive Log File
    archive_md = []
    archive_md.append("# Complete Google Developer Badges Archive\n")
    archive_md.append(f"Historical record tracking all {total_badges} platform achievements earned.\n")
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
