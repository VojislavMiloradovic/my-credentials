import os
import json
import glob

DATA_DIR = "data"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

TITLE_KEYS = ["title", "name", "badgetitle", "coursetitle", "activitytitle", "certificationtitle", "displayname"]
DATE_KEYS = ["awardedon", "issuedon", "grantedon", "completedon", "completeddate", "date", "earneddate", "issued_at", "created_at"]
URL_KEYS = ["url", "badgeurl", "verificationurl", "link", "badge_url", "credential_url"]
ID_KEYS = ["credentialid", "badgeid", "id", "identifier", "sourceuid"]

def deep_find_value(obj, target_keys):
    """Recursively search a nested dict or list for matching target keys."""
    if isinstance(obj, dict):
        # 1. Check direct keys first
        for k, v in obj.items():
            if k.lower() in target_keys and v:
                if isinstance(v, (str, int, float)):
                    return str(v)
        # 2. Check nested dicts/lists
        for v in obj.values():
            if isinstance(v, (dict, list)):
                res = deep_find_value(v, target_keys)
                if res:
                    return res
    elif isinstance(obj, list):
        for item in obj:
            res = deep_find_value(item, target_keys)
            if res:
                return res
    return None

def find_all_credential_dicts(data):
    """Finds all dictionary objects inside JSON data that represent a badge/credential/activity."""
    items = []

    def recurse(node):
        if isinstance(node, list):
            for elem in node:
                recurse(elem)
        elif isinstance(node, dict):
            title_found = deep_find_value(node, TITLE_KEYS)
            if title_found and len(title_found) > 2:
                items.append(node)
            else:
                for v in node.values():
                    if isinstance(v, (dict, list)):
                        recurse(v)

    recurse(data)
    return items

def parse_credential_item(item, default_issuer):
    title = deep_find_value(item, TITLE_KEYS)
    if not title:
        return None

    # Clean up Microsoft raw source UIDs if present
    if "applied-skill" in str(title) or "learn.wwl" in str(title):
        title = " ".join(str(title).replace("applied-skill.", "").replace("learn.wwl.", "").split("-")).title()

    date_earned = deep_find_value(item, DATE_KEYS) or ""
    if date_earned and "T" in str(date_earned):
        date_earned = str(date_earned).split("T")[0]

    url = deep_find_value(item, URL_KEYS) or ""
    cred_id = deep_find_value(item, ID_KEYS) or ""

    c_obj = {
        "@type": "EducationalOccupationalCredential",
        "credentialCategory": "Badge/Certification",
        "name": str(title).strip(),
        "recognizedBy": {
            "@type": "Organization",
            "name": default_issuer
        }
    }

    if cred_id and str(cred_id) != "N/A":
        c_obj["identifier"] = str(cred_id)
    if date_earned:
        c_obj["dateCreated"] = str(date_earned)
    if url and str(url).startswith("http"):
        c_obj["url"] = str(url)

    return c_obj

def extract_all_credentials():
    credentials = []

    if not os.path.exists(DATA_DIR):
        print(f"⚠️ Directory '{DATA_DIR}' not found.")
        return credentials

    json_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    print(f"🔍 Found {len(json_files)} JSON file(s) in '{DATA_DIR}':")

    for json_file in json_files:
        filename = os.path.basename(json_file)
        platform_name = filename.replace(".json", "").replace("-", " ").title()

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            candidate_dicts = find_all_credential_dicts(data)
            added_from_file = 0

            for item in candidate_dicts:
                parsed = parse_credential_item(item, platform_name)
                if parsed:
                    credentials.append(parsed)
                    added_from_file += 1

            print(f"  ├─ 📄 {filename}: Parsed {added_from_file} credential(s)")

        except Exception as e:
            print(f"  ├─ ⚠️ Error parsing {filename}: {e}")

    return credentials

def cleanup_readme():
    """Removes embedded JSON-LD script blocks from README.md to keep it clean."""
    if not os.path.exists(README_PATH):
        return

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Fix character encoding issues if present
    content = content.replace("Vojislav Miloradoviﾄ", "Vojislav Miloradović")

    # Remove embedded script tags between markers
    if MARKER_START in content and MARKER_END in content:
        split_start = content.split(MARKER_START)
        split_end = split_start[1].split(MARKER_END)
        content = split_start[0].strip() + "\n\n" + split_end[1].lstrip()

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"🧹 Ensured {README_PATH} is clean of embedded script blocks.")

def main():
    credentials = extract_all_credentials()
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

    print(f"✅ Successfully generated {JSONLD_PATH} with {len(credentials)} total credential(s).")
    cleanup_readme()

if __name__ == "__main__":
    main()
