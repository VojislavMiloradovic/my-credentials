import json
import glob
import sys
import re

retired = []
for f in glob.glob('for_validation/*.json'):
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)

        # Handle different formats:
        # 1. Fingerprint format: {"fingerprints": {...}} - skip
        # 2. Full data format: {"badges": [...]} or {"badges": [...], "profile_id": ...} or list
        if isinstance(data, dict):
            if 'fingerprints' in data:
                continue  # Skip fingerprint baseline files
            if 'badges' in data:
                items = data['badges']
            else:
                items = data.values() if all(isinstance(v, dict) for v in data.values()) else []
        elif isinstance(data, list):
            items = data
        else:
            continue

        for item in items:
            if isinstance(item, dict) and item.get('retired') and item.get('url'):
                url = item['url']
                escaped = re.escape(url)
                retired.append(escaped)
    except Exception as e:
        print(f'Warning: Could not parse {f}: {e}', file=sys.stderr)

if retired:
    pattern = '(' + '|'.join(retired) + ')'
    print(f'exclude_pattern={pattern}')
else:
    print('exclude_pattern=')