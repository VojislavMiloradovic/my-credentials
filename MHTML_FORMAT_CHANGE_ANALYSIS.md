# Google Developer MHTML Format Change Analysis

## Executive Summary

Google has completely redesigned the Google Developer Profile "Learning" badge page. The MHTML source file format has changed from a static `devsite-badge` component structure (served from `developers.google.com`) to an Angular web component structure (served from `me.developers.google.com`).

**Impact**: The current parser `parse_google_learnings_mhtml()` in `update_google_developer.py` **will not work** with the new format. It will either:
1. Fail to find any `.badge-event` containers (returning empty list)
2. Fall back to the legacy text parser (`parse_local_learnings_txt()`) which expects a completely different file format

This affects the **detailed_learnings** stream (micro-learning activities from MHTML), which currently provides ~1,600+ records. The `public_badges` stream (from RPC API) is unaffected.

---

## Detailed Comparison: Old vs New Format

### Old Format (Current `data/Developer.mhtml`)

| Aspect | Details |
|--------|---------|
| **Source URL** | `https://developers.google.com/profile/badges/recognitions/learnings?u=VojislavMiloradovic` |
| **HTML Structure** | Static `devsite-badge` custom element |
| **Event Container** | `<div class="badge-event">` |
| **Title/Link** | `<a target="_blank" href="...">Title</a>` inside container |
| **Date Element** | `<p>26. ма́й 2026.</p>` (Serbian/Cyrillic month names) |
| **Date Format** | `DD. MMMM YYYY.` (Serbian Latin or Cyrillic) |
| **Total Count** | In `<div class="award-count fadein">1683</div>` |
| **Parser Strategy** | BeautifulSoup → find_all(class="badge-event") → extract link + date from `<p>` |

### New Format (`Downloads/Developer.mhtml`)

| Aspect | Details |
|--------|---------|
| **Source URL** | `https://me.developers.google.com/badges/recognitions/learnings` |
| **HTML Structure** | Angular app with web components (`gdp-root`, `gdp-badge-view`, `gdp-card`, etc.) |
| **Event Container** | `<li class="badge-event-row" _ngcontent-ng-c...="">` |
| **Title/Link** | `<a class="badge-event-title" href="..." jslog="...">Title</a>` |
| **Date Element** | `<span class="badge-event-date" _ngcontent-ng-c...="">May 26, 2026</span>` |
| **Date Format** | `MMMM DD, YYYY` (English month names) |
| **Total Count** | In `<div class="badge-level-pill fade-in-up"> 1689 </div>` |
| **Parser Strategy** | Must change to find `<li class="badge-event-row">` → extract from `<a.badge-event-title>` + `<span.badge-event-date>` |

---

## Key Structural Differences

### 1. Container Selector Change
```python
# OLD
badge_events = soup.find_all(class_="badge-event")

# NEW
badge_events = soup.find_all(class_="badge-event-row")
# OR more specifically:
badge_events = soup.select("li.badge-event-row")
```

### 2. Title/URL Extraction Change
```python
# OLD
link = event.find("a", href=True)
title = link.get_text(strip=True)
url = link["href"]

# NEW
link = event.find("a", class_="badge-event-title", href=True)
title = link.get_text(strip=True)
url = link["href"]
```

### 3. Date Extraction Change
```python
# OLD - <p> tag with Serbian date
date_p = event.find("p")
date_text = date_p.get_text(strip=True)  # "26. ма́й 2026."

# NEW - <span class="badge-event-date"> with English date
date_span = event.find("span", class_="badge-event-date")
date_text = date_span.get_text(strip=True)  # "May 26, 2026"
```

### 4. Date Parsing Change
The `normalize_date_string()` function currently expects Serbian format:
- `DD. MMMM YYYY.` (e.g., "17. august 2024." or "17. августа 2024.")

The new format uses English:
- `MMMM DD, YYYY` (e.g., "May 26, 2026")

**The SERBIAN_MONTHS dictionary will NOT match English month names.** Need to add English month support.

### 5. Total Count Extraction (Optional but useful)
```python
# NEW - can extract total from badge-level-pill
count_element = soup.find(class_="badge-level-pill")
if count_element:
    total = int(count_element.get_text(strip=True))
```

---

## Required Code Changes

### 1. Update `parse_google_learnings_mhtml()` in `update_google_developer.py`

