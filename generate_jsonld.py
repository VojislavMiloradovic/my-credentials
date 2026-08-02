import glob
import json
import os
import re
import sys

import jsonschema

ARCHIVE_DIR = "archives"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

HEADER_WORDS = {
    "date", "earned", "credential", "name", "title", "issuer", 
    "verification", "type", "badge", "category", "description", 
    "authority", "issued", "status", "id", "link", "url", "action", "verify"
}

JSONLD_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "@context": {"type": "string"},
        "@type": {"type": "string"},
        "mainEntity": {
            "type": "object",
            "properties": {
                "@type": {"type": "string"},
                "name": {"type": "string"},
                "url": {"type": "string"},
                "hasCredential": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "@type": {"type": "string"},
                            "credentialCategory": {"type": "string"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "image": {"type": "string"},
                            "identifier": {"type": "string"},
                            "dateCreated": {"type": "string"},
                            "expires": {"type": "string"},
                            "recognizedBy": {
                                "type": "object",
                                "properties": {
                                    "@type": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                                "required": ["@type", "name"],
                            },
                        },
                        "required": ["@type", "name", "recognizedBy"],
                    },
                },
            },
            "required": ["@type", "name", "hasCredential"],
        },
    },
    "required": ["@context", "@type", "mainEntity"],
}


def clean_str(s):
    if not s:
        return ""
    return re.sub(r"[\*\_`]", "", str(s)).strip()


def is_header_phrase(text):
    """Checks if a string consists entirely of table header keywords."""
    words = re.findall(r"\w+", clean_str(text).lower())
    if not words:
        return True
    return all(w in HEADER_WORDS for w in words)


def validate_jsonld(payload):
    """Validates generated JSON-LD object against the defined schema before writing."""
    try:
        jsonschema.validate(instance=payload, schema=JSONLD_SCHEMA)
        print("✓ JSON-LD Schema Validation Passed successfully.")
    except jsonschema.exceptions.ValidationError as e:
        print(f"❌ JSON-LD Validation Error: {e.message}", file=sys.stderr)
        sys.exit(1)
    except jsonschema.exceptions.SchemaError as e:
        print(f"❌ JSON Schema Error: {e.message}", file=sys.stderr)
        sys.exit(1)


