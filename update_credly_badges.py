"""
update_credly_badges.py
-----------------------
Fetches native Credly badges and external Open Badges, merges them,
saves output to credly_badges.json, generates platform archives,
and updates README.md via archive_utils.
"""

import json
import logging
import os
from typing import Any

import requests

try:
    from archive_utils import generate_platform_archive
except ImportError:
    generate_platform_archive = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("credly_updater")

# Profile Identifiers (can be overridden via environment variables)
CREDLY_USERNAME = os.getenv("CREDLY_USERNAME", "vojislavmiloradovic")
CREDLY_USER_ID = os.getenv("CREDLY_USER_ID", "752aee40-7358-4ade-9a49-81e8b6f49225")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "credly_badges.json")

# Default headers emulating standard browser requests to pass CDN checks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_date(raw_date: str | None) -> str | None:
    """Extracts YYYY-MM-DD from ISO or timestamp strings."""
    if not raw_date:
        return None
    return str(raw_date).split("T")[0]


def fetch_native_badges(username: str) -> list[dict[str, Any]]:
    """Fetches native Credly badges via unauthenticated profile route with pagination."""
    badges = []
    page = 1
    page_size = 100

    logger.info(f"🔄 Starting native badge fetch for user '{username}'...")

    while True:
        url = f"https://www.credly.com/users/{username}/badges.json"
        params = {"page": page, "page_size": page_size}

        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            raw_badges = data.get("data", [])
            if not raw_badges:
                logger.info(f"  No more native badges found on page {page}.")
                break

            logger.info(f"  Page {page}: Retrieved {len(raw_badges)} native badges.")

            for badge in raw_badges:
                badge_template = badge.get("badge_template", {})

                # Extract Issuer safely
                issuer_entities = badge.get("issuer", {}).get("entities", [])
                issuer_name = (
                    issuer_entities[0].get("entity", {}).get("name")
                    if issuer_entities and isinstance(issuer_entities[0], dict)
                    else "Credly"
                )

                # Extract Skills safely
                skills = [
                    s.get("name")
                    for s in badge_template.get("skills", [])
                    if isinstance(s, dict) and s.get("name")
                ]

                badge_id = badge.get("id")
                title = badge_template.get("name") or badge.get("name")
                issued_at = normalize_date(badge.get("issued_at_date") or badge.get("issued_at"))
                expires_at = normalize_date(badge.get("expires_at_date") or badge.get("expires_at"))
                image_url = badge_template.get("image_url") or badge.get("image_url")
                verify_url = f"https://www.credly.com/badges/{badge_id}/public_url" if badge_id else None

                parsed_badge = {
                    "id": badge_id,
                    "title": title,
                    "name": title,
                    "issuer": issuer_name,
                    "issuer_name": issuer_name,
                    "issued_at": issued_at,
                    "issued_at_date": issued_at,
                    "date": issued_at,
                    "expires_at": expires_at,
                    "image_url": image_url,
                    "image": image_url,
                    "verify_url": verify_url,
                    "url": verify_url,
                    "type": "Credly Verified",
                    "verification_type": "Credly Verified",
                    "skills": skills,
                }
                badges.append(parsed_badge)

            metadata = data.get("metadata", {})
            total_pages = metadata.get("total_pages")
            if total_pages and page >= total_pages:
                break

            if len(raw_badges) < page_size:
                break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to fetch native badges on page {page}: {e}")
            break

    logger.info(f"✅ Finished native badge fetch: {len(badges)} native badges total.")
    return badges


