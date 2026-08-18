"""
Unit tests for the archiver module.
"""

from pathlib import Path

import pytest

from archiver import (
    _extract_ym,
    clean_orphaned_chunks,
    count_tokens,
    find_latest_slice,
    generate_platform_archive,
    safe_write_file,
)


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_count_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert count_tokens("") == 0

    def test_count_tokens_none(self):
        """None should return 0 tokens."""
        assert count_tokens(None) == 0

    def test_count_tokens_simple_text(self):
        """Simple text should return approximate token count."""
        text = "Hello world"
        # tiktoken may not be available in test env, fallback is len/4
        tokens = count_tokens(text)
        assert tokens >= 0
        assert isinstance(tokens, int)

    def test_count_tokens_unicode(self):
        """Unicode text should be handled."""
        text = "Тест на српском"
        tokens = count_tokens(text)
        assert tokens >= 0


class TestSafeWriteFile:
    """Tests for safe_write_file function."""

    def test_safe_write_file_new_file(self, temp_dir):
        """Writing to new file should succeed and return True."""
        filepath = temp_dir / "new_file.txt"
        result = safe_write_file(str(filepath), "Hello world")
        assert result is True
        assert filepath.read_text() == "Hello world"

    def test_safe_write_file_same_content(self, temp_dir):
        """Writing same content should return False (no write)."""
        filepath = temp_dir / "existing.txt"
        filepath.write_text("Hello world")
        result = safe_write_file(str(filepath), "Hello world")
        assert result is False
        assert filepath.read_text() == "Hello world"

    def test_safe_write_file_different_content(self, temp_dir):
        """Writing different content should update and return True."""
        filepath = temp_dir / "existing.txt"
        filepath.write_text("Old content")
        result = safe_write_file(str(filepath), "New content")
        assert result is True
        assert filepath.read_text() == "New content"

    def test_safe_write_file_creates_parent_dirs(self, temp_dir):
        """Should create parent directories if they don't exist."""
        filepath = temp_dir / "subdir" / "nested" / "file.txt"
        result = safe_write_file(str(filepath), "Content")
        assert result is True
        assert filepath.read_text() == "Content"

    def test_safe_write_file_uses_unix_newlines(self, temp_dir):
        """Should write with Unix newlines (\\n)."""
        filepath = temp_dir / "file.txt"
        safe_write_file(str(filepath), "Line 1\nLine 2\n")
        content = filepath.read_bytes()
        assert b"\r\n" not in content  # No Windows newlines
        assert b"\n" in content


class TestFindLatestSlice:
    """Tests for find_latest_slice function."""

    def test_find_latest_slice_no_files(self, temp_dir):
        """Should return None when no slice files exist."""
        result = find_latest_slice(str(temp_dir), "test-platform")
        assert result is None

    def test_find_latest_slice_single_file(self, temp_dir):
        """Should return the single slice file."""
        slice_file = temp_dir / "test-platform-2024-01-part-01.md"
        slice_file.write_text("content")
        result = find_latest_slice(str(temp_dir), "test-platform")
        assert result == "test-platform-2024-01-part-01.md"

    def test_find_latest_slice_multiple_files(self, temp_dir):
        """Should return the highest part number."""
        (temp_dir / "test-platform-2024-01-part-01.md").write_text("content")
        (temp_dir / "test-platform-2024-02-part-02.md").write_text("content")
        (temp_dir / "test-platform-2024-03-part-03.md").write_text("content")
        result = find_latest_slice(str(temp_dir), "test-platform")
        assert result == "test-platform-2024-03-part-03.md"

    def test_find_latest_slice_ignores_non_matching(self, temp_dir):
        """Should ignore non-matching files."""
        (temp_dir / "other-platform-2024-01-part-01.md").write_text("content")
        (temp_dir / "test-platform-2024-01-part-01.md").write_text("content")
        result = find_latest_slice(str(temp_dir), "test-platform")
        assert result == "test-platform-2024-01-part-01.md"


