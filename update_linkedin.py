import csv
import os
import re
import sys
from datetime import datetime, timezone

from archiver import generate_platform_archive

README_PATH = "README.md"
ARCHIVE_DIR = "archives"
PLATFORM_PREFIX = "linkedin-certifications"
PLATFORM_NAME = "LinkedIn Certifications"
CERTIFICATIONS_CSV_PATH = "data/Certifications.csv"

MARKER_START = "<!-- LINKEDIN_START -->"
MARKER_END = "<!-- LINKEDIN_END -->"

MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
}

def parse_linkedin_date(date_str):
    if not date_str or str(date_str).strip().lower() in ['null', 'none', '']:
        return "N/A"
    
    clean_str = str(date_str).strip().lower()
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', clean_str)
    if iso_match:
        return iso_match.group(1)
        
    match = re.search(r'([a-z]{3,})\s+(\d{4})', clean_str)
    if match:
        month_part = match.group(1)[:3]
        year_part = match.group(2)
        month_num = MONTH_MAP.get(month_part, "00")
        return f"{year_part}-{month_num}"
    
    return "N/A"

def parse_certifications_csv():
    if not os.path.exists(CERTIFICATIONS_CSV_PATH):
        return []

    certs = []
    current_year_month = datetime.now(timezone.utc).strftime("%Y-%m")

    with open(CERTIFICATIONS_CSV_PATH, mode='r', encoding='utf-8-sig') as f:
        content = f.read()
        if not content.strip():
            return []

        lines = content.splitlines()
        delimiter = '\t' if '\t' in lines[0] else ','
        f.seek(0)

        reader = csv.DictReader(f, delimiter=delimiter)
        raw_rows = list(reader)

    total_raw = len(raw_rows)
    skipped = 0

    for idx, row in enumerate(raw_rows):
        name = (row.get('Name') or row.get('name') or "").strip()
        if not name:
            skipped += 1
            continue

        authority = (
            row.get('Authority') or row.get('authority') or "Unknown Issuer"
        ).strip()
        url = (row.get('Url') or row.get('url') or "").strip()
        license_num = (
            row.get('License Number') or row.get('license number') or ""
        ).strip()

        started = row.get('Started On') or row.get('started on')
        finished = row.get('Finished On') or row.get('finished on')

        issued_date = parse_linkedin_date(started)
        expiry_date = parse_linkedin_date(finished)

        if (
            issued_date != "N/A"
            and issued_date > current_year_month
            and expiry_date != "N/A"
            and expiry_date <= current_year_month
        ):
            issued_date, expiry_date = expiry_date, issued_date

        certs.append({
            "name": name,
            "authority": authority,
            "issued": issued_date,
            "url": url,
            "license": license_num,
            "original_order": idx,
        })

    if skipped:
        print(
            f"⚠️  Skipped {skipped} row(s) out of {total_raw} with missing name.",
            file=sys.stderr,
        )

    return certs

def main():
    certs = parse_certifications_csv()
    if not certs:
        sys.exit(1)

    total_certs = len(certs)
    certs.sort(key=lambda x: x["original_order"], reverse=True)
    certs.sort(key=lambda x: x.get("issued") if x.get("issued") != "N/A" else "0000-00", reverse=True)

    table_headers = ["Date Completed", "Certification Title", "Issuing Authority", "Verification Reference"]
    table_alignments = [":---:", ":---", ":---", ":---"]

    formatted_rows = []
    for c in certs:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "Verified Account Entry")
        row_text = f"| {c['issued']} | **{clean_name}** | {clean_auth} | {ref} |"
        formatted_rows.append((row_text, c['issued']))

    readme_lines = [
        "### LinkedIn Professional Certifications Summary",
        "#### Progress Metrics",
        "| Metric | Count |",
        "| :--- | :--- |",
        f"| **Total External Certifications Verified** | {total_certs:,} |",
        "",
        "#### Recent Certifications",
        f"Showing latest 10 items. View the full dataset via the [Platform Archive Index](./archives/{PLATFORM_PREFIX}-index.md) ([Raw Index](https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives/{PLATFORM_PREFIX}-index.md)) or [Monolithic Complete File](./archives/{PLATFORM_PREFIX}-complete.md).\n",
        "| Date | Certification Title | Issuing Authority | Credentials Reference |",
        "| :---: | :--- | :--- | :--- |"
    ]

    for c in certs[:10]:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "N/A")
        readme_lines.append(f"| *{c['issued']}* | **{clean_name}** | {clean_auth} | {ref} |")

    generate_platform_archive(
        platform_prefix=PLATFORM_PREFIX,
        platform_name=PLATFORM_NAME,
        table_headers=table_headers,
        table_alignments=table_alignments,
        formatted_rows=formatted_rows,
        readme_lines=readme_lines,
        marker_start=MARKER_START,
        marker_end=MARKER_END,
        archive_dir=ARCHIVE_DIR,
        readme_path=README_PATH,
    )

if __name__ == "__main__":
    main()
