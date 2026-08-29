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
    # developer.android.com/codelabs/ - Redirects to OAuth2 auth page (interaction_required)
    # These specific codelabs require authentication and redirect to accounts.google.com
    (
        "https://developer.android.com/codelabs/activity-recognition-transition",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/add-adaptive-layouts",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/add-play-integrity",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/admob-rewarded-video-android",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-adv-workmanager",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-app-links-introduction",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-development-kotlin-1.1",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-development-kotlin-1.2",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-development-kotlin-2.1",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-development-kotlin-3.1",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-development-kotlin-3.2",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-fundamentals-02-2-activity-lifecycle-and-state",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-hilt",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-nearby-messages",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-paging",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-people",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-privacy-codelab",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-testing",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-vts-2019",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/android-workmanager-java",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/approximate-location",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/audio-while-driving",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-30-days",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-activity-lifecycle",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-adaptive-content-for-large-screens",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-adaptive-navigation-for-large-screens",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-add-images",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-add-repository",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-app-with-views",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-art-space",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-before-you-begin",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-bookshelf",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-build-a-dice-roller-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-business-card",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-button-click-practice-problem",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-calculate-tip",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-classes-and-objects",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-collections",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-composables-practice-problems",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-conditionals",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-connect-device",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-coroutines-android-studio",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-coroutines-kotlin-playground",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-datastore",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-emulator",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-first-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-first-program",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-flight-search",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-functions",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-function-types-and-lambda",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-generics",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-higher-order-functions",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-install-android-studio",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-intro-debugger",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-intro-kotlin-practice-problems",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-kotlin-fundamentals-practice-problems",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-load-images",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-material-theming",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-my-city",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-navigation",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-nullability",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-persisting-data-room",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-amphibians-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-bus-schedule-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-classes-and-collections",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-grid",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-navigation",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-sports-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-superheroes",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-viewmodel",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-practice-water-me-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-sql",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-test-accessibility",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-test-cupcake",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-test-viewmodel",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-text-composables",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-training-add-scrollable-list",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-training-change-app-icon",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-update-data-room",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-using-state",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-variables",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-verify-background-work",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-view-interop",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-viewmodel-and-state",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-woof-animation",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-workmanager",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-compose-write-automated-tests",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/basic-android-kotlin-training-compose-add-compose-to-a-view-based-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/biometric-login",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/build-a-parked-app",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/building-kotlin-extensions-library",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/camerax-getting-started",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/codelab-adaptive-apps",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/codelab-dnd-compose",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/compose-for-tv-introduction",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/compose-for-wear-os",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/cronet",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/digit-classifier-tflite",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/edge-to-edge",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/gemini-summarize",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/glance",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/health-connect",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/java-to-kotlin",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-accessibility",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-advanced-state-side-effects",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-animation",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-basics",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-layouts",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-migration",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-navigation",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-performance",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-state",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/jetpack-compose-testing",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/kmp-migrate-room",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/kotlin-coroutines",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/large-screens/activity-embedding",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/large-screens/add-keyboard-and-mouse-support-with-compose",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/large-screens/advanced-activity-embedding",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/m3-design-theming",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/mdc-102-kotlin",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/mdc-103-kotlin",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/mdc-104-kotlin",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/ongoing-activity",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/pay-android-checkout",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/predictive-back",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/starting-android-accessibility",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/supporting-mediasession",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/tv-watch-next",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/using-android-q-gsi",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/watch-face-format",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/wear-tiles",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/work-profile-apps",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/xr-fundamentals-part-1",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    (
        "https://developer.android.com/codelabs/xr-fundamentals-part-2",
        "Redirects to OAuth2 auth page (interaction_required)",
    ),
    # codelabs.developers.google.com - Redirects to OAuth2 auth page
    # These specific codelabs require authentication and redirect to accounts.google.com
    # ("https://codelabs.developers.google.com/codelabs/specific-codelab-id", "Redirects to OAuth2 auth page (interaction_required)"),
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
            print(
                f"Added problematic redirect URL: {norm}  # {reason}", file=sys.stderr
            )

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
