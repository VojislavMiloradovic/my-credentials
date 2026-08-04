import glob
import os
from datetime import datetime, timezone

RAW_BASE_DEFAULT = "https://raw.githubusercontent.com/VojislavMiloradovic/my-credentials/main/archives"


def clean_old_chunks(archive_dir: str, platform_prefix: str) -> None:
    """Removes existing slice files for a given platform prefix."""
    pattern = os.path.join(archive_dir, f"{platform_prefix}-*-part-*.md")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass


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

    and updates README markers cleanly.
    """
    os.makedirs(archive_dir, exist_ok=True)
    clean_old_chunks(archive_dir, platform_prefix)

    # Sanitize and ensure row texts are clean single-line table rows
    sanitized_formatted_rows = []
    for r_text, r_date in formatted_rows:
        clean_text = r_text.replace("\r", "").replace("\n", " ").strip()
        sanitized_formatted_rows.append((clean_text, r_date))

    total_entries = len(sanitized_formatted_rows)
    now_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    # 1. Monolithic Complete File
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

    with open(monolith_path, "w", encoding="utf-8") as f:
        f.write("".join(archive_md))

    # 2. Chunking Logic (~10 KB limit per file)
    chunks = []
    current_chunk_rows = []
    current_chunk_bytes = 0
    MAX_BYTES = 9500

    for row_text, row_date in sanitized_formatted_rows:
        row_len = len(row_text.encode("utf-8"))
        if current_chunk_bytes + row_len > MAX_BYTES and current_chunk_rows:
            chunks.append(current_chunk_rows)
            current_chunk_rows = []
            current_chunk_bytes = 0
        current_chunk_rows.append((row_text, row_date))
        current_chunk_bytes += row_len

    if current_chunk_rows:
        chunks.append(current_chunk_rows)

    total_chunks = len(chunks)
    chunk_meta = []

    for i, chunk_rows in enumerate(chunks, start=1):
        chunk_filename = f"{platform_prefix}-{now_ym}-part-{i:02d}.md"
        chunk_path = os.path.join(archive_dir, chunk_filename)

        start_date = chunk_rows[-1][1]
        end_date = chunk_rows[0][1]

        prev_link = (
            f"[{platform_prefix}-{now_ym}-part-{i-1:02d}.md]({platform_prefix}-{now_ym}-part-{i-1:02d}.md)"
            if i > 1
            else "None"
        )
        next_link = (
            f"[{platform_prefix}-{now_ym}-part-{i+1:02d}.md]({platform_prefix}-{now_ym}-part-{i+1:02d}.md)"
            if i < total_chunks
            else "None"
        )

        c_md = [
            "---",
            f"archive_platform: {platform_name}",
            f"chunk_part: {i} of {total_chunks}",
            f"date_range: {start_date} to {end_date}",
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

        content = "\n".join(c_md)
        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(content)

        file_size_kb = round(len(content.encode("utf-8")) / 1024, 2)
        est_tokens = int(len(content) / 4)
        chunk_meta.append({
            "filename": chunk_filename,
            "part": i,
            "date_range": f"{start_date} to {end_date}",
            "size_kb": file_size_kb,
            "tokens": est_tokens,
            "entries": len(chunk_rows),
            "raw_url": f"{raw_base_url}/{chunk_filename}",
        })

    # 3. Master Platform Index File
    index_filename = f"{platform_prefix}-index.md"
    index_path = os.path.join(archive_dir, index_filename)

    mono_bytes = os.path.getsize(monolith_path) if os.path.exists(monolith_path) else 0
    mono_kb = round(mono_bytes / 1024, 2)
    mono_tokens = int(mono_bytes / 4)

    idx_md = [
        f"# {platform_name} Index\n",
        f"This directory provides chunked, AI-readable historical records for {platform_name}.\n",
        "## Archive Overview\n",
        f"- **Total Records Archived:** {total_entries}",
        f"- **Monolithic File Size:** ~{mono_kb} KB (~{mono_tokens:,} tokens)",
        f"- **Total Chunk Parts:** {total_chunks} chunk(s)\n",
        "### Monolithic Archive (Complete)\n",
        "| File Name | Size (KB) | Est. Tokens | Recommended For | Direct Raw URL |",
        "| :--- | :---: | :---: | :--- | :--- |",
        f"| [`{monolith_filename}`](./{monolith_filename}) | {mono_kb} KB | ~{mono_tokens:,} | Large Context Windows (>100k tokens) | [Raw Link]({raw_base_url}/{monolith_filename}) |\n",
        "### Chunked Archive Parts (~10 KB Slices)\n",
        "| Part | File Name | Date Range | Entries | Size (KB) | Est. Tokens | Direct Raw URL |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for cm in chunk_meta:
        idx_md.append(
            f"| Part {cm['part']:02d} | [`{cm['filename']}`](./{cm['filename']}) | `{cm['date_range']}` | {cm['entries']} | {cm['size_kb']} KB | ~{cm['tokens']} | [Raw URL]({cm['raw_url']}) |"
        )

    idx_md.append("\n\n[← Back to Main README](../README.md)\n")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(idx_md))

    # 4. Update README.md
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        if marker_start in content and marker_end in content:
            before = content.split(marker_start)[0]
            after = content.split(marker_end)[1]
            new_block = "\n".join(readme_lines) + "\n"
            new_content = f"{before}{marker_start}\n{new_block}{marker_end}{after}"

            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(new_content)
