import os
import re
import json
import glob

ARCHIVE_DIR = "archives"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

def clean_str(s):
    if not s:
        return ""
    # Strip markdown bold/italic formatting and code backticks
    return re.sub(r"[\*\_`]", "", str(s)).strip()

def parse_archive_monoliths():
    """Parses standardized complete markdown archives across all platforms into JSON-LD objects."""
    credentials = []

    if not os.path.exists(ARCHIVE_DIR):
        print(f"⚠️ Archive directory '{ARCHIVE_DIR}' not found.")
        return credentials

    monolith_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*-complete.md")))
    print(f"🔍 Found {len(monolith_files)} complete archive dataset(s) in '{ARCHIVE_DIR}':")

    for filepath in monolith_files:
        filename = os.path.basename(filepath)
        platform_name = filename.replace("-complete.md", "").replace("-", " ").title()
        count = 0

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # -----------------------------------------------------------------
            # 1. Parse Table Rows (| col1 | col2 | col3 |)
            # -----------------------------------------------------------------
            if line_str.startswith("|") and line_str.endswith("|"):
                # Skip table header and separator rows
                if "---" in line_str or "Date" in line_str or "Metric" in line_str or "Stat" in line_str:
                    continue

                cols = [c.strip() for c in line_str.split("|")[1:-1]]
                if not cols or len(cols) < 2:
                    continue

                title = ""
                date_earned = ""
                url = ""
                issuer = platform_name

                for col in cols:
                    # Extract verification URL
                    link_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", col)
                    if link_match:
                        if not url:
                            url = link_match.group(2)
                        if not title and "Verify" not in link_match.group(1):
                            title = clean_str(link_match.group(1))

                    # Extract bold text title
                    bold_match = re.search(r"\*\*([^*]+)\*\*", col)
                    if bold_match and not title:
                        title = clean_str(bold_match.group(1))

                    # Extract ISO / Year-Month dates
                    date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", col)
                    if date_match and not date_earned:
                        date_earned = date_match.group(1)

                    # Extract explicit issuer if specified (e.g., Credly "issued by XYZ")
                    if "issued by" in col.lower():
                        issuer = col.replace("issued by", "").replace("`", "").strip()

                if title:
                    c_obj = {
                        "@type": "EducationalOccupationalCredential",
                        "credentialCategory": "Badge/Certification",
                        "name": clean_str(title),
                        "recognizedBy": {
                            "@type": "Organization",
                            "name": clean_str(issuer)
                        }
                    }
                    if date_earned:
                        c_obj["dateCreated"] = date_earned
                    if url:
                        c_obj["url"] = url

                    credentials.append(c_obj)
                    count += 1

            # -----------------------------------------------------------------
            # 2. Parse Bullet Points (- **Title** ...)
            # -----------------------------------------------------------------
            elif line_str.startswith("- ") or line_str.startswith("* "):
                bold_match = re.search(r"\*\*([^*]+)\*\*", line_str)
                if not bold_match:
                    continue

                title = clean_str(bold_match.group(1))

                # Extract date
                date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", line_str)
                date_earned = date_match.group(1) if date_match else ""

                # Extract link
                link_match = re.search(r"\((https?://[^\)]+)\)", line_str)
                url = link_match.group(1) if link_match else ""

                # Extract Credential ID if present
                id_match = re.search(r"Credential ID:\s*`?([A-Za-z0-9]+)`?", line_str, re.IGNORECASE)
                cred_id = id_match.group(1) if id_match else ""

                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": "Badge/Certification",
                    "name": title,
                    "recognizedBy": {
                        "@type": "Organization",
                        "name": platform_name
                    }
                }
                if cred_id:
                    c_obj["identifier"] = cred_id
                if date_earned:
                    c_obj["dateCreated"] = date_earned
                if url:
                    c_obj["url"] = url

                credentials.append(c_obj)
                count += 1

        print(f"  ├─ 📄 {filename}: Extracted {count} credential(s)")

    return credentials

def cleanup_readme():
    """Ensures README.md stays clean without embedded script blocks."""
    if not os.path.exists(README_PATH):
        return

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Repair name encoding if needed
    content = content.replace("Vojislav Miloradoviﾄ", "Vojislav Miloradović")

    if MARKER_START in content and MARKER_END in content:
        split_start = content.split(MARKER_START)
        split_end = split_start[1].split(MARKER_END)
        content = split_start[0].strip() + "\n\n" + split_end[1].lstrip()

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"🧹 Ensured {README_PATH} is clean of embedded script blocks.")

def main():
    credentials = parse_archive_monoliths()

    payload = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": "Vojislav Miloradović",
            "url": "https://github.com/VojislavMiloradovic/my-credentials",
            "hasCredential": credentials
        }
    }

    with open(JSONLD_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Successfully generated {JSONLD_PATH} with {len(credentials)} total credential(s).")
    cleanup_readme()

if __name__ == "__main__":
    main()
