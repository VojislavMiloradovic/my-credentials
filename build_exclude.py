import glob
import json
import re
import sys

retired = []
for f in glob.glob('for_validation/*.json'):
    try:
        with open(f, 'r', encoding='utf-8') as fp:
            data = json.load(fp)

        # Handle different formats:
        # 1. Fingerprint format: {"fingerprints": {...}} - skip
        # 2. Full data format: varies by platform
        if isinstance(data, dict):
            if 'fingerprints' in data:
                continue  # Skip fingerprint baseline files

            # Platform-specific item arrays
            items = []
            for key in ('badges', 'achievements', 'learning_paths', 'certifications', 'combined_feed', 'public_badges', 'detailed_learnings'):
                if key in data and isinstance(data[key], list):
                    items.extend(data[key])

            # Also check for nested structures like {"verifiable_credentials": [...], "user_creds": [...]}
            for key in ('verifiable_credentials', 'user_creds', 'userCredentials'):
                if key in data and isinstance(data[key], list):
                    items.extend(data[key])

            if not items:
                continue
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