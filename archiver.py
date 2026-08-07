import glob
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
import tiktoken
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# --- Constants ---
RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"
MAX_ALLOWED_DATA_LOSS_PCT = 0.15

_ENCODER = None


# --- Shared Pipeline Custom Exceptions ---
class PipelineDataLossAnomaly(Exception):
    """Raised when incoming dataset drops beyond safety threshold compared to local state."""
    pass


# --- Shared Pipeline HTTP & Network Utilities ---
def get_resilient_session(retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """Configures a requests Session with automated retries and standard headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


# --- Shared Pipeline Data Manipulation & Validation Utilities ---
def normalize_date_string(date_str: str) -> str:
    """Normalizes raw date strings into standard YYYY-MM-DD or YYYY-MM format."""
    if not date_str or not isinstance(date_str, str):
        return ""
    clean = date_str.strip()
    
    # ISO / Standard format check
    m_full = re.match(r"^(\d{4}-\d{2}-\d{2})", clean)
    if m_full:
        return m_full.group(1)
        
    m_ym = re.match(r"^(\d{4}-\d{2})", clean)
    if m_ym:
        return m_ym.group(1)

    # Verbose date parsing fallback (e.g. "Jan 15, 2024")
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return clean


def execute_data_loss_guard(
    incoming_items: list | dict,
    json_path: str | Path,
    max_loss_pct: float = MAX_ALLOWED_DATA_LOSS_PCT,
) -> None:
    """Guards against unexpected dataset truncation by comparing incoming size with existing state."""
    path = Path(json_path)
    if not path.exists():
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            existing_data = json.load(f)

        existing_count = (
            len(existing_data.get("badges", []))
            if isinstance(existing_data, dict) and "badges" in existing_data
            else len(existing_data) if isinstance(existing_data, (list, dict)) else 0
        )
        incoming_count = len(incoming_items) if isinstance(incoming_items, (list, dict)) else 0

        if existing_count > 0 and incoming_count < existing_count:
            loss_pct = (existing_count - incoming_count) / existing_count
            if loss_pct > max_loss_pct:
                raise PipelineDataLossAnomaly(
                    f"Data loss guard anomaly: incoming count ({incoming_count}) is {loss_pct:.1%} lower "
                    f"than stored count ({existing_count}) in {path.name}."
                )
    except (json.JSONDecodeError, OSError):
        pass


def atomic_write_json(destination: str | Path, data: dict | list, indent: int = 2) -> None:
    """Atomically writes JSON content to prevent file corruption during crashes or mid-write exits."""
    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    with tempfile.NamedTemporaryFile("w", dir=dest_path.parent, delete=False, encoding="utf-8") as tmp:
        json.dump(data, tmp, indent=indent, ensure_ascii=False)
        tmp_name = tmp.name

    os.replace(tmp_name, dest_path)


# --- Archiving & Text Utilities ---
def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Calculates exact token counts using tiktoken (cl100k_base),
    falling back to character estimation if tiktoken is unavailable.
    """
    global _ENCODER
    if not text:
        return 0
    try:
        if _ENCODER is None:
            _ENCODER = tiktoken.get_encoding(encoding_name)
        return len(_ENCODER.encode(text))
    except Exception:
        return len(text) // 4


def safe_write_file(filepath: str, new_content: str) -> bool:
    """Writes content to filepath only if content has changed.

    Prevents unnecessary mtime updates and git diff noise.
    Returns True if file was written/updated, False if skipped.
    """
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                if f.read() == new_content:
                    return False
        except Exception:
            pass

    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_content)
    return True


def clean_orphaned_chunks(archive_dir: str, platform_prefix: str, active_filenames: set[str]) -> None:
    """Removes slice files for a platform that are no longer active chunks."""
    pattern = os.path.join(archive_dir, f"{platform_prefix}-*-part-*.md")
    for filepath in glob.glob(pattern):
        filename = os.path.basename(filepath)
        if filename not in active_filenames:
            try:
                os.remove(filepath)
                print(f"  🗑️  Removed orphaned chunk: {filename}")
            except OSError as e:
                print(f"  ⚠️  Failed to remove orphaned chunk {filename}: {e}")


