import os
import sys
import re
import json
import requests
from datetime import datetime, timezone

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def safely_extract_string(element):
    """Safely extracts a string from potential nested lists returned by Google's RPC response."""
    if isinstance(element, list):
        if len(element) > 0:
            return safely_extract_string(element[0])
        return ""
    return str(element) if element is not None else ""

def fetch_gdev_badges_rpc():
    """Requests Google's batch RPC execution framework using the precise structural matrix."""
    url = "https://me.developers.google.com/_/GoogleDeveloperProfile/data/batchexecute"
    
    # URL Query Parameters matching the layout requirement rules
    params = {
        "rpcids": "gQeJTc,RwSpuf",
        "source-path": "/u/vojislavmiloradovic",
        "bl": "boq_gdp-builders-ui_20260713.05_p0",
        "f.sid": "8705607390718843222",
        "hl": "en",
        "_reqid": "252198",
        "rt": "c"
    }
    
    # Substituting "me" with your public internal profile ID to allow access without login cookies
    profile_id = "110772055890077594470"
    
    # Replicating the exact multi-nested stringified JSON arrays Google expects inside the body
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
        
        # Track down the data vector line containing the identifier key token
        for line in raw_text.splitlines():
            if "gQeJTc" in line:
                # Remove framework stream length size-prefixes from the front of the data row
                clean_line = re.sub(r'^\d+', '', line).strip()
                
                try:
                    outer_data = json.loads(clean_line)
                    # Extract the nested stringified payload block located at position index 2
                    inner_str_payload = outer_data[0][2]
                    badge_matrix = json.loads(inner_str_payload)
                    
                    for item in badge_matrix:
                        if len(item) > 4:
                            # Use defensive extraction to gracefully pull array properties out safely
                            title = safely_extract_string(item[2]) or "Untitled Badge"
                            desc = safely_extract_string(item[3])
                            icon_path = safely_extract_string(item[4])
                            
                            if icon_path and icon_path.startswith("/"):
                                icon_url = f"https://developers.google.com{icon_path}"
                            else:
                                icon_url = icon_path
                                
                            # Epoch values are held inside the array cluster at index position 6
                            date_str = "N/A"
                            if len(item) > 6 and isinstance(item[6], list) and len(item[6]) > 0:
                                epoch_seconds = item[6][0]
                                date_str = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime('%Y-%m-%d')
                            
                            parsed_badges.append({
                                "title": title.strip(),
                                "description": desc.strip(),
                                "icon_url": icon_url,
                                "date": date_str
                            })
                except Exception as parse_error:
                    print(f"⚠️ Internal parse warning (skipping fragment block): {parse_error}")
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
    
    # Sort chronologically (newest first)
    badges.sort(key=lambda x: x.get("date", "0000-00-00"), reverse=True)
    
    # 1. Update Main Repository README.md Layout Container
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
    md.append("| Date Earned | Icon | Badge Title | Description |")
    md.append("| :---: | :---: | :--- | :--- |")
    
    for badge in badges[:10]:
        icon_display = f"<img src=\"{badge['icon_url']}\" width=\"32\" height=\"32\" />" if badge['icon_url'] else "🎓"
        clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
        clean_title = badge['title'].replace("|", "\\|")
        md.append(f"| *{badge['date']}* | {icon_display} | **{clean_title}** | {clean_desc} |")
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
    archive_md.append("| Date Earned | Icon | Badge Title | Description |")
    archive_md.append("| :---: | :---: | :--- | :--- |")

    for badge in badges:
        icon_display = f"<img src=\"{badge['icon_url']}\" width=\"32\" height=\"32\" />" if badge['icon_url'] else "🎓"
        clean_desc = badge['description'].replace("|", "\\|").replace("\n", " ")
        clean_title = badge['title'].replace("|", "\\|")
        archive_md.append(f"| {badge['date']} | {icon_display} | **{clean_title}** | {clean_desc} |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Comprehensive historical asset archive refreshed successfully!")

if __name__ == "__main__":
    main()