**Primary changes needed:**
- Update BeautifulSoup selectors for new Angular structure
- Add English month parsing to `normalize_date_string()` / `SERBIAN_MONTHS`
- Handle `_ngcontent-ng-c*` attributes (BeautifulSoup handles these automatically)
- Optionally extract total count from `.badge-level-pill`

**Proposed implementation approach:**
```python
def parse_google_learnings_mhtml(mhtml_path: str) -> list[dict]:
    # ... existing MHTML loading code ...
    
    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Try NEW format first (Angular/gdp-badge-view)
        badge_events = soup.select("li.badge-event-row")
        
        if not badge_events:
            # Fallback to OLD format (devsite-badge)
            badge_events = soup.find_all(class_="badge-event")
        
        if badge_events:
            learnings = []
            retired_count = 0
            
            for event in badge_events:
                # Try new format selectors first
                link = event.find("a", class_="badge-event-title", href=True)
                if not link:
                    # Fallback to old format
                    link = event.find("a", href=True)
                
                if not link:
                    continue
                    
                title = fix_mojibake(link.get_text(strip=True))
                url = link["href"]
                
                # Fix: If title looks like a raw URL/path, extract human-readable title from URL
                if is_url_like_title(title):
                    title = extract_title_from_url(url)
                
                # Try new format date selector
                date_span = event.find("span", class_="badge-event-date")
                if date_span:
                    date_text = date_span.get_text(strip=True)
                else:
                    # Fallback to old format
                    date_p = event.find("p")
                    date_text = date_p.get_text(strip=True) if date_p else ""
                
                iso_date = normalize_date_string(date_text)
                
                # Check if retired (date parsing failed or URL patterns)
                is_retired = iso_date == "N/A"
                if is_retired:
                    retired_count += 1
                
                # ... rest of entry creation ...
            
            return learnings
```

### 2. Update `normalize_date_string()` to Support English Months

Add English month names to `SERBIAN_MONTHS` dictionary (or create a separate mapping):

```python
ENGLISH_MONTHS = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}
```

Then update `normalize_date_string()` to try both Serbian and English patterns:

```python
def normalize_date_string(raw_date: Any) -> str:
    # ... existing code ...
    
    # Try Serbian format: DD. MMMM YYYY.
    serbian_match = re.match(r"^(\d+)\.\s+([^\s\d]+)\s+(\d{4})\.?$", s_date)
    if serbian_match:
        # ... existing Serbian parsing ...
        return f"{year}-{month_num}-{day}"
    
    # Try English format: MMMM DD, YYYY
    english_match = re.match(r"^([A-Za-z]+)\s+(\d+),\s+(\d{4})$", s_date)
    if english_match:
        month_str = english_match.group(1).lower()
        day = english_match.group(2).zfill(2)
        year = english_match.group(3)
        
        month_num = ENGLISH_MONTHS.get(month_str, "00")
        return f"{year}-{month_num}-{day}"
    
    return "N/A"
```

### 3. Update Test Fixtures

**Files to update:**
- `tests/fixtures/google_developer/learnings.txt` - Currently contains Serbian-format test data
- `tests/conftest.py` - `sample_google_developer_learnings` fixture

The test fixture should be updated to use the new English date format to match the new MHTML structure, OR the parser should be made to handle both formats (backward compatible).

**Recommendation**: Make parser backward-compatible (handle both formats), but update test fixtures to use new format for realistic testing.

### 4. Update Cross-Artifact Validator (if needed)

The cross-artifact validator reads from `for_validation/google-developer.json` which contains the parsed output. Since the parser output format (list of dicts with `title`, `date`, `description`, `source`, `url`, `retired`) remains the same, **no changes should be needed** in the validator.

However, verify:
- `validate_source_snapshots()` expects `combined_feed` key - unchanged
- `validate_stream_completeness()` checks sum of streams vs combined - unchanged
- Count validation will work as long as parser produces records

### 5. Update Retirement Handling

The `retired_urls.json` contains manually curated retired URLs matched by `match_type: "url"`. Since the new MHTML contains the same codelab URLs (e.g., `https://codelabs.developers.google.com/...`), **no changes needed** - URL matching will continue to work.

Auto-retirement (when date parsing fails) will still work with the new format.

### 6. Update Baseline Generation & Fixtures

When the parser is fixed and run:
- New baseline files will be generated in `for_validation/`
- `scripts/sync_fixtures.py` will copy them to `tests/fixtures/google_developer/`
- Fixture freshness check will pass

