#!/usr/bin/env python
"""Sanitize Google Developer MHTML by removing CID emails and any real PII."""

import re
import sys
from pathlib import Path


def sanitize_mhtml(content: str) -> str:
    # Remove MHTML CID "emails" (format: xxx@mhtml.blink)
    content = re.sub(r"[\w\.-]+@mhtml\.blink", "[CID_REDACTED]@mhtml.blink", content)

    # Remove any real email patterns (defensive)
    content = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[EMAIL_REDACTED]", content)

    # Remove potential Google UIDs (21-digit numbers in JSON contexts)
    content = re.sub(
        r'"(userId|uid|id)"\s*:\s*"\d{21}"', r'"\1": "[REDACTED]"', content
    )

    # Remove XSRF tokens
    content = re.sub(
        r'(["\']_?xsrf["\']\s*:\s*")[^"]+(")',
        r"\1[REDACTED]\2",
        content,
        flags=re.IGNORECASE,
    )

    return content


def process_file(file_path: Path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    sanitized = sanitize_mhtml(content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(sanitized)

    print(f"Sanitized {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sanitize_gdev_mhtml.py <path-to-mhtml>")
        sys.exit(1)
    process_file(Path(sys.argv[1]))
