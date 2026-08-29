import glob
import json
import os
import re
import sys

RETIRED_URLS_FILE = "retired_urls.json"

# -----------------------------------------------------------------------------
# PROBLEMATIC REDIRECT URLS
# -----------------------------------------------------------------------------
# These are specific URLs that are known to redirect to Google OAuth2 auth pages
# (accounts.google.com/o/oauth2/v2/auth...interaction_required) instead of
# serving the actual codelab content. They are added to .lycheeignore to prevent
# false positive link check failures.
#
# IMPORTANT: We do NOT exclude entire domains like codelabs.developers.google.com,
# developer.android.com/codelabs/, or firebase.google.com/codelabs/ because
# the vast majority of URLs on these platforms (1000+) work correctly and only
# a small subset redirect to auth pages. We only exclude specific problematic URLs.
#
# Format: (url, reason_comment)
PROBLEMATIC_REDIRECT_URLS: list[tuple[str, str]] = [
    # codelabs.developers.google.com - Redirects to OAuth2 auth page
    # These specific codelabs require authentication and redirect to accounts.google.com
    # ("https://codelabs.developers.google.com/codelabs/specific-codelab-id", "Redirects to OAuth2 auth page (interaction_required)"),
    
    # developer.android.com/codelabs/ - Redirects to OAuth2 auth page
    # ("https://developer.android.com/codelabs/specific-codelab-id", "Redirects to OAuth2 auth page (interaction_required)"),
    
    # firebase.google.com/codelabs/ - Redirects to OAuth2 auth page
    # ("https://firebase.google.com/codelabs/specific-codelab-id", "Redirects to OAuth2 auth page (interaction_required)"),
]


def normalize_url(raw_url: str | None) -> str:
    """Normalize URL to match markdown format."""
    if not raw_url or not isinstance(raw_url, str):
        return ""
    clean = raw_url.strip()
    clean = re.sub(r"\s+program/?$", "", clean)
    clean = clean.replace(" ", "")
    if not clean:
        return ""
    if clean.startswith("learn."):
        path_part = clean[6:]
        clean = f"https://learn.microsoft.com/en-us/training/paths/{path_part}"
    elif not clean.startswith("http"):
        if clean.startswith("/"):
            clean = f"https://learn.microsoft.com/en-us{clean}"
        else:
            clean = f"https://learn.microsoft.com/en-us/{clean}"
    elif "learn.microsoft.com/training/" in clean:
        clean = clean.replace(
            "learn.microsoft.com/training/", "learn.microsoft.com/en-us/training/"
        )
    return clean


def main():
    retired_urls: set[str] = set()

    # 1. Directly load URLs from retired_urls.json registry
    if os.path.exists(RETIRED_URLS_FILE):
        try:
            with open(RETIRED_URLS_FILE, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for platform_rules in data.values():
                if isinstance(platform_rules, list):
                    for rule in platform_rules:
                        if isinstance(rule, dict):
                            u = rule.get("url") or (
                                rule.get("id")
                                if str(rule.get("id", "")).startswith("http")
                                else None
                            )
                        elif isinstance(rule, str) and rule.startswith("http"):
                            u = rule
                        else:
                            u = None
                        if u:
                            norm = normalize_url(u)
                            if norm:
                                retired_urls.add(norm)
        except Exception as e:
            print(f"Warning: Could not parse {RETIRED_URLS_FILE}: {e}", file=sys.stderr)

    # 1b. Add known problematic redirect URLs (Google OAuth2 auth pages)
    # These are specific URLs identified as redirecting to accounts.google.com/o/oauth2/v2/auth
    # instead of serving codelab content. We only exclude specific known-bad URLs,
    # NOT entire codelabs domains (1000+ valid URLs would be lost).
    for url, reason in PROBLEMATIC_REDIRECT_URLS:
        norm = normalize_url(url)
        if norm:
            retired_urls.add(norm)
            print(f"Added problematic redirect URL: {norm}  # {reason}", file=sys.stderr)

    # 2. Extract retired URLs from validated JSON exports
    for f in glob.glob("for_validation/*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            if isinstance(data, dict):
                if "fingerprints" in data:
                    continue
                items = []
                for key in (
                    "badges",
                    "achievements",
                    "learning_paths",
                    "certifications",
                    "combined_feed",
                    "public_badges",
                    "detailed_learnings",
                    "verifiable_credentials",
                    "user_creds",
                    "userCredentials",
                ):
                    if key in data and isinstance(data[key], list):
                        items.extend(data[key])
                if not items:
                    continue
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                if isinstance(item, dict) and item.get("retired"):
                    url = None
                    for field in (
                        "url",
                        "learningPathUid",
                        "learning_path_uid",
                        "learningPathId",
                        "sourceUid",
                    ):
                        raw = item.get(field)
                        if raw:
                            url = normalize_url(raw)
                            if url:
                                break
                    if url:
                        retired_urls.add(url)
        except Exception as e:
            print(f"Warning: Could not parse {f}: {e}", file=sys.stderr)

    if retired_urls:
        with open(".lycheeignore", "w", encoding="utf-8") as f:
            f.write("# Retired credentials - auto-generated by build_exclude.py\n")
            f.write(
                "# These URLs return 404 and should be excluded from link checking\n\n"
            )
            for url in sorted(retired_urls):
                f.write(f"{url}\n")
        print("lycheeignore_written=true")
    else:
        print("lycheeignore_written=false")


if __name__ == "__main__":
    main()
