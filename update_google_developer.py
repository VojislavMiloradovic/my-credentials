import os
import sys
import re
import json
import requests

README_PATH = "README.md"
GDEV_ARCHIVE_PATH = "archives/google-developer.md"

MARKER_START = "<!-- GOOGLE_DEVELOPER_START -->"
MARKER_END = "<!-- GOOGLE_DEVELOPER_END -->"

def main():
    username = "vojislavmiloradovic"
    url = f"https://developers.google.com/profile/u/{username}"
    
    print(f"📡 Fetching Google Developer profile...")
    
    # Simulating a modern browser request to prevent security firewalls or 403 blocks
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to fetch profile. Status code: {response.status_code}")
            print("📋 Response Context Snippet:")
            print(response.text[:600])
            sys.exit(1)
            
        content_type = response.headers.get("Content-Type", "")
        badges = []

        # Scenario A: The URL acts as a clean JSON endpoint
        if "application/json" in content_type:
            data = response.json()
            badges = data.get("badges", [])
            
        # Scenario B: The URL serves the raw HTML document shell (Caused the JSONDecodeError)
        else:
            print("ℹ️ Server returned HTML page. Extracting data via string parsing...")
            html_content = response.text
            
            # Look for common hydration patterns where Google embeds data inside script blocks
            # Checks for 'window.__INITIAL_DATA__ = {...};' or 'initialData = {...};'
            match = re.search(r'(?:__INITIAL_DATA__|initialData)\s*=\s*(\{.*?\});', html_content)
            
            if match:
                try:
                    payload = json.loads(match.group(1))
                    badges = payload.get("badges", [])
                except json.JSONDecodeError as je:
                    print(f"⚠️ Matched structural state script tag, but JSON parsing failed: {je}")
            
            # Fallback if structural patterns change or if profile is completely dynamic
            if not badges:
                print("❌ HTML structure parsed, but no explicit badge payload was extracted.")
                print("📋 Raw content header sample to audit page structure:")
                print(html_content[:800])
                print("\n💡 Action Item: Inspect the text dump above in your workflow log to confirm the correct XHR data script target.")
                sys.exit(1)

    except Exception as e:
        print(f"❌ Error communicating with endpoint: {e}")
        sys.exit(1)
        
    total_badges = len(badges)
    print(f"✅ Successfully found and processed {total_badges} Google Developer badges.")

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
        date = badge.get("awarded_date", "N/A")
        title = badge.get("title", "Untitled Badge")
        desc = badge.get("description", "").replace("\n", " ")
        md.append(f"| *{date}* | **{title}** | {desc} |")
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
        date = badge.get("awarded_date", "N/A")
        title = badge.get("title", "Untitled Badge").replace("|", "\\|")
        desc = badge.get("description", "").replace("|", "\\|").replace("\n", " ")
        url = badge.get("badge_url", "🎓 Profile Verified")
        archive_md.append(f"| {date} | **{title}** | {desc} | [Link]({url}) |")

    archive_md.append("\n\n[← Back to README](../README.md)\n")

    os.makedirs(os.path.dirname(GDEV_ARCHIVE_PATH), exist_ok=True)
    with open(GDEV_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Complete Google Developer archive synchronized successfully!")

if __name__ == "__main__":
    main()
