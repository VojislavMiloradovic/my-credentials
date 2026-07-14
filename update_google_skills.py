import json
import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"

def fetch_skills():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to load page: Status {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Locate badges (Google Skills often renders classes dynamically; this captures standard card patterns)
    badges = []
    
    # Locate badge titles and their image links if available
    # We look for typical card layouts in Google Skills profiles
    badge_cards = soup.find_all("div", class_="badge-card") or soup.find_all("div", class_="profile-badge")
    
    for card in badge_cards:
        title_elem = card.find("h3") or card.find("div", class_="title") or card.find("p")
        img_elem = card.find("img")
        
        title = title_elem.get_text(strip=True) if title_elem else None
        img_url = img_elem["src"] if img_elem and "src" in img_elem.attrs else None
        
        if title:
            badges.append({
                "title": title,
                "image_url": img_url
            })

    # Backup lookup if specific structures aren't found
    if not badges:
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if "Credential" in text or "Badge" in text:
                badges.append({"title": text, "image_url": None})

    # 1. Save JSON data
    profile_data = {
        "profile_url": URL,
        "total_badges": len(badges),
        "badges": badges
    }
    with open("google_skills.json", "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)
    print(f"Updated google_skills.json with {len(badges)} badges.")

    # 2. Update README.md
    update_readme(badges)

def update_readme(badges):
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            readme_content = f.read()
    except FileNotFoundError:
        print("README.md not found. Skipping README update.")
        return

    # Generate Markdown to inject
    if not badges:
        badge_md = "\n*No Google Skills badges detected dynamically yet (checking daily).*\n"
    else:
        badge_md = f"\n### Google Cloud Skills Boost ({len(badges)} Badges)\n\n"
        badge_md += "| Badge | Title |\n|---|---|\n"
        for b in badges:
            img_tag = f"<img src='{b['image_url']}' width='40' />" if b['image_url'] else "🏅"
            badge_md += f"| {img_tag} | {b['title']} |\n"
        badge_md += "\n"

    # Match the placeholder comments
    pattern = r"<!-- GOOGLE_SKILLS_START -->.*?<!-- GOOGLE_SKILLS_END -->"
    replacement = f"<!-- GOOGLE_SKILLS_START -->{badge_md}<!-- GOOGLE_SKILLS_END -->"
    
    # Replace content safely
    new_readme, count = re.subn(pattern, replacement, readme_content, flags=re.DOTALL)
    
    if count > 0:
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new_readme)
        print("Successfully updated README.md with new badge list!")
    else:
        print("Could not find <!-- GOOGLE_SKILLS_START --> and <!-- GOOGLE_SKILLS_END --> tags in README.md.")

if __name__ == "__main__":
    fetch_skills()
