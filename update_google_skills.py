import json
import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"

# --- 1. INTERNAL STATS (Update these counts whenever you make progress!) ---
INTERNAL_STATS = {
    "Course": 331,
    "Check": 1769,
    "Classroom": 0,
    "Game": 4,
    "Lab": 223,
    "Lesson": 4830
}

def parse_badge_text(raw_text):
    """
    Splits messy scraped text like:
    "Digital Transformation with Google CloudEarned Sep  6, 2025 EDT"
    into a clean title and a formatted earned date.
    """
    if not raw_text:
        return "Unknown Badge", ""
    
    # Standardize whitespace
    text = re.sub(r'\s+', ' ', raw_text).strip()
    
    # Look for the transition 'Earned <Month>'
    match = re.search(r"^(.*?)(Earned\s+[A-Za-z]{3}\s+\d{1,2},\s+\d{4}.*)$", text)
    
    if match:
        title = match.group(1).strip()
        date_earned = match.group(2).strip()
        # Remove timezone abbreviation at the end (e.g. "EDT", "UTC")
        date_earned = re.sub(r'\s+[A-Z]{3,4}$', '', date_earned)
        return title, date_earned
    
    return text, ""

def fetch_skills():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to load page: Status {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # --- 2. SCRAPE TOTAL POINTS FROM PUBLIC PROFILE ---
    total_points = "188,404"  # Default fallback
    try:
        # Search the page text for strings like "188,404 points" or "188404 points"
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
    
    # Target Google profile badge containers
    badge_elements = soup.find_all("div", class_="profile-badge") or soup.find_all("div", class_="badge-card")
    
    if not badge_elements:
        # Fallback to general cards
        badge_elements = [div for div in soup.find_all("div") if div.find("p") and ("earned" in div.get_text().lower() or "skill badge" in div.get_text().lower())]

    for elem in badge_elements:
        # 1. Grab image URL
        img_elem = elem.find("img")
        img_url = None
        if img_elem:
            img_url = img_elem.get("src") or img_elem.get("data-src") or img_elem.get("srcset")
            if img_url and "," in img_url:
                img_url = img_url.split(",")[0].strip().split(" ")[0]

        # 2. Grab and clean text
        text_elem = elem.find("h3") or elem.find("h4") or elem.find("p") or elem
        raw_text = text_elem.get_text(" ", strip=True) if text_elem else ""
        
        # Only parse if it looks like a valid credential
        if "earned" in raw_text.lower():
            title, date_earned = parse_badge_text(raw_text)
            if title:
                # 3. Grab badge-specific verification link (if available, else fallback to profile URL)
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

    # Deduplicate by title
    unique_badges = []
    seen = set()
    for b in badges:
        if b["title"].lower() not in seen:
            seen.add(b["title"].lower())
            unique_badges.append(b)

    # Sort badges so latest earned are on top
    try:
        from datetime import datetime
        def get_sort_key(x):
            date_str = x["date_earned"].replace("Earned ", "")
            return datetime.strptime(date_str, "%b %d, %Y")
            
        unique_badges.sort(key=get_sort_key, reverse=True)
    except Exception:
        pass

    # 4. Save cleaned JSON data
    profile_data = {
        "profile_url": URL,
        "total_points": total_points,
        "internal_stats": INTERNAL_STATS,
        "total_badges": len(unique_badges),
        "badges": unique_badges
    }
    with open("google_skills.json", "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)
    print(f"Updated google_skills.json with {len(unique_badges)} badges and {total_points} points.")

    # 5. Update README.md
    update_readme(unique_badges, total_points)

def update_readme(badges, total_points):
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            readme_content = f.read()
    except FileNotFoundError:
        print("README.md not found. Skipping README update.")
        return

    # Generate the complete Markdown section
    badge_md = f"\n### Google Cloud Skills Boost ({len(badges)} Badges)\n\n"
    badge_md += f"**Public Profile:** [Verify Profile]({URL})  \n"
    badge_md += f"**Total Lifetime Points:** {total_points}\n\n"
    
    # Render Internal Stats Table
    badge_md += "#### Platform Progress Summary\n"
    badge_md += "| Metric | Count |\n|---|---|\n"
    for metric, count in INTERNAL_STATS.items():
        badge_md += f"| **{metric}** | {count:,} |\n"
    badge_md += "\n"

    # Render Badges List
    if not badges:
        badge_md += "*No Google Skills badges detected dynamically yet (checking daily).*\n"
    else:
        badge_md += "#### Earned Badges\n"
        badge_md += "| Badge | Credential | Date Earned | Verification |\n|:---:|---|:---:|:---:|\n"
        for b in badges:
            img_tag = f"<img src=\"{b['image_url']}\" width=\"40\" />" if b['image_url'] else "🏅"
            v_url = b.get("verification_url", URL)
            badge_md += f"| {img_tag} | **{b['title']}** | *{b['date_earned']}* | [Verify Credential]({v_url}) |\n"
        badge_md += "\n"

    # Robust tag matching and replacement
    start_tag = "<!-- GOOGLE_SKILLS_START -->"
    end_tag = "<!-- GOOGLE_SKILLS_END -->"
    
    if start_tag in readme_content and end_tag in readme_content:
        parts_before = readme_content.split(start_tag)[0]
        parts_after = readme_content.split(end_tag)[1]
        
        new_readme = f"{parts_before}{start_tag}{badge_md}{end_tag}{parts_after}"
        
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new_readme)
        print("Successfully updated README.md with the structured progress summary and badge table!")
    else:
        print("Could not find the exact HTML comments <!-- GOOGLE_SKILLS_START --> and <!-- GOOGLE_SKILLS_END --> in README.md.")

if __name__ == "__main__":
    fetch_skills()
