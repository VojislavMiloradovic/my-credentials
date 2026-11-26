"""
Sanitizes Microsoft Learn JSON exports by pruning unused PII/lab sections and
redacting temporary lab secrets, VM credentials, Azure storage keys, SAS tokens,
emails, and user IDs before committing or processing.
"""

import json
import re
import sys
from pathlib import Path

# Substring-matched field names associated with credentials/tokens
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

# Exact normalized field names for PII / internal account identifiers
# (kept separate from substring matching so words like "android" or "voicemail"
# or catalog slugs like "sourceUid" are never falsely redacted)
EXACT_SENSITIVE_JSON_KEYS = {
    "userid",
    "docsid",
    "email",
    "userprincipalname",
    "upn",
    "mail",
    "objectid",
    "principalname",
    "legalname",
    "sharingid",
    "tenantid",
    "oid",
}

# Top-level Microsoft Learn export sections that are unused by update_ms_learn.py
# and contain account PII or temporary lab execution output.
UNNEEDED_MS_EXPORT_SECTIONS = {
    "TechProfile",
    "SkillAssessment",
    "LearnCompanion",
    "Q&A",
    "NextSteps",
    "Assessments",
    "Attachments",
    "Certifications",
    "Lists",
}

MS_EXPORT_CORE_SECTIONS = {"Progress", "XP", "VerifiableCredentials"}

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
    # Email addresses embedded in text fields
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[EMAIL_REDACTED]",
    ),
]


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "")
    if normalized in EXACT_SENSITIVE_JSON_KEYS:
        return True
    return any(sens in normalized for sens in SENSITIVE_JSON_KEYS)


def scrub_text(text: str) -> str:
    """Applies inline regex substitutions to clean embedded secrets in terminal output."""
    for pattern, replacement in INLINE_SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def prune_unneeded_ms_sections(data: dict) -> dict:
    """Drop unused PII/lab top-level sections when given a Microsoft Learn export."""
    keys = set(data.keys())
    has_ms_export_shape = bool(keys & MS_EXPORT_CORE_SECTIONS) and bool(
        keys & UNNEEDED_MS_EXPORT_SECTIONS
    )
    if not has_ms_export_shape:
        return data
    return {k: v for k, v in data.items() if k not in UNNEEDED_MS_EXPORT_SECTIONS}


def sanitize_node(val):
    """Recursively sanitize a JSON-serializable value."""
    if isinstance(val, str):
        return scrub_text(val)
    elif isinstance(val, dict):
        # Special handling for VerifiableCredentials.userCredentials:
        # keep sourceUid (catalog slug used for public display & retired matching),
        # while redacting account/user identifiers.
        if "userCredentials" in val and isinstance(val["userCredentials"], list):
            sanitized = {}
            for k, v in val.items():
                if k == "userCredentials":
                    sanitized[k] = [
                        {
                            k2: "[REDACTED]"
                            if is_sensitive_key(k2)
                            else sanitize_node(v2)
                            for k2, v2 in cred.items()
                        }
                        for cred in v
                    ]
                elif is_sensitive_key(k):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = sanitize_node(v)
            return sanitized
        else:
            sanitized_dict = {}
            for k, v in val.items():
                if is_sensitive_key(k):
                    sanitized_dict[k] = "[REDACTED]"
                else:
                    sanitized_dict[k] = sanitize_node(v)
            return sanitized_dict
    elif isinstance(val, list):
        return [sanitize_node(item) for item in val]
    else:
        return val


def process_file(file_path: Path):
    if not file_path.exists():
        print(f"Error: File {file_path} not found.")
        sys.exit(1)

    print(f"Sanitizing {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = prune_unneeded_ms_sections(data)

    sanitized_data = sanitize_node(data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(sanitized_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully sanitized {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sanitize_ms_export.py <path-to-json>")
        sys.exit(1)

    process_file(Path(sys.argv[1]))
