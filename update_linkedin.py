import os
import sys
import csv
import re

README_PATH = "README.md"
LINKEDIN_ARCHIVE_PATH = "archives/linkedin-certifications.md"
CERTIFICATIONS_CSV_PATH = "data/Certifications.csv"

MARKER_START = "<!-- LINKEDIN_START -->"
MARKER_END = "<!-- LINKEDIN_END -->"

MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
}

def parse_linkedin_date(date_str):
    """Standardizes LinkedIn date strings into ISO YYYY-MM-DD or YYYY-MM format."""
    if not date_str or str(date_str).strip().lower() in ['null', 'none', '']:
        return "N/A"
    
    clean_str = str(date_str).strip().lower()
    
    # Check if full YYYY-MM-DD already exists
    iso_match = re.search(r'(\d{4}-\d{2}-\d{2})', clean_str)
    if iso_match:
        return iso_match.group(1)
        
    # Check Month Year format (e.g. 'Feb 2026') -> '2026-02'
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
    current_year_month = "2026-07"

    with open(CERTIFICATIONS_CSV_PATH, mode='r', encoding='utf-8-sig') as f:
        content = f.read()
        if not content.strip():
            return []
            
        delimiter = '\t' if '\t' in content.splitlines()[0] else ','
        f.seek(0)
        
        reader = csv.DictReader(f, delimiter=delimiter)
        for idx, row in enumerate(reader):
            name = row.get('Name') or row.get('name')
            if not name:
                continue
                
            authority = row.get('Authority') or row.get('authority') or "Unknown Issuer"
            url = row.get('Url') or row.get('url') or ""
            license_num = row.get('License Number') or row.get('license number') or ""
            
            started = row.get('Started On') or row.get('started on')
            finished = row.get('Finished On') or row.get('finished on')
            
            issued_date = parse_linkedin_date(started)
            expiry_date = parse_linkedin_date(finished)
            
            if issued_date != "N/A" and issued_date > current_year_month:
                if expiry_date != "N/A" and expiry_date <= current_year_month:
                    issued_date, expiry_date = expiry_date, issued_date
                else:
                    expiry_date = issued_date
                    issued_date = current_year_month
            
            certs.append({
                "name": name.strip(),
                "authority": authority.strip(),
                "issued": issued_date,
                "url": url.strip(),
                "license": license_num.strip(),
                "original_order": idx
            })
            
    return certs

def main():
    certs = parse_certifications_csv()
    if not certs:
        sys.exit(1)
        
    total_certs = len(certs)
    certs.sort(key=lambda x: x["original_order"], reverse=True)
    certs.sort(key=lambda x: x.get("issued") if x.get("issued") != "N/A" else "0000-00", reverse=True)
    
    md = []
    md.append("### LinkedIn Professional Certifications Summary")
    md.append(f"#### Progress Metrics")
    md.append("| Metric | Count |")
    md.append("| :--- | :--- |")
    md.append(f"| **Total External Certifications Verified** | {total_certs:,} |")
    md.append("\n")
    
    md.append("#### Recent Certifications")
    md.append("Showing the latest 10 items. View complete historical logs in [LinkedIn Certifications archive](./archives/linkedin-certifications.md).\n")
    md.append("| Date | Certification Title | Issuing Authority | Credentials Reference |")
    md.append("| :---: | :--- | :--- | :--- |")
    
    for c in certs[:10]:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "N/A")
        md.append(f"| *{c['issued']}* | **{clean_name}** | {clean_auth} | {ref} |")
    md.append("\n")
    
    if os.path.exists(README_PATH):
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme_content = f.read()

        if MARKER_START in readme_content and MARKER_END in readme_content:
            parts_before = readme_content.split(MARKER_START)[0]
            parts_after = readme_content.split(MARKER_END)[1]
            new_readme = f"{parts_before}{MARKER_START}\n" + "\n".join(md) + f"{MARKER_END}{parts_after}"
            with open(README_PATH, "w", encoding="utf-8") as f:
                f.write(new_readme)
            
    archive_md = []
    archive_md.append("# Master LinkedIn Certifications History Log\n")
    archive_md.append(f"Historical record cataloging all {total_certs} verified external professional credentials.\n\n")
    archive_md.append("| Date Completed | Certification Title | Issuing Authority | Verification Reference |")
    archive_md.append("| :---: | :--- | :--- | :--- |")
    
    for c in certs:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "Verified Account Entry")
        archive_md.append(f"| {c['issued']} | **{clean_name}** | {clean_auth} | {ref} |")
        
    archive_md.append("\n\n[← Back to README](../README.md)\n")
    
    os.makedirs(os.path.dirname(LINKEDIN_ARCHIVE_PATH), exist_ok=True)
    with open(LINKEDIN_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))

if __name__ == "__main__":
    main()