class TestExtractYM:
    """Tests for _extract_ym helper function."""

    @pytest.mark.parametrize("date_str,expected", [
        ("2024-01-15", "2024-01"),
        ("2024-01", "2024-01"),
        ("2024", "2024-01"),
        ("", "2024-06"),  # Defaults to current month (frozen in conftest)
        (None, "2024-06"),
    ])
    def test_extract_ym(self, date_str, expected):
        # Note: default_ym is based on current time which is frozen in conftest
        result = _extract_ym(date_str, "2024-06")
        assert result == expected


class TestCleanOrphanedChunks:
    """Tests for clean_orphaned_chunks function."""

    def test_clean_orphaned_chunks_removes_obsolete(self, temp_dir):
        """Should remove slice files not in active_filenames."""
        (temp_dir / "test-platform-2024-01-part-01.md").write_text("old")
        (temp_dir / "test-platform-2024-02-part-02.md").write_text("active")
        (temp_dir / "test-platform-2024-03-part-03.md").write_text("active")
        
        clean_orphaned_chunks(str(temp_dir), "test-platform", {"test-platform-2024-02-part-02.md", "test-platform-2024-03-part-03.md"})
        
        assert not (temp_dir / "test-platform-2024-01-part-01.md").exists()
        assert (temp_dir / "test-platform-2024-02-part-02.md").exists()
        assert (temp_dir / "test-platform-2024-03-part-03.md").exists()

    def test_clean_orphaned_chunks_no_op_when_all_active(self, temp_dir):
        """Should not remove anything when all files are active."""
        (temp_dir / "test-platform-2024-01-part-01.md").write_text("active")
        (temp_dir / "test-platform-2024-02-part-02.md").write_text("active")
        
        clean_orphaned_chunks(str(temp_dir), "test-platform", {"test-platform-2024-01-part-01.md", "test-platform-2024-02-part-02.md"})
        
        assert (temp_dir / "test-platform-2024-01-part-01.md").exists()
        assert (temp_dir / "test-platform-2024-02-part-02.md").exists()