def fetch_external_badges(user_id: str) -> list[dict[str, Any]]:
    """Fetches public external/imported Open Badges for user UUID."""
    url = f"https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public"
    logger.info("🔄 Fetching external open badges from public endpoint...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()

        raw_external = (
            data.get("data", [])
            if isinstance(data, dict)
            else (data if isinstance(data, list) else [])
        )
        logger.info(f"  Retrieved {len(raw_external)} external open badges.")

        parsed_external = []
        for item in raw_external:
            if not isinstance(item, dict):
                continue

            badge_info = item.get("badge", {}) if isinstance(item.get("badge"), dict) else {}
            assertion = item.get("assertion", {}) if isinstance(item.get("assertion"), dict) else {}

            title = (
                badge_info.get("name")
                or assertion.get("badge", {}).get("name")
                or item.get("title")
                or "External Badge"
            )

            issuer_name = (
                badge_info.get("issuer", {}).get("name")
                or assertion.get("badge", {}).get("issuer", {}).get("name")
                or item.get("issuer_name")
                or "External Issuer"
            )

            issued_at = normalize_date(
                assertion.get("issuedOn")
                or item.get("issued_at")
                or item.get("issued_at_date")
            )

            badge_id = item.get("id") or item.get("uuid")
            image_url = badge_info.get("image") or item.get("image_url")
            verify_url = item.get("verify_url") or assertion.get("id")

            parsed_external.append({
                "id": badge_id,
                "title": title,
                "name": title,
                "issuer": issuer_name,
                "issuer_name": issuer_name,
                "issued_at": issued_at,
                "issued_at_date": issued_at,
                "date": issued_at,
                "expires_at": normalize_date(item.get("expires_at")),
                "image_url": image_url,
                "image": image_url,
                "verify_url": verify_url,
                "url": verify_url,
                "type": "External/Imported",
                "verification_type": "External/Imported",
                "skills": item.get("skills", []),
            })

        logger.info(f"✅ Successfully parsed {len(parsed_external)} external badges.")
        return parsed_external

    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Warning: Failed to fetch external badges: {e}")
        return []


def merge_and_save_badges(
    native_badges: list[dict[str, Any]],
    external_badges: list[dict[str, Any]],
    output_filepath: str,
) -> list[dict[str, Any]]:
    """Combines native and external badges, deduplicates, and saves JSON."""
    all_badges = native_badges + external_badges

    unique_badges = []
    seen = set()

    for badge in all_badges:
        key = badge.get("id") or f"{badge.get('title')}-{badge.get('issuer')}"
        if key not in seen:
            seen.add(key)
            unique_badges.append(badge)

    payload = {
        "user_username": CREDLY_USERNAME,
        "user_id": CREDLY_USER_ID,
        "total_count": len(unique_badges),
        "native_count": len(native_badges),
        "external_count": len(external_badges),
        "badges": unique_badges,
    }

    try:
        with open(output_filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"🎉 Output written to '{output_filepath}' ({len(unique_badges)} total badges).")
    except OSError as e:
        logger.error(f"❌ Failed to write output file '{output_filepath}': {e}")

    return unique_badges


def build_archives_and_readme(badges: list[dict[str, Any]]) -> None:
    """Generates markdown archive files and updates README.md via archive_utils."""
    if not generate_platform_archive:
        logger.warning("⚠️ archive_utils module not available. Skipping archive generation.")
        return

    # Sort badges descending by date
    sorted_badges = sorted(
        badges,
        key=lambda b: str(b.get("issued_at") or ""),
        reverse=True,
    )

    all_skills = set()
    formatted_rows = []

    for b in sorted_badges:
        date_str = b.get("issued_at") or "N/A"
        title = b.get("title") or "Unknown Credential"
        verify_url = b.get("verify_url")
        issuer = b.get("issuer") or "Credly"
        v_type = b.get("type") or "Credly Verified"

        for skill in b.get("skills", []):
            if skill:
                all_skills.add(skill)

        name_cell = f"[{title}]({verify_url})" if verify_url else title
        row_text = f"| {date_str} | {name_cell} | {issuer} | {v_type} |"
        formatted_rows.append((row_text, date_str))

    native_count = sum(1 for b in sorted_badges if b.get("type") == "Credly Verified")
    external_count = sum(1 for b in sorted_badges if b.get("type") == "External/Imported")
    total_count = len(sorted_badges)
    total_skills = len(all_skills)

    # Detect markers in README.md
    marker_start = "<!-- CREDLY_START -->"
    marker_end = "<!-- CREDLY_END -->"
    if os.path.exists("README.md"):
        with open("README.md", "r", encoding="utf-8") as f:
            content = f.read()
        if "<!-- CREDLY_BADGES_START -->" in content:
            marker_start = "<!-- CREDLY_BADGES_START -->"
            marker_end = "<!-- CREDLY_BADGES_END -->"

    readme_lines = [
        "### Credly Credentials",
        "",
        "[Credly Verified Credentials](https://www.credly.com/users/vojislavmiloradovic/badges)",
        "",
        "Public Profile: [Verify Credly Profile](https://www.credly.com/users/vojislavmiloradovic/badges)",
        f"**Total Portfolio Credentials:** {total_count} ({native_count} Credly Verified, {external_count} External/Imported)",
        f"**Total Verified Skills Mapped:** {total_skills}",
        "",
        "#### Latest Earned Credentials",
        "",
        f"Showing latest 10 of {total_count} credentials. View the full dataset via the [Platform Archive Index](./archives/credly-badges-index.md) ([Raw Index](https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-badges-index.md)), latest slice [Part 01 Raw](https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/credly-badges-2026-07-part-01.md), or the [Monolithic Complete File](./archives/credly-badges-complete.md).",
        "",
        "| Date Earned | Credential Name | Issuer | Verification Type |",
        "| :---: | :--- | :--- | :---: |",
    ]

    for row_text, _ in formatted_rows[:10]:
        readme_lines.append(row_text)

    headers = ["Date Earned", "Credential Name", "Issuer", "Verification Type"]
    alignments = [":---:", ":---", ":---", ":---:"]

    logger.info("🔄 Generating archive files and updating README.md...")
    generate_platform_archive(
        platform_prefix="credly-badges",
        platform_name="Credly Verified Credentials",
        table_headers=headers,
        table_alignments=alignments,
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=marker_start,
        marker_end=marker_end,
    )
    logger.info("✅ Archives and README.md updated successfully.")


def main():
    logger.info("Starting Credly Sync Script...")
    native_badges = fetch_native_badges(CREDLY_USERNAME)
    external_badges = fetch_external_badges(CREDLY_USER_ID)
    unique_badges = merge_and_save_badges(native_badges, external_badges, OUTPUT_FILE)
    build_archives_and_readme(unique_badges)
    logger.info("Sync completed successfully.")


if __name__ == "__main__":
    main()
