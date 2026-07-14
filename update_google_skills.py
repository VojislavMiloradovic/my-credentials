import json
import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.skills.google/public_profiles/2011cb91-6066-4d7f-bbec-644b1530829b"

def clean_title(raw_text):
    """
    Cleans up the long descriptive text to extract only the actual badge title.
    """
    if not raw_text:
        return ""
    
    # Strip whitespace/newlines
    text = raw_text.replace('\n', ' ').strip()
    
    # Google Skills descriptions often start with words like 'Earn the...', 'Complete the...' 
    # Let's extract the actual course title by focusing on the capitalized words or using regex patterns.
    patterns = [
        r"(?:Complete|Earn) the (?:introductory|advanced|intermediate)?\s*(.*?)\s*(?:skill badge|course) to demonstrate",
        r"(?:Complete|Earn) the (?:introductory|advanced|intermediate)?\s*(.*?)\s*(?:skill badge|course), where",
        r"^(.*?)(?:\. Complete|\. Earn|\. This course|\. Skill badges|\?)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Clean up trailing punctuation if any
            candidate = re.sub(r'[\.,]$', '', candidate)
            return candidate
            
    # Fallback to a simple sentence split
    parts = text.split('.')
    return parts[0].strip() if parts else text

def fetch_skills():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(URL, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to load page: Status {response.status_code}")

    soup = BeautifulSoup(response.text, 'html.parser')
    badges = []
    
    # Target typical Google profile badge elements
    # Sometimes they reside in 'ql-badge' elements or custom tags
    badge_elements = soup.find_all("div", class_="profile-badge") or soup.find_all("div", class_="badge-card")
    
    if not badge_elements:
        # Fallback to any div containing text that looks like a badge
        badge_elements = [div for div in soup.find_all("div") if div.find("p") and ("skill badge" in div.get_text().lower() or "earned" in div.get_text().lower())]

    for elem in badge_elements:
        # 1. Grab image
        img_elem = elem.find("img")
        img_url = None
        if img_elem:
            # Check for standard src, then lazy-loaded src variants
            img_url = img_elem.get("src") or img_elem.get("data-src") or img_elem.get("srcset")
            if img_url and "," in img_url:  # Clean up srcset arrays if present
                img_url = img_url.split(",")[0].strip().split(" ")[0]

        # 2. Grab and clean title
        # Look for headers, then paragraphs
        text_elem = elem.find("h3") or elem.find("h4") or elem.find("p") or elem
        raw_text = text_elem.get_text(strip=True) if text_elem else ""
        
        title = clean_title(raw_text)
        if title:
            badges.append({
                "title": title,
                "image_url": img_url,
                "description": raw_text[:200] + "..." if len(raw_text) > 200 else raw_text
            })

    # Deduplicate based on title
    unique_badges = []
    seen = set()
    for b in badges:
        if b["title"].lower() not in seen:
            seen.add(b["title"].lower())
            unique_badges.append(b)

    # 1. Save cleaned JSON data
    profile_data = {
        "profile_url": URL,
        "total_badges": len(unique_badges),
        "badges": unique_badges
    }
    with open("google_skills.json", "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2, ensure_ascii=False)
    print(f"Updated google_skills.json with {len(unique_badges)} badges.")

    # 2. Update README.md
    update_readme(unique_badges)

def update_readme(badges):
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            readme_content = f.read()
    except FileNotFoundError:
        print("README.md not found. Skipping README update.")
        return

    # Generate Markdown table
    if not badges:
        badge_md = "\n*No Google Skills badges detected dynamically yet (checking daily).*\n"
    else:
        badge_md = f"\n### Google Cloud Skills Boost ({len(badges)} Badges)\n\n"
        badge_md += "| Badge | Title |\n|---|---|\n"
        for b in badges:
            # Render badge icon or fallback to medal emoji
            img_tag = f"<img src='{b['image_url']}' width='45' />" if b['image_url'] else "🏅"
            badge_md += f"| {img_tag} | **{b['title']}** |\n"
        badge_md += "\n"

    # Match the placeholder comments
    pattern = r"<!-- GOOGLE_SKILLS_START -->.*?<!-- GOOGLE_SKILLS_END -->"
    replacement = f"<!-- GOOGLE_SKILLS_START -->{badge_md}<!-- GOOGLE_SKILLS_END -->"
    
    new_readme, count = re.subn(pattern, replacement, readme_content, flags=re.DOTALL)
    
    if count > 0:
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new_readme)
        print("Successfully updated README.md with new badge list!")
    else:
        print("Could not find <!-- GOOGLE_SKILLS_START --> and <!-- GOOGLE_SKILLS_END --> tags in README.md.")

if __name__ == "__main__":
    fetch_skills()
