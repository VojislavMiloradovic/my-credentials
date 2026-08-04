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


def extract_table_data_rows(lines: list[str]) -> list[tuple[list[str], list[str]]]:
    """Extracts header columns and cell contents from Markdown tables using separator-anchored parsing."""
    data_rows = []
    cleaned_lines = [line.strip() for line in lines]
    separator_re = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")

    i = 0
    while i < len(cleaned_lines):
        line = cleaned_lines[i]
        if line.startswith("|") and line.endswith("|"):
            if (i + 1) < len(cleaned_lines) and separator_re.match(cleaned_lines[i + 1]):
                header_cols = [c.strip().lower() for c in line.split("|")[1:-1]]
                i += 2  # Skip header row and separator row
                while i < len(cleaned_lines):
                    row_line = cleaned_lines[i]
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    if separator_re.match(row_line):
                        i += 1
                        continue
                    cols = [c.strip() for c in row_line.split("|")[1:-1]]
                    if cols:
                        data_rows.append((header_cols, cols))
                    i += 1
                continue
            elif separator_re.match(line):
                i += 1
                continue
        i += 1

    return data_rows


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

        table_rows = extract_table_data_rows(lines)

        for header_cols, cols in table_rows:
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

                img_match = re.search(r"!\[.*?\]\((https?://[^\)]+)\)", col)
                if img_match and not image_url:
                    image_url = img_match.group(1)

                link_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", col)
                if link_match:
                    if not url:
                        url = link_match.group(2)
                    if not title and "Verify" not in link_match.group(1):
                        title = clean_str(link_match.group(1))

                bold_match = re.search(r"\*\*([^*]+)\*\*", col)
                if bold_match and not title and "title" in col_header:
                    title = clean_str(bold_match.group(1))

                date_match = re.search(r"\b(20\d{2}-\d{2}(-\d{2})?)\b", col)
                if date_match and not date_earned:
                    date_earned = date_match.group(1)

                if "category" in col_header or "type" in col_header:
                    cleaned_cat = clean_str(col)
                    if cleaned_cat and cleaned_cat.lower() not in ["verify", "active"]:
                        category = cleaned_cat

                if "issuer" in col_header or "authority" in col_header:
                    cleaned_issuer = clean_str(col)
                    if cleaned_issuer:
                        issuer = cleaned_issuer
                elif "issued by" in col.lower():
                    issuer = col.replace("issued by", "").replace("`", "").strip()

                if "description" in col_header:
                    cleaned_desc = clean_str(col)
                    if cleaned_desc and cleaned_desc.lower() != title.lower():
                        description = cleaned_desc

                id_match = re.search(r"Credential ID:\s*`?([A-Za-z0-9]+)`?", col, re.IGNORECASE)
                if id_match and not cred_id:
                    cred_id = id_match.group(1)

            if not title and cols:
                for col in cols:
                    c_clean = clean_str(col)
                    if c_clean and not re.match(r"^\d{4}-\d{2}(-\d{2})?$", c_clean):
                        title = c_clean
                        break

            if title:
                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": category,
                    "name": clean_str(title),
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
