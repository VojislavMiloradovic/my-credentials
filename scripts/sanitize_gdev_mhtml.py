"""Sanitize Google Developer MHTML files by stripping account widgets, tokens, CIDs, and PII."""

import email
import quopri
import re
import sys
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from bs4 import BeautifulSoup

LEARNINGS_LOCATION_MARKERS = (
    "profile/badges/recognitions/learnings",
    "me.developers.google.com/badges/recognitions/learnings",
)

SENSITIVE_META_NAMES = (
    "og-profile-acct",
    "xsrf_token",
    "google-signin-client_id",
)


def sanitize_mhtml(content: str) -> str:
    """Scrub PII, CIDs, 21-digit UIDs, and XSRF tokens from raw HTML/MHTML text."""
    # Unfold Quoted-Printable soft line breaks so wrapped emails/tokens are matched completely
    content = re.sub(r"=\r?\n", "", content)

    # Remove MHTML CID "emails" (format: xxx@mhtml.blink)
    content = re.sub(r"[\w.\-]+@mhtml\.blink", "[CID_REDACTED]@mhtml.blink", content)

    # Remove <meta> tags carrying account email, XSRF tokens, or sign-in client IDs
    content = re.sub(
        r"<meta\b[^>]*\bname\s*(?:=3D|=)\s*[\"']?(?:og-profile-acct|xsrf_token|google-signin-[^\"'>\s]+)[\"']?[^>]*>",
        "",
        content,
        flags=re.IGNORECASE,
    )

    # Remove any real email patterns (preserving @mhtml.blink placeholders)
    content = re.sub(
        r"[A-Za-z0-9._%+\-]+@(?!mhtml\.blink)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        "[EMAIL_REDACTED]",
        content,
    )

    # Remove potential Google UIDs (21-digit numbers in JSON contexts)
    content = re.sub(
        r'"(userId|uid|id)"\s*:\s*"\d{21}"', r'"\1": "[REDACTED]"', content
    )

    # Remove JSON-style and HTML-attribute XSRF tokens
    content = re.sub(
        r'(["\']_?xsrf(?:_token)?["\']\s*:\s*")[^"]+(")',
        r"\1[REDACTED]\2",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'(\bxsrf(?:_token)?["\']?\s*(?:=3D|=)\s*["\'])[^"\']+(["\'])',
        r"\1[REDACTED]\2",
        content,
        flags=re.IGNORECASE,
    )

    # Scrub authuser query parameter
    content = re.sub(
        r"(authuser\s*(?:=3D|=))[^&\"'\s<>]+",
        r"\1[REDACTED]",
        content,
        flags=re.IGNORECASE,
    )

    return content


def _sanitize_learnings_html(html_content: str) -> str:
    """Remove scripts, sensitive meta tags, and Google account switcher blocks from HTML."""
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup.find_all("script"):
        tag.decompose()

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        if name in SENSITIVE_META_NAMES or "xsrf" in name or "acct" in name:
            meta.decompose()

    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if any(
            domain in href
            for domain in (
                "accounts.google.com/ListAccounts",
                "accounts.google.com/SignOutOptions",
                "accounts.google.com/ServiceLogin",
                "myaccount.google.com",
            )
        ):
            link.decompose()

    return sanitize_mhtml(str(soup))


def _build_sanitized_mhtml_bytes(raw_bytes: bytes) -> bytes | None:
    """Parse multipart MHTML, keep only sanitized learnings HTML, and re-serialize."""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    if not msg.is_multipart():
        return None

    kept_parts: list[tuple[str, str]] = []
    for part in msg.walk():
        if part.get_content_type() != "text/html":
            continue
        content_location = part.get("Content-Location", "")
        if any(marker in content_location for marker in LEARNINGS_LOCATION_MARKERS):
            raw_payload = part.get_payload(decode=False)
            if isinstance(raw_payload, (str, bytes)):
                decoded_html = quopri.decodestring(raw_payload).decode(
                    "utf-8", errors="replace"
                )
            else:
                continue
            sanitized_html = _sanitize_learnings_html(decoded_html)
            kept_parts.append((content_location, sanitized_html))

    if not kept_parts:
        return None

    out = MIMEMultipart("related", type="text/html")
    out["Subject"] = "Google Developer Profile Learnings (Sanitized)"
    for content_location, sanitized_html in kept_parts:
        html_part = MIMEText(sanitized_html, "html", "utf-8")
        html_part.replace_header("Content-Transfer-Encoding", "quoted-printable")
        qp_bytes = quopri.encodestring(sanitized_html.encode("utf-8"))
        html_part.set_payload(qp_bytes.decode("ascii"))
        html_part["Content-Location"] = content_location
        out.attach(html_part)

    return out.as_bytes()


def process_file(file_path: Path):
    if not file_path.exists():
        print(f"Path not found, skipping: {file_path}")
        return

    if file_path.is_dir():
        targets = sorted(
            p for p in file_path.iterdir() if p.is_file() and ".mhtml" in p.name.lower()
        )
        if not targets:
            print(f"No MHTML files found in {file_path}")
            return
        for target in targets:
            process_file(target)
        return

    raw_bytes = file_path.read_bytes()
    sanitized_bytes = _build_sanitized_mhtml_bytes(raw_bytes)
    if sanitized_bytes is not None:
        file_path.write_bytes(sanitized_bytes)
    else:
        content = raw_bytes.decode("utf-8", errors="ignore")
        sanitized = sanitize_mhtml(content)
        file_path.write_text(sanitized, encoding="utf-8")

    print(f"Sanitized {file_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/sanitize_gdev_mhtml.py <path-to-mhtml-or-dir>")
        sys.exit(1)
    process_file(Path(sys.argv[1]))
