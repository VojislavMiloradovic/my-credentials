"""
update_credly_badges.py
-----------------------
Fetches all native Credly badges and external Open Badges, merges them,
saves output to credly_badges.json, generates platform archives,
and updates README.md via archiver helper.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

# Fallback import handling for archiver module
generate_platform_archive = None
for module_name in ("archiver", "archiver_2", "archive_utils"):
    try:
        mod = __import__(module_name, fromlist=["generate_platform_archive"])
        generate_platform_archive = mod.generate_platform_archive
        break
    except (ImportError, AttributeError):
        continue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("credly_updater")

# Profile Identifiers
CREDLY_USERNAME = os.getenv("CREDLY_USERNAME", "vojislavmiloradovic")
CREDLY_USER_ID = os.getenv("CREDLY_USER_ID", "752aee40-7358-4ade-9a49-81e8b6f49225")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "credly_badges.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_date(raw_date: Any) -> str | None:
    """Extracts YYYY-MM-DD from ISO strings, UNIX timestamps, or formatted date strings."""
    if raw_date is None or raw_date == "" or raw_date == "N/A" or raw_date == "None":
        return None

    # Handle numeric UNIX timestamp (int/float)
    if isinstance(raw_date, (int, float)):
        try:
            ts = float(raw_date)
            if ts > 1e11:  # Milliseconds timestamp
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    s_date = str(raw_date).strip()
    if not s_date or s_date.lower() in ("none", "null", "n/a"):
        return None

    # Handle numeric timestamp strings (e.g. "1700000000")
    if s_date.isdigit():
        try:
            ts = float(s_date)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None

    # Handle standard ISO string splits e.g. "2026-03-25T14:30:00Z"
    parts = s_date.split("T")[0].split(" ")[0]
    if len(parts) == 10 and parts[4] == "-" and parts[7] == "-":
        return parts

    # Parse common human-readable date strings (e.g., "Feb 7, 2026", "March 15, 2026")
    for fmt in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s_date, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(s_date.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    return None


def extract_title(item: dict[str, Any]) -> str:
    """Deeply extracts title across native and Open Badges v2 payload structures."""
    GENERIC_TITLES = {"external badge", "external credential", "badge", "credential"}
    candidates = []

    # 1. Check Open Badges v2 badge_class object
    bc = item.get("badge_class")
    if isinstance(bc, dict):
        candidates.extend([bc.get("name"), bc.get("title")])

    # 2. Check direct item keys
    for k in ("title", "name", "badge_name", "badge_template_name"):
        candidates.append(item.get(k))

    # 3. Check badge object
    badge = item.get("badge")
    if isinstance(badge, dict):
        candidates.extend([badge.get("name"), badge.get("title")])
        badge_bc = badge.get("badge_class")
        if isinstance(badge_bc, dict):
            candidates.extend([badge_bc.get("name"), badge_bc.get("title")])

    # 4. Check badge_template object
    bt = item.get("badge_template")
    if isinstance(bt, dict):
        candidates.extend([bt.get("name"), bt.get("title")])

    # 5. Check assertion object
    assertion = item.get("assertion")
    if isinstance(assertion, dict):
        candidates.extend([assertion.get("name"), assertion.get("title")])
        a_badge = assertion.get("badge")
        if isinstance(a_badge, dict):
            candidates.extend([a_badge.get("name"), a_badge.get("title")])
            a_bc = a_badge.get("badge_class")
            if isinstance(a_bc, dict):
                candidates.extend([a_bc.get("name"), a_bc.get("title")])

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            clean = cand.strip()
            if clean.lower() not in GENERIC_TITLES:
                return clean

    return "External Credential"


def extract_issuer(item: dict[str, Any]) -> str:
    """Deeply extracts issuer name across native and external open badge payloads."""
    GENERIC_ISSUERS = {"external issuer", "credly issuer", "credly", "issuer"}
    candidates = []

    # 1. Check badge_class issuer
    bc = item.get("badge_class")
    if isinstance(bc, dict):
        bc_issuer = bc.get("issuer")
        if isinstance(bc_issuer, dict):
            candidates.extend([bc_issuer.get("name"), bc_issuer.get("title")])
        elif isinstance(bc_issuer, str):
            candidates.append(bc_issuer)

    # 2. Direct keys
    for k in ("issuer_name", "issuer_organization_name"):
        candidates.append(item.get(k))

    raw_issuer = item.get("issuer")
    if isinstance(raw_issuer, str):
        candidates.append(raw_issuer)
    elif isinstance(raw_issuer, dict):
        candidates.append(raw_issuer.get("name"))
        entities = raw_issuer.get("entities", [])
        if isinstance(entities, list) and entities and isinstance(entities[0], dict):
            ent = entities[0].get("entity")
            if isinstance(ent, dict):
                candidates.append(ent.get("name"))

    # 3. Check badge / badge_template
    for parent_key in ("badge", "badge_template"):
        parent = item.get(parent_key)
        if isinstance(parent, dict):
            p_issuer = parent.get("issuer")
            if isinstance(p_issuer, str):
                candidates.append(p_issuer)
            elif isinstance(p_issuer, dict):
                candidates.append(p_issuer.get("name"))

    # 4. Check assertion
    assertion = item.get("assertion")
    if isinstance(assertion, dict):
        a_badge = assertion.get("badge")
        if isinstance(a_badge, dict):
            iss = a_badge.get("issuer")
            if isinstance(iss, dict):
                candidates.append(iss.get("name"))
            elif isinstance(iss, str):
                candidates.append(iss)

    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            clean = cand.strip()
            if clean.lower() not in GENERIC_ISSUERS:
                return clean

    return "External Issuer"


def extract_date(item: dict[str, Any]) -> str:
    """Deeply extracts issue/earned date across native and external badge payloads."""
    candidates = [
        item.get("issued_at_date"),
        item.get("issued_at"),
        item.get("issued_on"),
        item.get("issuedOn"),
        item.get("issued_date"),
        item.get("created_at"),
        item.get("earned_at"),
        item.get("updated_at"),
    ]

    bc = item.get("badge_class")
    if isinstance(bc, dict):
        candidates.extend([
            bc.get("issued_at"),
            bc.get("issued_on"),
            bc.get("issuedOn"),
        ])

    assertion = item.get("assertion")
    if isinstance(assertion, dict):
        candidates.extend([
            assertion.get("issuedOn"),
            assertion.get("issued_on"),
            assertion.get("issued_at"),
            assertion.get("issued_at_date"),
        ])

    badge = item.get("badge")
    if isinstance(badge, dict):
        candidates.extend([
            badge.get("issued_at"),
            badge.get("issued_at_date"),
            badge.get("issuedOn"),
            badge.get("issued_on"),
        ])

    for c in candidates:
        norm = normalize_date(c)
        if norm:
            return norm

    # Fallback to current UTC date if date is completely unparseable
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def extract_verify_url(item: dict[str, Any]) -> str | None:
    """Extracts verification or public badge URL."""
    candidates = [
        item.get("verify_url"),
        item.get("public_url"),
        item.get("url"),
        item.get("target_url"),
        item.get("assertion_url"),
        item.get("badge_url"),
    ]

    assertion = item.get("assertion")
    if isinstance(assertion, str) and assertion.startswith("http"):
        candidates.append(assertion)
    elif isinstance(assertion, dict):
        candidates.extend([
            assertion.get("id"),
            assertion.get("verify_url"),
            assertion.get("url"),
        ])

    badge_id = item.get("id") or item.get("uuid")
    if isinstance(badge_id, str) and badge_id.startswith("http"):
        candidates.append(badge_id)

    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c.strip()

    if badge_id:
        return f"https://www.credly.com/badges/{badge_id}/public_url"

    return None


def extract_skills(item: dict[str, Any]) -> list[str]:
    """Extracts skills list safely from strings or dictionary objects."""
    skills = []

    def process_skill(s: Any):
        if isinstance(s, str) and s.strip():
            skills.append(s.strip())
        elif isinstance(s, dict):
            val = s.get("name") or s.get("title") or s.get("id")
            if isinstance(val, str) and val.strip():
                skills.append(val.strip())

    raw_skills = (
        item.get("skills")
        or (item.get("badge_template", {}).get("skills") if isinstance(item.get("badge_template"), dict) else None)
        or (item.get("badge_class", {}).get("skills") if isinstance(item.get("badge_class"), dict) else None)
        or (item.get("badge", {}).get("skills") if isinstance(item.get("badge"), dict) else None)
    )

    if isinstance(raw_skills, list):
        for s in raw_skills:
            process_skill(s)
    elif isinstance(raw_skills, str):
        skills.append(raw_skills.strip())

    return list(dict.fromkeys(skills))


def fetch_native_badges(username: str) -> list[dict[str, Any]]:
    """Fetches native Credly badges across all pages."""
    badges = []
    page = 1

    logger.info(f"🔄 Starting native badge fetch for user '{username}'...")

    while True:
        url = f"https://www.credly.com/users/{username}/badges.json"
        params = {"page": page}

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
                title = extract_title(badge)
                issuer_name = extract_issuer(badge)
                issued_at = extract_date(badge)
                verify_url = extract_verify_url(badge)
                skills = extract_skills(badge)
                badge_id = badge.get("id")

                parsed_badge = {
                    "id": badge_id,
                    "title": title,
                    "name": title,
                    "issuer": issuer_name,
                    "issuer_name": issuer_name,
                    "issued_at": issued_at,
                    "issued_at_date": issued_at,
                    "date": issued_at,
                    "expires_at": normalize_date(badge.get("expires_at_date") or badge.get("expires_at")),
                    "image_url": badge.get("image_url") or (badge.get("badge_template", {}).get("image_url") if isinstance(badge.get("badge_template"), dict) else None),
                    "verify_url": verify_url,
                    "url": verify_url,
                    "type": "Credly Verified",
                    "verification_type": "Credly Verified",
                    "skills": skills,
                }
                badges.append(parsed_badge)

            metadata = data.get("metadata", {})
            total_pages = metadata.get("total_pages")
            if total_pages is not None:
                if page >= total_pages:
                    break
            else:
                if len(raw_badges) == 0:
                    break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to fetch native badges on page {page}: {e}")
            break

    logger.info(f"✅ Finished native badge fetch: {len(badges)} native badges total across {page} page(s).")
    return badges


def fetch_external_badges(user_id: str) -> list[dict[str, Any]]:
    """Fetches public external/imported Open Badges from Credly endpoint."""
    url = f"https://www.credly.com/api/v1/users/{user_id}/external_badges/open_badges/public"
    logger.info("🔄 Fetching external open badges from public endpoint...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
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

            # Extract from nested 'external_badge' dictionary
            ext_badge = item.get("external_badge") or {}
            
            title = (
                ext_badge.get("badge_name")
                or ext_badge.get("name")
                or item.get("title")
                or "External Credential"
            )
            
            issuer_name = (
                ext_badge.get("issuer_name")
                or item.get("issuer_name")
                or "External Issuer"
            )

            issued_at = (
                ext_badge.get("issued_at_date")
                or ext_badge.get("issued_at")
                or item.get("issued_at")
            )
            normalized_date = normalize_date(issued_at)

            expires_at = normalize_date(
                ext_badge.get("expires_at_date") or ext_badge.get("expires_at")
            )

            verify_url = (
                ext_badge.get("badge_url")
                or ext_badge.get("badge_id")
                or item.get("verify_url")
            )

            image_url = ext_badge.get("image_url") or item.get("image_url")
            badge_id = item.get("id") or ext_badge.get("credly_record_id")

            # Parse skills from external_badge or top level item
            skills_raw = ext_badge.get("skills", []) or item.get("skills", [])
            skills = [s.get("name") for s in skills_raw if isinstance(s, dict) and s.get("name")]

            parsed_external.append({
                "id": badge_id,
                "title": title,
                "name": title,
                "issuer": issuer_name,
                "issuer_name": issuer_name,
                "issued_at": normalized_date,
                "issued_at_date": normalized_date,
                "date": normalized_date,
                "expires_at": expires_at,
                "image_url": image_url,
                "verify_url": verify_url,
                "url": verify_url,
                "type": "External/Imported",
                "verification_type": "External/Imported",
                "skills": skills,
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
    """Generates markdown archive files and updates README.md via archiver helper."""
    if not generate_platform_archive:
        logger.error("❌ Archiver module could not be imported. Please verify archiver.py exists.")
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
        date_str = b.get("issued_at") or "2026-01-01"
        title = b.get("title") or "Unknown Credential"
        verify_url = b.get("verify_url")
        issuer = b.get("issuer") or "Credly"
        v_type = b.get("type") or "Credly Verified"

        for skill in b.get("skills", []):
            if isinstance(skill, str) and skill.strip():
                all_skills.add(skill.strip())

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
