import sys
from generate_jsonld import parse_archive_monoliths

filepath = "archives/google-cloud-skills-complete.md"

try:
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
except FileNotFoundError:
    print(f"Error: Could not find {filepath}")
    sys.exit(1)

# Extract raw table rows excluding separator lines (| --- |)
raw_rows = [line.strip() for line in lines if line.strip().startswith("|") and "---" not in line]

# Run JSON-LD parser
all_creds = parse_archive_monoliths()
gcloud_creds = [c["name"] for c in all_creds if c.get("recognizedBy", {}).get("name") == "Google Cloud Skills"]

print("\n========================================")
print(f"Raw Table Rows (including main header): {len(raw_rows)}")
print(f"Parsed Google Cloud Credentials:        {len(gcloud_creds)}")
print("========================================\n")

print("--- SKIPPED OR UNPARSED ROWS ---")
skipped_count = 0
for r in raw_rows[1:]:  # Skip top header row (| Date Earned | Badge Title |)
    matched = any(title.lower() in r.lower() for title in gcloud_creds if len(title) > 3)
    if not matched:
        print(f"[SKIPPED] {r}")
        skipped_count += 1

if skipped_count == 0:
    print("[SUCCESS] All table rows matched extracted credentials!")
else:
    print(f"\nTotal Skipped Rows: {skipped_count}")
