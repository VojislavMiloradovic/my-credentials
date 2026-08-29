import json
import os

RETIRED_URLS_FILE = "retired_urls.json"


def load_retired_urls(platform: str) -> set[str]:
    """Load retired URLs for a platform from the mapping file."""
    if not os.path.exists(RETIRED_URLS_FILE):
        return set()
    try:
        with open(RETIRED_URLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get(platform, [])
        urls = set()
        for entry in entries:
            if isinstance(entry, str):
                urls.add(entry.strip())
            elif isinstance(entry, dict) and entry.get("url"):
                urls.add(entry["url"].strip())
            elif isinstance(entry, dict) and entry.get("id"):
                urls.add(entry["id"].strip())
        return urls
    except Exception:
        return set()


# Load retired URLs for google-developer at module level
_GOOGLE_DEV_RETIRED_URLS = load_retired_urls("google-developer")
