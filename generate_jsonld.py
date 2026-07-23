import os
import json
import glob
import re

DATA_DIR = "data"
README_PATH = "README.md"
JSONLD_PATH = "credentials.jsonld"

MARKER_START = "<!-- JSONLD_START -->"
MARKER_END = "<!-- JSONLD_END -->"

def clean_uid(uid):
    if not uid:
        return ""
    parts = str(uid).replace("applied-skill.", "").replace("learn.wwl.", "").split("-")
    return " ".join(parts).title()

def extract_credentials():
    credentials = []

    # 1. Parse Microsoft Learn JSON
    ms_path = os.path.join(DATA_DIR, "microsoft-learn.json")
    if os.path.exists(ms_path):
        try:
            with open(ms_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            user_creds = data.get("VerifiableCredentials", {}).get("userCredentials", []) or []
            for cred in user_creds:
                name = clean_uid(cred.get("sourceUid", ""))
                cred_id = cred.get("credentialId", "")
                date_earned = cred.get("awardedOn", "").split("T")[0] if cred.get("awardedOn") else ""
                url = cred.get("url", "https://learn.microsoft.com/users/vojislavmiloradovic/")

                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": "Certification",
                    "name": name if name else "Microsoft Applied Skill / Certification",
                    "recognizedBy": {
                        "@type": "Organization",
                        "name": "Microsoft"
                    }
                }
                if cred_id and cred_id != "N/A":
                    c_obj["identifier"] = cred_id
                if date_earned:
                    c_obj["dateCreated"] = date_earned
                if url:
                    c_obj["url"] = url
                
                credentials.append(c_obj)
        except Exception as e:
            print(f"⚠️ Error parsing MS Learn JSON for JSON-LD: {e}")

    # 2. Generic Scanner for other platform JSONs (AWS, Credly, Google, LinkedIn)
    for json_file in glob.glob(os.path.join(DATA_DIR, "*.json")):
        filename = os.path.basename(json_file)
        if filename == "microsoft-learn.json":
            continue

        platform_name = filename.replace(".json", "").replace("-", " ").title()
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Look for arrays of items/badges/certs
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("badges") or data.get("certifications") or data.get("achievements") or []

            for item in items:
                if not isinstance(item, dict):
                    continue

                title = item.get("title") or item.get("name") or item.get("badgeTitle")
                if not title:
                    continue

                date_earned = item.get("issuedOn") or item.get("grantedOn") or item.get("date") or ""
                if date_earned and "T" in str(date_earned):
                    date_earned = str(date_earned).split("T")[0]

                url = item.get("url") or item.get("badgeUrl") or item.get("verificationUrl") or ""

                c_obj = {
                    "@type": "EducationalOccupationalCredential",
                    "credentialCategory": "Badge/Certification",
                    "name": title,
                    "recognizedBy": {
                        "@type": "Organization",
                        "name": platform_name
                    }
                }
                if date_earned:
                    c_obj["dateCreated"] = str(date_earned)
                if url:
                    c_obj["url"] = str(url)

                credentials.append(c_obj)

        except Exception as e:
            print(f"⚠️ Error parsing {filename} for JSON-LD: {e}")

    return credentials

def build_jsonld_payload(credentials):
    return {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": "Vojislav Miloradovic",
            "url": "https://github.com/VojislavMiloradovic/my-credentials",
            "hasCredential": credentials
        }
    }

def update_readme_jsonld(jsonld_str):
    if not os.path.exists(README_PATH):
        print(f"⚠️ {README_PATH} does not exist.")
        return

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Form script block
    script_block = f"{MARKER_START}\n<script type=\"application/ld+json\">\n{jsonld_str}\n</script>\n{MARKER_END}"

    if MARKER_START in content and MARKER_END in content:
        split_start = content.split(MARKER_START)
        split_end = split_start[1].split(MARKER_END)
        updated_content = split_start[0] + script_block + split_end[1]
    else:
        updated_content = content + f"\n\n{script_block}\n"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(updated_content)

    print(f"✅ Embedded JSON-LD script into {README_PATH}.")

def main():
    creds = extract_credentials()
    payload = build_jsonld_payload(creds)
    jsonld_str = json.dumps(payload, indent=2, ensure_ascii=False)

    # 1. Output standalone credentials.jsonld
    with open(JSONLD_PATH, "w", encoding="utf-8") as f:
        f.write(jsonld_str)
    print(f"✅ Generated {JSONLD_PATH} ({len(creds)} credentials).")

    # 2. Inject hidden script block in README.md
    update_readme_jsonld(jsonld_str)

if __name__ == "__main__":
    main()
