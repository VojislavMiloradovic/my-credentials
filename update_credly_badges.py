import re
import time
from datetime import datetime, timezone

import requests

from archiver import RAW_BASE_DEFAULT, generate_platform_archive

USERNAME = "vojislavmiloradovic"
USER_ID = "752aee40-7358-4ade-9a49-81e8b6f49225"
README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "credly-badges"
PLATFORM_NAME = "Credly Verified Credentials"

MARKER_START = "<!-- CREDLY_BADGES_START -->"
MARKER_END = "<!-- CREDLY_BADGES_END -->"


def normalize_iso_date(raw_date: str) -> str:
    """Extracts ISO date string (YYYY-MM-DD or YYYY-MM) from raw string."""
    if not raw_date or raw_date == "N/A":
        return "N/A"
    clean = str(raw_date).split("T")[0].strip(" \t\n\r\"'")
    match = re.search(r"^\d{4}-\d{2}(-\d{2})?", clean)
    if match:
        return match.group(0)
    return clean if clean else "N/A"


def fetch_paginated_data(url_template: str, headers: dict, page_size: int = 48) -> list[dict]:
    """Fetches paginated JSON data from Credly API endpoints safely."""
    all_items = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        url = url_template.format(page=page, page_size=page_size)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"⚠️ Warning: Request failed for page {page} on URL {url}: {e}")
            break

        page_items = data.get("data", [])
        if not page_items:
            break

        all_items.extend(page_items)
        metadata = data.get("metadata", {})
        if "total_pages" in metadata:
            total_pages = metadata["total_pages"]
        elif len(page_items) < page_size:
            total_pages = page
        else:
            total_pages = max(total_pages, page + 1)

        page += 1
        time.sleep(0.3)

    return all_items


def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    print("🔄 Fetching Credly badges...")
    native_url_template = f"https://www.credly.com/users/{USERNAME}/badges.json?page={{page}}"
    native_raw = fetch_paginated_data(native_url_template, headers)

    external_url_template = f"https://www.credly.com/api/v1/users/{USER_ID}/external_badges/open_badges/public?page={{page}}&page_size={{page_size}}"
    external_raw = fetch_paginated_data(external_url_template, headers)

    badges = []
    all_skills_set = set()

    # 1. Process Native Credly Badges
    for item in native_raw:
        badge_id = item.get("id")
        issued_at = normalize_iso_date(item.get("issued_at_date") or item.get("issued_at", "N/A"))

        template = item.get("badge_template", {})
        name = template.get("name", "Unknown Badge")

        raw_skills = template.get("skills", [])
        badge_skills = []
        for s in raw_skills:
            skill_name = s.get("name") if isinstance(s, dict) else str(s)
            if skill_name:
                badge_skills.append(skill_name)
                all_skills_set.add(skill_name)

        issuer = template.get("issuer", {})
        issuer_name = issuer.get("summary") or "Verified Issuer"
        verify_url = f"https://www.credly.com/badges/{badge_id}"

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "type": "Credly Verified",
            "skills": badge_skills,
        })

    # 2. Process External / Imported Badges
    for item in external_raw:
        ext = item.get("external_badge", {})
        name = ext.get("badge_name") or item.get("name") or "Unknown Certification"
        issuer_name = ext.get("issuer_name") or item.get("issuer") or "Third-Party Issuer"
        issued_at = normalize_iso_date(ext.get("issued_at_date") or item.get("issued_at_date") or "N/A")

        verify_url = ext.get("badge_url") or item.get("verification_url") or f"https://www.credly.com/users/{USERNAME}"

        raw_skills = item.get("skills", [])
        badge_skills = []
        if isinstance(raw_skills, list):
            for s in raw_skills:
                skill_name = s.get("name") if isinstance(s, dict) else str(s)
                if skill_name:
                    badge_skills.append(skill_name)
                    all_skills_set.add(skill_name)

        badges.append({
            "name": name,
            "issuer": issuer_name,
            "date": issued_at,
            "verify": verify_url,
            "type": "External/Imported",
            "skills": badge_skills,
        })

    # 3. Sort Badges Descending by Date
    badges.sort(key=lambda x: x["date"] if x["date"] != "N/A" else "0000-00-00", reverse=True)

    total_badges = len(badges)
    unique_skills = sorted(all_skills_set)
    total_skills = len(unique_skills)
    native_count = sum(1 for b in badges if b["type"] == "Credly Verified")
    external_count = sum(1 for b in badges if b["type"] == "External/Imported")

    # 4. Format Rows for Monolith & Chunked Archives
    formatted_rows = []
    for b in badges:
        clean_name = b["name"].replace("|", "\\|")
        clean_issuer = b["issuer"].replace("|", "\\|")
        row_text = f"| {b['date']} | **{clean_name}** | {clean_issuer} | `{b['type']}` | [Verify]({b['verify']}) |"
        formatted_rows.append((row_text, b["date"]))

    # 5. Build README content block
    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    index_filename = f"{PLATFORM_PREFIX}-index.md"
    monolith_filename = f"{PLATFORM_PREFIX}-complete.md"
    index_raw = f"{RAW_BASE_DEFAULT}/{index_filename}"
    latest_chunk_raw = f"{RAW_BASE_DEFAULT}/{PLATFORM_PREFIX}-{now_ym}-part-01.md"

    readme_lines = [
        "### Credly Verified Credentials",
        f"- **Public Profile:** [Verify Credly Profile](https://www.credly.com/users/{USERNAME})",
        f"- **Total Portfolio Credentials:** {total_badges} ({native_count} Credly Verified, {external_count} External/Imported)",
        f"- **Total Verified Skills Mapped:** {total_skills}\n",
        "#### Latest Earned Credentials",
        f"Showing latest 10 of {total_badges:,} credentials. View the full dataset via the [Platform Archive Index](./archives/{index_filename}) ([Raw Index]({index_raw})), latest slice [Part 01 Raw]({latest_chunk_raw}), or the [Monolithic Complete File](./archives/{monolith_filename}).\n",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for b in badges[:10]:
        clean_name = b["name"].replace("|", "\\|")
        clean_issuer = b["issuer"].replace("|", "\\|")
        readme_lines.append(f"| *{b['date']}* | **{clean_name}** | {clean_issuer} | `{b['type']}` |")

    # Extra Skills Section inserted prior to table in Monolith
    skills_monolith_header = (
        "## Mapped Professional Skills\n\n"
        + ", ".join([f"`{skill}`" for skill in unique_skills])
        + "\n\n---\n\n"
    )

    # 6. Delegate generation and README insertion to archiver module
    generate_platform_archive(
        platform_prefix=PLATFORM_PREFIX,
        platform_name=PLATFORM_NAME,
        table_headers=["Date Earned", "Credential Title", "Verified Issuer", "Type", "Verification Link"],
        table_alignments=[":---:", ":---", ":---", ":---:", ":---:"],
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=MARKER_START,
        marker_end=MARKER_END,
        archive_dir=ARCHIVE_DIR,
        readme_path=README_PATH,
        extra_monolith_header_md=skills_monolith_header,
    )

    print("✅ Successfully updated Credly badges archive & README!")


if __name__ == "__main__":
    main()
