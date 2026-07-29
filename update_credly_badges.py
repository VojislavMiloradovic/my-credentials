#!/usr/bin/env python3
"""
update_credly_badges.py
-----------------------
Fetches both native Credly badges and external Open Badges for a profile
using public endpoints, merges them, and saves the output to a JSON file.
"""

import json
import logging
import os
from typing import Any

import requests

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


def fetch_native_badges(username: str) -> list[dict[str, Any]]:
    """
    Fetches native Credly badges via the unauthenticated JSON profile route with pagination.
    Endpoint: https://www.credly.com/users/{username}/badges.json
    """
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

                parsed_badge = {
                    "id": badge_id,
                    "title": badge_template.get("name") or badge.get("name"),
                    "issuer": issuer_name,
                    "issued_at": badge.get("issued_at_date") or badge.get("issued_at"),
                    "expires_at": badge.get("expires_at_date") or badge.get("expires_at"),
                    "image_url": badge_template.get("image_url") or badge.get("image_url"),
                    "verify_url": f"https://www.credly.com/badges/{badge_id}/public_url" if badge_id else None,
                    "type": "Native Credly",
                    "skills": skills,
                }
                badges.append(parsed_badge)

            # Pagination check via API metadata
            metadata = data.get("metadata", {})
            total_pages = metadata.get("total_pages")
            if total_pages and page >= total_pages:
                break

            # Fallback pagination check
            if len(raw_badges) < page_size:
                break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to fetch native badges on page {page}: {e}")
            break

    logger.info(f"✅ Finished native badge fetch: {len(badges)} native badges total.")
    return badges


def fetch_external_badges(user_id: str) -> list[dict[str, Any]]:
    """
    Fetches public external/imported Open Badges for the user UUID.
    Endpoint: https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public
    """
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

            issued_at = (
                assertion.get("issuedOn")
                or item.get("issued_at")
                or item.get("issued_at_date")
            )

            badge_id = item.get("id") or item.get("uuid")

            parsed_external.append({
                "id": badge_id,
                "title": title,
                "issuer": issuer_name,
                "issued_at": issued_at,
                "expires_at": item.get("expires_at"),
                "image_url": badge_info.get("image") or item.get("image_url"),
                "verify_url": item.get("verify_url") or assertion.get("id"),
                "type": "External Open Badge",
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
):
    """Combines native and external badges, deduplicates, and saves output JSON."""
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


def main():
    logger.info("Starting Credly Sync Script...")
    native_badges = fetch_native_badges(CREDLY_USERNAME)
    external_badges = fetch_external_badges(CREDLY_USER_ID)
    merge_and_save_badges(native_badges, external_badges, OUTPUT_FILE)
    logger.info("Sync completed successfully.")


if __name__ == "__main__":
    main()
