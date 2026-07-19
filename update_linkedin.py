import os
import sys
import csv
import re
from datetime import datetime

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
    """Standardizes LinkedIn date strings (e.g., 'Feb 2026') into AI-scannable YYYY-MM formats."""
    if not date_str or str(date_str).strip().lower() in ['null', 'none', '']:
        return "N/A"
    
    clean_str = str(date_str).strip().lower()
    match = re.search(r'([a-z]{3,})\s+(\d{4})', clean_str)
    if match:
        month_part = match.group(1)[:3]
        year_part = match.group(2)
        month_num = MONTH_MAP.get(month_part, "00")
        return f"{year_part}-{month_num}"
    
    return "N/A"

def parse_certifications_csv():
    """Reads and parses the LinkedIn certifications dump defensively with automatic delimiter sniffing."""
    if not os.path.exists(CERTIFICATIONS_CSV_PATH):
        print(f"❌ Error: Target file missing at expected path: {CERTIFICATIONS_CSV_PATH}")
        return []

    certs = []
    # Open with utf-8-sig to cleanly discard explicit Byte Order Mark configurations automatically
    with open(CERTIFICATIONS_CSV_PATH, mode='r', encoding='utf-8-sig') as f:
        content = f.read()
        if not content.strip():
            return []
            
        # Dynamically evaluate if the CSV layout utilizes traditional commas or copy-pasted tabs
        delimiter = '\t' if '\t' in content.splitlines()[0] else ','
        f.seek(0)
        
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            # Check for name fields safely across different spelling configurations
            name = row.get('Name') or row.get('name')
            if not name:
                continue
                
            authority = row.get('Authority') or row.get('authority') or "Unknown Issuer"
            url = row.get('Url') or row.get('url') or ""
            license_num = row.get('License Number') or row.get('license number') or ""
            
            # Prioritize completion dates, fallback to started dates if finished is empty
            finished = row.get('Finished On') or row.get('finished on')
            started = row.get('Started On') or row.get('started on')
            raw_date = finished if (finished and finished.strip()) else started
            
            iso_date = parse_linkedin_date(raw_date)
            
            certs.append({
                "name": name.strip(),
                "authority": authority.strip(),
                "date": iso_date,
                "url": url.strip(),
                "license": license_num.strip()
            })
            
    return certs

def main():
    certs = parse_certifications_csv()
    if not certs:
        print("❌ Process termination: No rows extracted from Certifications.csv profile asset.")
        sys.exit(1)
        
    total_certs = len(certs)
    print(f"✅ Successfully extracted {total_certs} credential entities from file.")
    
    # Sort chronologically, putting N/A records gracefully at the base line
    certs.sort(key=lambda x: x.get("date", "0000-00") if x.get("date") != "N/A" else "0000-00", reverse=True)
    
    # 1. Generate token-optimized entry snapshot block for README.md
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
        md.append(f"| *{c['date']}* | **{clean_name}** | {clean_auth} | {ref} |")
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
            print("✅ Main README.md targets updated successfully.")
            
    # 2. Update Complete Archive Log Document File
    archive_md = []
    archive_md.append("# Master LinkedIn Certifications History Log\n")
    archive_md.append(f"Historical record cataloging all {total_certs} verified external professional credentials.\n\n")
    archive_md.append("| Date Completed | Certification Title | Issuing Authority | Verification Reference |")
    archive_md.append("| :---: | :--- | :--- | :--- |")
    
    for c in certs:
        clean_name = c['name'].replace("|", "\\|")
        clean_auth = c['authority'].replace("|", "\\|")
        ref = f"[Verify Record]({c['url']})" if c['url'] else (c['license'] if c['license'] else "Verified Account Entry")
        archive_md.append(f"| {c['date']} | **{clean_name}** | {clean_auth} | {ref} |")
        
    archive_md.append("\n\n[← Back to README](../README.md)\n")
    
    os.makedirs(os.path.dirname(LINKEDIN_ARCHIVE_PATH), exist_ok=True)
    with open(LINKEDIN_ARCHIVE_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(archive_md))
    print("✅ Comprehensive certifications archive refreshed successfully!")

if __name__ == "__main__":
    main()