def _extract_ym(date_str: str, default_ym: str) -> str:
    """Extracts YYYY-MM prefix from a date string, falling back to default_ym."""
    if not date_str:
        return default_ym
    m = re.match(r"^(\d{4}-\d{2})", date_str.strip())
    if m:
        return m.group(1)
    m_yr = re.match(r"^(\d{4})", date_str.strip())
    if m_yr:
        return f"{m_yr.group(1)}-01"
    return default_ym


def generate_platform_archive(
    platform_prefix: str,
    platform_name: str,
    table_headers: list[str],
    table_alignments: list[str],
    formatted_rows: list[tuple[str, str]],
    readme_lines: list[str],
    marker_start: str,
    marker_end: str,
    archive_dir: str = "archives",
    readme_path: str = "README.md",
    raw_base_url: str = RAW_BASE_DEFAULT,
    extra_monolith_header_md: str = "",
) -> None:
    """Generates monolithic archive, ~10KB slice archives, platform index,
    and updates README markers cleanly with tail-anchored stable chunking.
    """
    print(f"\n📦 Processing platform archive: {platform_name} ({platform_prefix})")
    os.makedirs(archive_dir, exist_ok=True)

    sanitized_formatted_rows = []
    for r_text, r_date in formatted_rows:
        clean_text = r_text.replace("\r", "").replace("\n", " ").strip()
        sanitized_formatted_rows.append((clean_text, r_date))

    total_entries = len(sanitized_formatted_rows)
    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    monolith_filename = f"{platform_prefix}-complete.md"
    monolith_path = os.path.join(archive_dir, monolith_filename)

    header_line = "| " + " | ".join(table_headers) + " |"
    align_line = "| " + " | ".join(table_alignments) + " |"

    archive_md = [
        f"# Complete {platform_name} Archive\n\n",
        f"This document represents a unified, verifiable list of all {total_entries} records.\n\n",
    ]

    if extra_monolith_header_md:
        archive_md.append(extra_monolith_header_md)

    archive_md.append("## Verified Records Archive\n\n")
    archive_md.append(f"{header_line}\n{align_line}\n")

    for row_text, _ in sanitized_formatted_rows:
        archive_md.append(f"{row_text}\n")

    archive_md.append(f"\n\n[← Back to Index](./{platform_prefix}-index.md) | [← README](../README.md)\n")

    monolith_text = "".join(archive_md)
    mono_written = safe_write_file(monolith_path, monolith_text)

    mono_bytes = os.path.getsize(monolith_path) if os.path.exists(monolith_path) else 0
    mono_kb = round(mono_bytes / 1024, 2)
    mono_tokens = count_tokens(monolith_text)

    mono_status = "✍️  Updated" if mono_written else "⏭️  Unchanged"
    print(f"  {mono_status} monolith: {monolith_filename} ({mono_kb} KB | {mono_tokens:,} tokens | {total_entries} records)")

    oldest_to_newest = sanitized_formatted_rows[::-1]
    raw_chunks_old_to_new = []
    current_chunk_rows = []
    current_chunk_bytes = 0
    MAX_BYTES = 9500

    for row_text, row_date in oldest_to_newest:
        row_len = len(row_text.encode("utf-8"))
        if current_chunk_bytes + row_len > MAX_BYTES and current_chunk_rows:
            raw_chunks_old_to_new.append(current_chunk_rows)
            current_chunk_rows = []
            current_chunk_bytes = 0
        current_chunk_rows.append((row_text, row_date))
        current_chunk_bytes += row_len

    if current_chunk_rows:
        raw_chunks_old_to_new.append(current_chunk_rows)

    total_chunks = len(raw_chunks_old_to_new)
    chunk_meta = []
    chunk_filenames = []

    for i, chunk_rows_old in enumerate(raw_chunks_old_to_new, start=1):
        chunk_rows = chunk_rows_old[::-1]
        start_date = chunk_rows[-1][1]
        end_date = chunk_rows[0][1]

        ym_prefix = _extract_ym(end_date, now_ym)
        chunk_filename = f"{platform_prefix}-{ym_prefix}-part-{i:02d}.md"
        chunk_filenames.append(chunk_filename)

        chunk_meta.append({
            "part": i,
            "filename": chunk_filename,
            "date_range": f"{start_date} to {end_date}",
            "rows": chunk_rows,
        })

    active_filenames = set(chunk_filenames)
    print(f"  🧩 Slicing dataset into {total_chunks} stable chunk file(s):")

    for i, meta in enumerate(chunk_meta, start=1):
        chunk_filename = meta["filename"]
        chunk_rows = meta["rows"]

        prev_link = f"[{chunk_filenames[i-2]}](./{chunk_filenames[i-2]})" if i > 1 else "None"
        next_link = f"[{chunk_filenames[i]}](./{chunk_filenames[i]})" if i < total_chunks else "None"

        c_md = [
            "---",
            f"archive_platform: {platform_name}",
            f"chunk_part: {i} of {total_chunks}",
            f"date_range: {meta['date_range']}",
            f"total_entries: {len(chunk_rows)}",
            f"raw_url: {raw_base_url}/{chunk_filename}",
            "---\n",
            f"# {platform_name} — Part {i:02d}\n",
            f"> **Navigation:** Prev: {prev_link} | [Index](./{platform_prefix}-index.md) | Next: {next_link} | [Complete Archive](./{monolith_filename})\n",
            header_line,
            align_line,
        ]

        for r_text, _ in chunk_rows:
            c_md.append(r_text.strip())

        c_md.append(f"\n---\n> **Navigation:** Prev: {prev_link} | [Index](./{platform_prefix}-index.md) | Next: {next_link}\n")

        content = "\n".join(c_md) + "\n"
        chunk_path = os.path.join(archive_dir, chunk_filename)
        chunk_written = safe_write_file(chunk_path, content)

        file_size_kb = round(len(content.encode("utf-8")) / 1024, 2)
        exact_tokens = count_tokens(content)

        meta["size_kb"] = file_size_kb
        meta["tokens"] = exact_tokens
        meta["entries"] = len(chunk_rows)
        meta["raw_url"] = f"{raw_base_url}/{chunk_filename}"

        slice_status = "✍️  Updated" if chunk_written else "⏭️  Unchanged"
        print(f"     [{i:02d}/{total_chunks:02d}] {slice_status}: {chunk_filename} ({file_size_kb} KB | {exact_tokens:,} tokens | {len(chunk_rows)} entries)")

    clean_orphaned_chunks(archive_dir, platform_prefix, active_filenames)

    index_filename = f"{platform_prefix}-index.md"
    index_path = os.path.join(archive_dir, index_filename)

    idx_md = [
        f"# {platform_name} Index\n",
        f"This directory provides chunked, AI-readable historical records for {platform_name}.\n",
        "## Archive Overview\n",
        f"- **Total Records Archived:** {total_entries}",
        f"- **Monolithic File Size:** ~{mono_kb} KB ({mono_tokens:,} tokens)",
        f"- **Total Chunk Parts:** {total_chunks} chunk(s)\n",
        "### Monolithic Archive (Complete)\n",
        "| File Name | Size (KB) | Tokens | Recommended For | Direct Raw URL |",
        "| :--- | :---: | :---: | :--- | :--- |",
        f"| [`{monolith_filename}`](./{monolith_filename}) | {mono_kb} KB | {mono_tokens:,} | Large Context Windows (>100k tokens) | [Raw Link]({raw_base_url}/{monolith_filename}) |\n",
        "### Chunked Archive Parts (~10 KB Slices)\n",
        "| Part | File Name | Date Range | Entries | Size (KB) | Tokens | Direct Raw URL |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for cm in reversed(chunk_meta):
        idx_md.append(
            f"| Part {cm['part']:02d} | [`{cm['filename']}`](./{cm['filename']}) | `{cm['date_range']}` | {cm['entries']} | {cm['size_kb']} KB | {cm['tokens']:,} | [Raw URL]({cm['raw_url']}) |"
        )

    idx_md.append("\n\n[← Back to Main README](../README.md)\n")
    idx_written = safe_write_file(index_path, "\n".join(idx_md) + "\n")

    idx_status = "✍️  Updated" if idx_written else "⏭️  Unchanged"
    print(f"  {idx_status} index: {index_filename}")

    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        if marker_start in content and marker_end in content:
            before = content.split(marker_start)[0]
            after = content.split(marker_end)[1]
            new_block = "\n".join(readme_lines) + "\n"
            new_content = f"{before}{marker_start}\n{new_block}{marker_end}{after}"
            readme_written = safe_write_file(readme_path, new_content)

            readme_status = "✍️  Updated" if readme_written else "⏭️  Unchanged"
            print(f"  {readme_status} README markers: {readme_path}")
