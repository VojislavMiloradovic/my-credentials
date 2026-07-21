import json
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

URL = "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"

INTERNAL_STATS = {
    "Course": 331,
    "Check": 1769,
    "Classroom": 0,
    "Game": 4,
    "Lab": 223,
    "Lesson": 4830
}

def to_iso_date(raw_date_str):
    """Converts strings like 'Earned Jul 21, 2026 EDT' into strict ISO format (YYYY-MM-DD or YYYY-MM)."""
    if not raw_date_str:
        return "N/A"
    
    clean = re.sub(r'^Earned\s+', '', raw_date_str, flags=re.IGNORECASE)
    clean = re.sub(r'\s+[A-Z]{3,4}$', '', clean).strip()
    
    # Try YYYY-MM-DD parsing
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # Try YYYY-MM parsing
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
    os.makedirs("archives", exist_ok=True)
    
    archive_path = "archives/google-cloud-skills.md"
    archive_md = f"# Google Cloud Skills Boost — Full Credentials Archive\n\n"
    archive_md += f"**Public Profile:** [Verify Profile]({URL})  \n"
    archive_md += f"**Total Lifetime Points:** {total_points}  \n"
    archive_md += f"**Total Badges:** {len(badges)}\n\n"
    archive_md += "#### All Earned Badges\n"
    archive_md += "| Date Earned | Badge Title |\n|:---:|---|\n"
    for b in badges:
        archive_md += f"| {b['date_earned']} | **{b['title']}** |\n"
    archive_md += "\n\n[← Back to README](../README.md)\n"
    
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(archive_md)

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

    if not badges:
        badge_md += "*No Google Skills badges detected dynamically yet (checking daily).*\n"
    else:
        badge_md += "#### Latest Earned Badges\n"
        badge_md += "| Date Earned | Badge Title |\n|:---:|---| \n"
        for b in badges[:10]:
            badge_md += f"| *{b['date_earned']}* | **{b['title']}** |\n"
        badge_md += "\n"
        badge_md += f"👉 **[View all {len(badges)} earned badges in the full archive](./archives/google-cloud-skills.md)**\n\n"

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