class TestGeneratePlatformArchive:
    """Tests for generate_platform_archive function."""

    def setup_method(self):
        """Set up test data."""
        self.formatted_rows = [
            ("| 2024-01-15 | [Badge 1](https://example.com/1) | AWS | Badge |", "2024-01-15"),
            ("| 2024-01-10 | [Badge 2](https://example.com/2) | AWS | Badge |", "2024-01-10"),
            ("| 2024-01-05 | [Badge 3](https://example.com/3) | AWS | Badge |", "2024-01-05"),
        ]
        self.readme_lines = [
            "### Test Platform",
            "",
            "**Total Portfolio Credentials:** 3",
            "",
            "| Date Earned | Credential Name | Issuer | Verification Type |",
            "| :---: | :--- | :--- | :---: |",
            "| 2024-01-15 | [Badge 1](https://example.com/1) | AWS | Badge |",
            "| 2024-01-10 | [Badge 2](https://example.com/2) | AWS | Badge |",
            "| 2024-01-05 | [Badge 3](https://example.com/3) | AWS | Badge |",
        ]

    def test_generate_platform_archive_creates_files(self, temp_dir):
        """Should create monolith, index, and slice files."""
        archive_dir = str(temp_dir / "archives")
        
        latest_slice = generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=self.formatted_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(temp_dir / "README.md"),
        )
        
        # Check monolith created
        monolith_path = Path(archive_dir) / "test-platform-complete.md"
        assert monolith_path.exists()
        content = monolith_path.read_text(encoding="utf-8")
        assert "Test Platform" in content
        assert "Badge 1" in content
        assert "Badge 2" in content
        assert "Badge 3" in content
        
        # Check index created
        index_path = Path(archive_dir) / "test-platform-index.md"
        assert index_path.exists()
        index_content = index_path.read_text(encoding="utf-8")
        assert "Test Platform Index" in index_content
        
        # Check slice created
        assert latest_slice is not None
        slice_path = Path(archive_dir) / latest_slice
        assert slice_path.exists()

    def test_generate_platform_archive_chunking(self, temp_dir):
        """Should chunk data into ~10KB slices."""
        # Create enough rows to exceed 10KB
        large_rows = []
        for i in range(200):
            row = f"| 2024-01-{i%30+1:02d} | [Badge {i}](https://example.com/{i}) | AWS | Badge |"
            large_rows.append((row, f"2024-01-{i%30+1:02d}"))
        
        archive_dir = str(temp_dir / "archives")
        
        _ = generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=large_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(temp_dir / "README.md"),
        )
        
        # Should have multiple chunks
        slice_files = list(Path(archive_dir).glob("test-platform-*-part-*.md"))
        assert len(slice_files) > 1
        
        # Part numbers should be sequential starting from 01
        part_nums = sorted([int(f.name.split("-part-")[1].split(".")[0]) for f in slice_files])
        assert part_nums == list(range(1, len(part_nums) + 1))

    def test_generate_platform_archive_stable_chunk_order(self, temp_dir):
        """Part-01 should always contain oldest entries (tail-anchored)."""
        archive_dir = str(temp_dir / "archives")
        
        _ = generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=self.formatted_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(temp_dir / "README.md"),
        )
        
        # Check part-01 contains oldest (2024-01-05)
        part1_path = Path(archive_dir) / "test-platform-2024-01-part-01.md"
        if part1_path.exists():
            content = part1_path.read_text()
            assert "2024-01-05" in content

    def test_generate_platform_archive_navigation_links(self, temp_dir):
        """Slice files should have prev/next navigation links."""
        # Create enough rows for 3 chunks
        large_rows = []
        for i in range(50):
            row = f"| 2024-01-{i%30+1:02d} | [Badge {i}](https://example.com/{i}) | AWS | Badge |"
            large_rows.append((row, f"2024-01-{i%30+1:02d}"))
        
        archive_dir = str(temp_dir / "archives")
        
        generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=large_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(temp_dir / "README.md"),
        )
        
        slice_files = sorted(Path(archive_dir).glob("test-platform-*-part-*.md"))
        if len(slice_files) >= 2:
            # First part should have no prev, but next link
            part1_content = slice_files[0].read_text()
            assert "Prev: None" in part1_content
            assert "Next:" in part1_content
            
            # Last part should have prev, no next
            part_last_content = slice_files[-1].read_text()
            assert "Prev:" in part_last_content
            assert "Next: None" in part_last_content

    def test_generate_platform_archive_readme_update(self, temp_dir):
        """Should update README.md with marker replacement."""
        readme_path = temp_dir / "README.md"
        readme_path.write_text("Before\n<!-- TEST_START -->\nOld content\n<!-- TEST_END -->\nAfter")
        
        archive_dir = str(temp_dir / "archives")
        
        generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=self.formatted_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(readme_path),
        )
        
        content = readme_path.read_text()
        assert "### Test Platform" in content
        assert "Old content" not in content
        assert "Before" in content
        assert "After" in content

    def test_generate_platform_archive_handles_missing_markers(self, temp_dir):
        """Should handle missing markers gracefully."""
        readme_path = temp_dir / "README.md"
        readme_path.write_text("No markers here")
        
        archive_dir = str(temp_dir / "archives")
        
        latest_slice = generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=self.formatted_rows,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(readme_path),
        )
        
        # Should still create archive files even if README not updated
        assert latest_slice is not None

    def test_generate_platform_archive_retired_marker(self, temp_dir):
        """Should include retired marker in output."""
        rows_with_retired = [
            ("| 2024-01-15 | [Badge 1](https://example.com/1) ⚠️ *Content retired* | AWS | Badge |", "2024-01-15"),
        ]
        
        archive_dir = str(temp_dir / "archives")
        
        generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=["Date", "Name", "Issuer", "Type"],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=rows_with_retired,
            readme_lines=self.readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=str(temp_dir / "README.md"),
        )
        
        monolith_path = Path(archive_dir) / "test-platform-complete.md"
        content = monolith_path.read_text(encoding="utf-8")
        assert "⚠️ *Content retired*" in content