**Files that will be regenerated:**
- `for_validation/google-developer.json`
- `for_validation/google-developer-combined-baseline.json`
- `for_validation/google-developer-detailed_learnings-baseline.json`
- `for_validation/google-developer-public_badges-baseline.json`
- `tests/fixtures/google_developer/combined_baseline.json`
- `tests/fixtures/google_developer/detailed_learnings_baseline.json`
- `tests/fixtures/google_developer/public_badges_baseline.json`
- `tests/fixtures/google_developer/combined_feed.json`

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Parser returns 0 records | High | Critical - loss guard triggers | Add backward-compatible selectors, test thoroughly |
| Date parsing fails for all records | High | High - all marked retired | Add English month support to `normalize_date_string()` |
| Title extraction gets URLs instead of titles | Medium | Medium - poor data quality | Keep `is_url_like_title()` + `extract_title_from_url()` logic |
| Test failures | High | Medium - CI blocks | Update test fixtures to new format |
| Cross-artifact validation fails | Low | Medium | Validator reads normalized output, unchanged |
| Retirement detection breaks | Low | Low | URL-based matching unchanged |

---

## Implementation Plan

### Phase 1: Parser Update (Critical)
1. [ ] Update `parse_google_learnings_mhtml()` with new selectors (try new first, fallback to old)
2. [ ] Add English month support to `normalize_date_string()`
3. [ ] Test with new MHTML file locally

### Phase 2: Test Updates (High)
1. [ ] Update `tests/fixtures/google_developer/learnings.txt` to new format
2. [ ] Update `sample_google_developer_learnings` fixture in `conftest.py`
3. [ ] Run unit tests: `uv run pytest tests/unit/ -k "google_developer" -v`
4. [ ] Run integration tests: `uv run pytest tests/integration/test_google_developer_pipeline.py -v`

### Phase 3: Validation & Baseline Regeneration (High)
1. [ ] Run full pipeline: `uv run python update_google_developer.py`
2. [ ] Verify cross-artifact validation: `uv run python cross_artifact_validator.py --mode strict`
3. [ ] Sync fixtures: `uv run python scripts/sync_fixtures.py`
4. [ ] Check fixture freshness: `uv run python scripts/check_fixture_freshness.py --threshold 90`

### Phase 4: Output Verification (Medium)
1. [ ] Verify archives generated correctly: `archives/google-developer-*.md`
2. [ ] Verify JSON-LD: `uv run python generate_jsonld.py`
3. [ ] Verify llms.txt: `uv run python generate_llms_txt.py`
4. [ ] Verify llms-full.txt: `uv run python generate_llms_full.py`
5. [ ] Check README injection looks correct

---

## Backward Compatibility Strategy

The parser should support **both formats** during transition:
1. Try new Angular selectors first (`li.badge-event-row`, `a.badge-event-title`, `span.badge-event-date`)
2. Fall back to old `devsite-badge` selectors (`div.badge-event`, `a`, `p`)
3. Try English date parsing first, then Serbian

This ensures:
- Old MHTML files in test fixtures still work
- No breaking change if Google serves mixed formats
- Smooth transition when deploying

---

## Files to Modify

| File | Changes |
|------|---------|
| `update_google_developer.py` | `parse_google_learnings_mhtml()`, `normalize_date_string()`, `SERBIAN_MONTHS` / new `ENGLISH_MONTHS` |
| `tests/fixtures/google_developer/learnings.txt` | Update to English date format |
| `tests/conftest.py` | Update `sample_google_developer_learnings` fixture |

---

## Verification Commands

```bash
# Test parser directly
uv run python -c "
from update_google_developer import parse_google_learnings_mhtml
learnings = parse_google_learnings_mhtml('data/Developer.mhtml')
print(f'Parsed {len(learnings)} records')
for l in learnings[:3]:
    print(f'  {l[\"date\"]} | {l[\"title\"][:60]}')
"

# Run tests
uv run pytest tests/integration/test_google_developer_pipeline.py -v
uv run pytest tests/unit/ -k "google_developer" -v

# Full pipeline
uv run python update_google_developer.py

# Validation
uv run python cross_artifact_validator.py --mode strict

# Fixtures
uv run python scripts/sync_fixtures.py
uv run python scripts/check_fixture_freshness.py --threshold 90
```