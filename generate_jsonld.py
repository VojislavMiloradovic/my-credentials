import os
import json
import glob

DATA_DIR = "data"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

def clean_text(text):
    if not text:
        return ""
    return str(text).strip()

def parse_credential_item(item, default_issuer):
    """Flexible parser that extracts title, date, URL, and identifier from varied JSON schemas."""
    if not isinstance(item, dict):
        return None

    # Determine title / name
    title = (
        item.get("title") or item.get("name") or item.get("badgeTitle") or 
        item.get("sourceUid") or item.get("activityTitle") or item.get("certificationTitle")
    )
    if not title:
        return None

    # Clean up Microsoft raw source UIDs
    if "applied-skill" in str(title) or "learn.wwl" in str(title):
        title = " ".join(str(title).replace("applied-skill.", "").replace("learn.wwl.", "").split("-")).title()

    # Determine earned date
    date_earned = (
        item.get("awardedOn") or item.get("issuedOn") or item.get("grantedOn") or 
        item.get("completedOn") or item.get("date") or item.get("earnedDate") or ""
    )
    if date_earned and "T" in str(date_earned):
        date_earned = str(date_earned).split("T")[0]

    # Determine verification URL & identifier
    url = item.get("url") or item.get("badgeUrl") or item.get("verificationUrl") or item.get("link") or ""
    cred_id = item.get("credentialId") or item.get("id") or item.get("badgeId") or ""
    
    issuer = item.get("issuer") or item.get("issuingAuthority") or item.get("recognizedBy") or default_issuer
    if isinstance(issuer, dict):
        issuer = issuer.get("name") or default_issuer

    c_obj = {
        "@type": "EducationalOccupationalCredential",
        "credentialCategory": "Badge/Certification",
        "name": clean_text(title),
        "recognizedBy": {
            "@type": "Organization",
            "name": clean_text(issuer)
        }
    }
    
    if cred_id and str(cred_id) != "N/A":
        c_obj["identifier"] = str(cred_id)
    if date_earned:
        c_obj["dateCreated"] = str(date_earned)
    if url:
        c_obj["url"] = str(url)

    return c_obj

def extract_all_credentials():
    credentials = []

    if not os.path.exists(DATA_DIR):
        print(f"⚠️ Directory '{DATA_DIR}' not found.")
        return credentials

    for json_file in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        filename = os.path.basename(json_file)
        platform_name = filename.replace(".json", "").replace("-", " ").title()

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Microsoft Learn nested structure
            if "microsoft" in filename:
                verifiable = data.get("VerifiableCredentials", {}).get("userCredentials", []) or []
                for vc in verifiable:
                    parsed = parse_credential_item(vc, "Microsoft")
                    if parsed:
                        parsed["credentialCategory"] = "Certification"
                        credentials.append(parsed)

                achievements = data.get("Achievements", []) or data.get("achievements", []) or []
                for ach in achievements:
                    parsed = parse_credential_item(ach, "Microsoft")
                    if parsed:
                        credentials.append(parsed)
                continue

            # Generic array or dict parser for Credly, Google, AWS, LinkedIn
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = (
                    data.get("badges") or data.get("certifications") or data.get("achievements") or 
                    data.get("data") or data.get("items") or data.get("courses") or data.get("activities") or []
                )
                if not items:
                    for val in data.values():
                        if isinstance(val, list):
                            items.extend(val)

            for item in items:
                parsed = parse_credential_item(item, platform_name)
                if parsed:
                    credentials.append(parsed)

        except Exception as e:
            print(f"⚠️ Error parsing {filename}: {e}")

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
        content = split_start[0].strip() + "\n" + split_end[1].lstrip()

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"🧹 Cleaned embedded script tags from {README_PATH}.")

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

    # Write full credentials.jsonld
    with open(JSONLD_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"✅ Successfully generated {JSONLD_PATH} with {len(credentials)} credentials.")
    
    # Strip script tag from README.md
    cleanup_readme()

if __name__ == "__main__":
    main()
