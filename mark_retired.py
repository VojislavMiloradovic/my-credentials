import json
import csv
import os

# 1. Mark MS Learn dead item as retired
print("Processing microsoft-learn.json...")
with open('data/microsoft-learn.json', 'r', encoding='utf-8') as f:
    ms_data = json.load(f)

ms_modified = 0
for item in ms_data:
    if item.get('sourceId') == 'learn.viva-glint-360-feedback':
        item['retired'] = True
        ms_modified += 1
        print(f"  Marked retired: {item.get('sourceId')}")

if ms_modified:
    with open('data/microsoft-learn.json', 'w', encoding='utf-8') as f:
        json.dump(ms_data, f, indent=2, ensure_ascii=False)
    print(f"  Updated {ms_modified} item(s)")
else:
    print("  No matching item found")

# 2. Mark LinkedIn dead item as retired
print("\nProcessing Certifications.csv...")
csv_path = 'data/Certifications.csv'
rows = []
with open(csv_path, 'r', encoding='utf-8-sig') as f:
    content = f.read()
    delimiter = "\t" if "\t" in content.splitlines()[0] else ","
    f.seek(0)
    reader = csv.DictReader(f, delimiter=delimiter)
    fieldnames = reader.fieldnames
    # Add retired column if not present
    if 'retired' not in fieldnames:
        fieldnames = list(fieldnames) + ['retired']
    for row in reader:
        rows.append(row)

li_modified = 0
for row in rows:
    url = row.get('Url') or row.get('url') or row.get('URL') or ''
    if 'ae6b4ab2f3e25673ea0b882f5443d748f91855994ac4f6204d2b824e14bc51f4' in url:
        row['retired'] = 'true'
        li_modified += 1
        print(f"  Marked retired: {row.get('Name') or row.get('name')}")

if li_modified:
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Updated {li_modified} item(s)")
else:
    print("  No matching item found")

print("\nDone!")