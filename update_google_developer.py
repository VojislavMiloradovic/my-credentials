import os
import sys
import requests

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def fetch_gdev_json(username):
    """Cycle through internal Google Developer XHR endpoints to retrieve the live JSON payload."""
    # These are the actual backend paths the client application calls to hydrate the profile UI
    endpoints = [
        f"https://developers.google.com/site-api/developer-profile/u/{username}",
        f"https://developers.google.com/site-api/profiles/u/{username}",
        f"https://developers.google.com/site-api/developer-profile?username={username}"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://developers.google.com/profile/u/{username}"
    }
    
    for url in endpoints:
        print(f"📡 Testing internal data endpoint: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200 and "application/json" in response.headers.get("Content-Type", ""):
                data = response.json()
                # Confirm we received an active profile state or badge array
                if "badges" in data or "profile" in data or "earnedBadges" in data:
                    print(f"✅ Successful JSON handshake established.")
                    return data
            print(f"ℹ️ Endpoint returned status {response.status_code} or unexpected content type.")
        except Exception as e:
            print(f"⚠️ Connection attempt to endpoint failed: {e}")
            continue
            
    return None

def main():
    username = "vojislavmiloradovic"
    
    # Extract the live backend JSON data payload
    data = fetch_gdev_json(username)
    
    if not data:
        print("❌ Error: All internal Google Developer API data paths returned unparsable responses.")
        print("💡 The profile may be set to private, or Google's backend API routing rules have shifted.")
        sys.exit(1)

    # Adaptive normalization to find the badge array regardless of minor schema variations
    badges = data.get("badges", []) or data.get("earnedBadges", []) or data.get("profile", {}).get("badges", [])
    
    total_badges = len(badges)
    print(f"✅ Successfully processed {total_badges} Google Developer profile badges.")

    # Sort badges safely by award date string (newest first)
    badges.sort(key=lambda x: x.get("awarded_date", "0000-00-00"), reverse=True)

    # 1. Build Markdown Table Summary for the README.md
    md = []
    md.append("### Google Developer Profile Summary")
    md.append(f"**Public Profile:** [Verify Developer Profile](https://g.dev/{username})  \n")
    
    md.append("#### Platform Progress")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total Badges Earned** | {total_badges:,} |")
    md.append("\n")

    md.append("#### Latest Badges")
    md.append(f"Showing the latest 10 badges. See the complete history in the [Google Developer archive](./archives/google-developer.md).\n")
    md.append("| Date Earned | Badge Title | Description |")
    md.append("| :---: | :--- | :--- |")
    
    for badge in badges[:10]:
        date_raw = badge.get("awarded_date", "N/A")
        # Clean up full ISO timestamps (YYYY-MM-DDTHH:MM:SSZ) down to standard YYYY-MM-DD strings
        if date_raw and "T" in str(date_raw):
            date_raw = str(date_raw).split("T")[0]
            
        title = badge.get("title", "Untitled Badge")
        desc = badge.get("description", "").replace("\n", " ")
        md.append(f"| *{date_raw}* | **{title}** | {desc} |")
    md.append("\n")

    # Inject update into Main README.md
    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()

        if MARKER_START in readme_content and MARKER_END in readme_content:
            parts_before = readme_content.split(MARKER_START)[0]
            parts_after = readme_content.split(MARKER_END)[1]
            new_readme = f"{parts_before}{MARKER_START}\n" + "\n".join(md) + f"{MARKER_END}{parts_after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_readme)
            print("✅ Successfully updated README.md with Google Developer achievements!")
        else:
            print("⚠️ Setup notice: Missing structural HTML comment markers inside README.md.")
    
    # 2. Build In-Depth Historical Log File
    print(f"Generating comprehensive archive log in {GDEV_ARCHIVE_PATH}...")
    archive_md = []
    archive_md.append("# Complete Google Developer Badges Archive\n")
    archive_md.append(f"Historical record of all {total_badges} learning badges earned on the Google Developer platform.\n")
    archive_md.append("| Date Earned | Badge Title | Description | Link |")
    archive_md.append("| :---: | :--- | :--- | :--- |")

    for badge in badges:
        date_raw = badge.get("awarded_date", "N/A")
        if date_raw and "T" in str(date_raw):
            date_raw = str(date_raw).split("T")[0]
            
        title = badge.get("title", "Untitled Badge").replace("|", "\\|")
        desc = badge.get("description", "").replace("|", "\\|").replace("\n", " ")
        url = badge.get("badge_url", "🎓 Profile Verified")
        archive_md.append(f"| {date_raw} | **{title}** | {desc} | [Link]({url}) |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Complete Google Developer archive synchronized successfully!")

if __name__ == "__main__":
    main()
