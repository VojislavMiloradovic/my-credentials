# Local Python/uv Environment Setup

## Location
```
C:\Users\Toughbook\opencode-test\.venv
```

## Quick Commands
```bash
cd C:\Users\Toughbook\opencode-test

# Run Python script
uv run python script.py

# Run ruff lint
uv run ruff check path/to/file.py

# Run with repo files
uv run python C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\build_exclude.py
uv run ruff check C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\update_ms_learn.py
```

## Environment Details
- **Python**: 3.11.15 (via uv)
- **uv**: 0.12.3 (matches `pyproject.toml` tool.uv.required-version)
- **Dependencies** (exact versions from `pyproject.toml`):
  - requests==2.34.2
  - beautifulsoup4==4.15.0
  - jsonschema==4.26.0
  - tiktoken==0.13.0
  - pydantic==2.13.4
  - ruff==0.16.2 (dev dependency)

## Notes
- Environment is isolated in `opencode-test/` — does not touch the repo
- Uses `uv.lock` for reproducible installs
- Repo's `.venv` is broken (missing Python executable) — use this instead