def parse_archive_monoliths():
    """Parses standardized complete markdown archives across all platforms into credential dictionaries."""
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

        header_cols = []
        num_lines = len(lines)

        for i in range(num_lines):
            line_str = lines[i].strip()
            if not line_str:
                continue

            # Peek at next line for Markdown table delimiter (| --- | --- |)
            next_line_str = lines[i + 1].strip() if i + 1 < num_lines else ""

            # -----------------------------------------------------------------
            # 1. Parse Table Rows (| col1 | col2 | col3 |)
            # -----------------------------------------------------------------
            if line_str.startswith("|") and line_str.endswith("|"):
                # Skip separator lines
                if "---" in line_str:
                    continue

                cols = [c.strip() for c in line_str.split("|")[1:-1]]
                if not cols or len(cols) < 2:
                    continue

                # Header Guard 1: If next line is a delimiter (---), this line is a header
                if "---" in next_line_str and next_line_str.startswith("|"):
                    header_cols = [c.strip().lower() for c in cols]
                    continue

                # Header Guard 2: Check if row consists purely of header phrases
                if all(is_header_phrase(c) for c in cols if c):
                    header_cols = [c.strip().lower() for c in cols]
                    continue

                title = ""
                date_earned = ""
                url = ""
                issuer = platform_name
                category = "Badge/Certification"
                description = ""
                image_url = ""
                cred_id = ""

                for idx, col in enumerate(cols):
                    col_header = header_cols[idx] if idx < len(header_cols) else ""

                    # Extract image URL
                    img_match = re.search(r"!\[.*?\]\((https?://[^\)]+)\)", col)
                    if img_match and not image_url:
                        image_url = img_match.group(1)

                    # Extract link URL & title
                    link_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", col)
                    if link_match:
                        if not url:
                            url = link_match.group(2)
                        if not title and "verify" not in link_match.group(1).lower():
                            cand = clean_str(link_match.group(1))
                            if not is_header_phrase(cand):
                                title = cand

                    # Extract bold title
                    bold_match = re.search(r"\*\*([^*]+)\*\*", col)
                    if bold_match and not title:
                        cand = clean_str(bold_match.group(1))
                        if not is_header_phrase(cand):
                            title = cand

                    # Extract ISO / Year-Month dates
                    date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", col)
                    if date_match and not date_earned:
                        date_earned = date_match.group(1)

                    # Category extraction
                    if "category" in col_header or "type" in col_header:
                        cleaned_cat = clean_str(col)
                        if cleaned_cat and cleaned_cat.lower() not in ["verify", "active"]:
                            category = cleaned_cat

                    # Issuer extraction
                    if "issuer" in col_header:
                        cleaned_issuer = clean_str(col)
                        if cleaned_issuer and not is_header_phrase(cleaned_issuer):
                            issuer = cleaned_issuer
                    elif "issued by" in col.lower():
                        issuer = col.replace("issued by", "").replace("`", "").strip()

                    # Description extraction
                    if "description" in col_header:
                        cleaned_desc = clean_str(col)
                        if cleaned_desc and cleaned_desc.lower() != title.lower():
                            description = cleaned_desc

                    # Credential ID extraction
                    id_match = re.search(r"Credential ID:\s*`?([A-Za-z0-9]+)`?", col, re.IGNORECASE)
                    if id_match and not cred_id:
                        cred_id = id_match.group(1)

                # Fallback: Plain-text title in first/second column if not header
                if not title:
                    for c in cols:
                        cand = clean_str(c)
                        if cand and not is_header_phrase(cand):
                            title = cand
                            break

                if title and not is_header_phrase(title):
                    c_obj = {
                        "@type": "EducationalOccupationalCredential",
                        "credentialCategory": category,
                        "name": title,
                        "recognizedBy": {
                            "@type": "Organization",
                            "name": clean_str(issuer),
                        },
                    }
                    if description:
                        c_obj["description"] = description
                    if image_url:
                        c_obj["image"] = image_url
                    if cred_id:
                        c_obj["identifier"] = cred_id
                    if date_earned:
                        c_obj["dateCreated"] = date_earned
                    if url:
                        c_obj["url"] = url

                    credentials.append(c_obj)
                    count += 1

            # -----------------------------------------------------------------
            # 2. Parse Bullet Points (- Title / * Title)
            # -----------------------------------------------------------------
            elif line_str.startswith(("- ", "* ", "+ ")):
                bold_match = re.search(r"\*\*([^*]+)\*\*", line_str)
                link_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line_str)

                if bold_match:
                    title = clean_str(bold_match.group(1))
                elif link_match and "verify" not in link_match.group(1).lower():
                    title = clean_str(link_match.group(1))
                else:
                    raw_text = re.sub(r"^[-*\+]\s+", "", line_str)
                    title = clean_str(raw_text.split(" - ")[0].split(" (")[0])

                if not title or is_header_phrase(title):
                    continue

                date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", line_str)
                date_earned = date_match.group(1) if date_match else ""

                url = link_match.group(2) if link_match else ""

                img_match = re.search(r"!\[.*?\]\((https?://[^\)]+)\)", line_str)
                image_url = img_match.group(1) if img_match else ""

                id_match = re.search(r"Credential ID:\s*`?([A-Za-z0-9]+)`?", line_str, re.IGNORECASE)
                cred_id = id_match.group(1) if id_match else ""

                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": "Badge/Certification",
                    "name": title,
                    "recognizedBy": {
                        "@type": "Organization",
                        "name": platform_name,
                    },
                }
                if cred_id:
                    c_obj["identifier"] = cred_id
                if image_url:
                    c_obj["image"] = image_url
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
            "hasCredential": credentials,
        },
    }

    validate_jsonld(payload)

    with open(JSONLD_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Successfully generated {JSONLD_PATH} with {len(credentials)} total credential(s).")
    cleanup_readme()


if __name__ == "__main__":
    main()
