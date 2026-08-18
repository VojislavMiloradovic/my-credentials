# Testing Guide

This document describes how to run tests locally, add new fixtures, and understand the test structure.

## Quick Start

```bash
# Install test dependencies
uv sync --extra test

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=. --cov-report=term-missing

# Run specific test file
uv run pytest tests/unit/test_date_normalization.py -v

# Run tests for specific provider
uv run pytest tests/integration/test_microsoft_learn_pipeline.py -v

# Run with parallel execution
uv run pytest -n auto
```

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures and configuration
├── test_cli_smoke.py           # CLI entry point smoke tests
├── test_config_validation.py   # Config file validation tests
├── fixtures/                   # Test data fixtures (committed)
│   ├── microsoft_learn/
│   ├── google_skills/
│   ├── aws_skills/
│   ├── credly/
│   ├── linkedin/
│   ├── google_developer/
│   └── shared/
├── unit/                       # Unit tests for core modules
│   ├── test_archiver.py
│   ├── test_build_exclude.py
│   ├── test_date_normalization.py
│   ├── test_loss_guard.py
│   ├── test_pydantic_models.py
│   ├── test_retired_handling.py
│   └── test_sanitize_ms_export.py
└── integration/                # Integration tests for pipelines
    ├── test_aws_skills_pipeline.py
    ├── test_credly_pipeline.py
    ├── test_google_developer_pipeline.py
    ├── test_google_skills_pipeline.py
    ├── test_jsonld_generation.py
    ├── test_llms_generation.py
    ├── test_linkedin_pipeline.py
    ├── test_microsoft_learn_pipeline.py
    └── test_archive_parsing.py
```

## Fixture Management

### Adding New Fixtures

1. Create fixture file in appropriate `tests/fixtures/<provider>/` directory
2. Keep fixtures minimal and realistic (only fields actually parsed)
3. Include edge cases: missing fields, malformed dates, duplicates
4. Name descriptively: `export.json`, `api_response.json`, `transcript.csv`

### Fixture Rotation Policy

- Keep **latest 2 versions** per fixture type per provider
- Archive older fixtures to `tests/fixtures/archive/` (git-tracked but not in test discovery)
- Document download URLs in `tests/fixtures/README.md` for historical versions

### Fixture Size Limits

- JSON/CSV fixtures: **< 50 KB each**
- HTML/RPC fixtures: **< 100 KB each**
- Total `tests/fixtures/` target: **< 2 MB**

## Running Tests

### Local Development

```bash
# Full test suite with coverage
uv run pytest -n auto -v --cov=. --cov-report=term-missing --cov-fail-under=70

# Type checking
uv run mypy tests/ --ignore-missing-imports

# Linting
uv run ruff check .
uv run ruff format --check .
```

### CI Pipeline

Tests run automatically on push/PR via GitHub Actions (`.github/workflows/test.yml`):

1. **Test job**: Runs pytest with coverage, uploads to Codecov
2. **Lint job**: Runs ruff check and format

Coverage threshold: **70%** (ramping to 85%)

## Test Patterns

### Parametrized Tests

```python
@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("Jan 15, 2024", "2024-01-15"),
        ("1705312800000", "2024-01-15"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_date_string(input_val, expected):
    assert normalize_date_string(input_val) == expected
```

### HTTP Mocking with Responses

```python
@responses.activate
def test_fetch_google_skills_json_api_success(sample_google_skills_json):
    responses.add(
        responses.GET,
        "https://www.skills.google/public_profiles/test.json",
        json=sample_google_skills_json,
        status=200,
    )
    
    badges = fetch_google_skills_badges("test")
    assert len(badges) == 2
```

### File I/O with tmp_path

```python
def test_process_file_basic(temp_dir):
    test_file = temp_dir / "test.json"
    test_file.write_text(json.dumps({"password": "secret"}))
    
    process_file(test_file)
    
    result = json.loads(test_file.read_text())
    assert result["password"] == "[REDACTED]"
```

### Mocking Shared Modules

```python
@pytest.fixture
def mock_archiver(monkeypatch):
    mock_generate = MagicMock(return_value="test-platform-2024-06-part-01.md")
    monkeypatch.setattr("archiver.generate_platform_archive", mock_generate)
    return mock_generate

def test_main_pipeline_success(mock_archiver, ...):
    main()
    mock_archiver.assert_called_once()
```

## Coverage Targets

| Module | Target |
|--------|--------|
| Core (archiver, loss_guard, sanitize, retired, date parsing) | ≥ 95% |
| Provider parsers | ≥ 80% |
| Generation scripts | ≥ 75% |
| Overall | ≥ 70% (ramping to 85%) |

## Adding New Tests

1. **Unit test**: Add to `tests/unit/test_<module>.py`
2. **Integration test**: Add to `tests/integration/test_<provider>_pipeline.py`
3. **Use existing fixtures** from `conftest.py` where possible
4. **Add new fixtures** to `tests/fixtures/<provider>/` if needed
5. **Follow naming convention**: `test_<function>_<scenario>`
6. **Use parametrize** for multiple input/output cases

## Debugging Tests

```bash
# Run single test with output
uv run pytest tests/unit/test_date_normalization.py::TestAwsDateNormalization::test_normalize_date_string -v -s

# Drop into debugger on failure
uv run pytest --pdb tests/unit/test_loss_guard.py

# Show coverage for specific file
uv run pytest --cov=update_ms_learn tests/integration/test_microsoft_learn_pipeline.py
```

## Test Data Builders

`conftest.py` provides builder fixtures for creating test data:

```python
def test_something(aws_badge_builder):
    badge = aws_badge_builder(id="custom-id", title="Custom Title")
    # badge has all required fields with defaults, only overrides specified
```

Available builders:
- `aws_badge_builder`
- `google_badge_builder`
- `ms_achievement_builder`
- `credly_badge_builder`
- `linkedin_cert_builder`
- `gdev_badge_builder`

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure `sys.path.insert(0, str(Path(__file__).parent.parent.parent))` in test files
2. **Fixture not found**: Check `tests/fixtures/<provider>/<filename>` exists
3. **Mock not working**: Verify patch target path matches import location (e.g., `update_ms_learn.os.path.exists`)
4. **Coverage too low**: Check `--cov-report=term-missing` for uncovered lines

### Test Isolation

- Each test gets fresh `tmp_path` directory
- HTTP mocks are per-test via `responses` library
- Time is frozen to `2024-06-15 12:00:00 UTC` via `freezegun`
- Shared modules mocked via `monkeypatch` in fixtures