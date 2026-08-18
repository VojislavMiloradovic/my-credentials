"""
Sanitizes Microsoft Learn JSON exports by redacting temporary lab secrets,
VM credentials, Azure storage keys, SAS tokens, and connection strings
found in PowerShell execution logs (e.g., scriptResult fields) before Gitleaks runs.
"""

import json
import re
import sys
from pathlib import Path

# Common field names associated with credentials/tokens
SENSITIVE_JSON_KEYS = {
    "password",
    "secret",
    "privatekey",
    "sshkey",
    "connectionstring",
    "authorization",
    "accesstoken",
    "refreshtoken",
    "bearer",
    "subscriptionkey",
    "clientsecret",
    "labpassword",
    "vmpassword",
}

# Regex patterns for inline string replacement (e.g., inside scriptResult text)
INLINE_SCRUB_PATTERNS = [
    # Azure SAS token signatures
    (re.compile(r"(sig=)[a-zA-Z0-9%2F%2B%3D]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
    # Azure Connection String AccountKey
    (re.compile(r"(AccountKey=)[a-zA-Z0-9+/=]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
    # Key-Value lines in script logs (e.g., Initial Key : <key>, New Key1 : <key>, Key2 value : <key>, Value : <key>)
    (
        re.compile(
            r"((?:Initial Key|New Key\d*|Key\d*|Value)\s*:\s*)[a-zA-Z0-9+/=]{20,}",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # JSON-style strings in terminal dumps (e.g., "Key" : "<key>", "Connection String" : "<conn_string>")
    (re.compile(r'("Key"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
    (
        re.compile(r'("Connection String"\s*:\s*")[^"]+(")', re.IGNORECASE),
        r"\1[REDACTED]\2",
    ),
    # Standalone Base64 key patterns typical for Azure Storage keys (64-88 chars ending in =)
    (re.compile(r"\b[A-Za-z0-9+/]{60,88}={1,2}\b"), "[REDACTED_KEY]"),
    # PEM Private Keys
    (
        re.compile(
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
]


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "")
    return any(sens in normalized for sens in SENSITIVE_JSON_KEYS)


def scrub_text(text: str) -> str:
    """Applies inline regex substitutions to clean embedded secrets in terminal output."""
    for pattern, replacement in INLINE_SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_node(val):
    if isinstance(val, str):
        return scrub_text(val)
    elif isinstance(val, dict):
        sanitized_dict = {}
        for k, v in val.items():
            if is_sensitive_key(k):
                sanitized_dict[k] = "[REDACTED]"
            else:
                sanitized_dict[k] = sanitize_node(v)
        return sanitized_dict
    elif isinstance(val, list):
        return [sanitize_node(item) for item in val]
    return val


def process_file(file_path: Path):
    if not file_path.exists():
        print(f"Error: File {file_path} not found.")
        sys.exit(1)

    print(f"Sanitizing {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sanitized_data = sanitize_node(data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(sanitized_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully sanitized {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/sanitize_ms_export.py <path-to-json>")
        sys.exit(1)

    process_file(Path(sys.argv[1]))
