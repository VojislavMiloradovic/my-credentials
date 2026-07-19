import os
import sys
import requests

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def main():
    username = "vojislavmiloradovic"
    url = f"https://developers.google.com/profile/u/{username}"
    
    print(f"📡 Fetching Google Developer profile from hidden API...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to fetch profile. Status code: {response.status_code}")
            sys.exit(1)
        
        data = response.json()
    except Exception as e:
        print(f"❌ Error communicating with endpoint: {e}")
        sys.exit(1)

    # Extract user profile information out of response payload
    profile = data.get("profile", {})
    badges = data.get("badges", [])
    
    total_badges = len(badges)
    print(f"✅ Found {total_badges} Google Developer badges.")

    # Sort badges by award date (newest first)
    # The API returns timestamps or formatted dates; handle fallback safely
    badges.sort(key=lambda x: x.get("awarded_date", "0000-00-00"), reverse=True)

    # 1. Build Markdown Section for Main README.md
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
        date = badge.get("awarded_date", "N/A")
        title = badge.get("title", "Untitled Badge")
        desc = badge.get("description", "").replace("\n", " ")
        md.append(f"| *{date}* | **{title}** | {desc} |")
    md.append("\n")

    # Update Main README.md
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
            print("ℹ️ Setup note: Add the HTML comment markers to your README to inject the data.")
    
    # 2. Generate Complete Archive File
    print(f"Generating comprehensive archive in {GDEV_ARCHIVE_PATH}...")
    archive_md = []
    archive_md.append("# Complete Google Developer Badges Archive\n")
    archive_md.append(f"Historical record of all {total_badges} learning badges earned on the Google Developer platform.\n")
    archive_md.append("| Date Earned | Badge Title | Description | Link |")
    archive_md.append("| :---: | :--- | :--- | :--- |")

    for badge in badges:
        date = badge.get("awarded_date", "N/A")
        title = badge.get("title", "Untitled Badge").replace("|", "\\|")
        desc = badge.get("description", "").replace("|", "\\|").replace("\n", " ")
        url = badge.get("badge_url", "🎓 Profile Verified")
        archive_md.append(f"| {date} | **{title}** | {desc} | [Link]({url}) |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Google Developer archive synchronized successfully!")

if __name__ == "__main__":
    main()
