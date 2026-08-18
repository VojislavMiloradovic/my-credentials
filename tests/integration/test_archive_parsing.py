"""
Integration tests for archive parsing utilities.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from archiver import (
    generate_platform_archive,
)
from generate_jsonld import extract_table_data_rows
from generate_jsonld import extract_table_data_rows as jsonld_extract_table_data_rows
from generate_llms_txt import extract_dataset_items


class TestArchiveParsing:
    """Tests for shared archive parsing utilities."""

    def test_extract_table_data_rows_archiver(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| :--- | :--- |",
            "| Cell 1 | Cell 2 |",
            "| Cell 3 | Cell 4 |",
            "Not a table",
        ]
        rows = extract_table_data_rows(lines)
        assert len(rows) == 2
        assert rows[0][0] == ["header 1", "header 2"]
        assert rows[0][1] == ["Cell 1", "Cell 2"]

    def test_extract_table_data_rows_jsonld(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| :--- | :--- |",
            "| Cell 1 | Cell 2 |",
            "| Cell 3 | Cell 4 |",
        ]
        rows = jsonld_extract_table_data_rows(lines)
        assert len(rows) == 2

    def test_extract_dataset_items_llms(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| :--- | :--- |",
            "| Cell 1 | Cell 2 |",
            "- Bullet item",
            "* Another bullet",
            "Normal text",
        ]
        items = extract_dataset_items(lines)
        assert len(items) == 3
        assert items[0] == "| Cell 1 | Cell 2 |"
        assert items[1] == "- Bullet item"
        assert items[2] == "* Another bullet"

    def test_parsing_consistency(self):
        """All three parsing functions should handle the same table format."""
        lines = [
            "| Date | Title | Issuer |",
            "| :---: | :--- | :--- |",
            "| 2024-01-15 | Badge 1 | AWS |",
            "| 2024-01-10 | Badge 2 | Google |",
        ]

        archiver_rows = extract_table_data_rows(lines)
        jsonld_rows = jsonld_extract_table_data_rows(lines)
        llms_items = extract_dataset_items(lines)

        # archiver and jsonld should return same structure
        assert archiver_rows == jsonld_rows
        # llms should include table rows as items
        assert len(llms_items) == 2
        assert llms_items[0] == "| 2024-01-15 | Badge 1 | AWS |"

    def test_parsing_multiple_tables(self):
        lines = [
            "| Table 1 | Col |",
            "| :--- | :--- |",
            "| A | B |",
            "",
            "| Table 2 | Col |",
            "| :--- | :--- |",
            "| C | D |",
        ]

        archiver_rows = extract_table_data_rows(lines)
        # Should find both tables
        assert len(archiver_rows) == 2

    def test_parsing_malformed_table(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| Cell 1 | Cell 2 |",  # Missing separator row
            "| Cell 3 | Cell 4 |",
        ]
        rows = extract_table_data_rows(lines)
        assert rows == []  # No separator = not a table

    def test_parsing_empty_table(self):
        lines = [
            "| Header 1 | Header 2 |",
            "| :--- | :--- |",
        ]
        rows = extract_table_data_rows(lines)
        assert rows == []


class TestArchiveGenerationRoundtrip:
    """Tests for archive generation and parsing roundtrip."""

    def test_generate_then_parse(self, temp_dir):
        """Generate archive then parse it back."""
        formatted_rows = [
            (
                "| 2024-01-15 | [Badge 1](https://example.com/1) | AWS | Badge |",
                "2024-01-15",
            ),
            ("| 2024-01-10 | Badge 2 | AWS | Badge |", "2024-01-10"),
        ]
        readme_lines = [
            "### Test Platform",
            "",
            "**Total Portfolio Credentials:** 2",
            "",
            "| Date Earned | Credential Name | Issuer | Verification Type |",
            "| :---: | :--- | :--- | :---: |",
            "| 2024-01-15 | [Badge 1](https://example.com/1) | AWS | Badge |",
            "| 2024-01-10 | Badge 2 | AWS | Badge |",
        ]

        archive_dir = str(temp_dir / "archives")
        readme_path = str(temp_dir / "README.md")

        _ = generate_platform_archive(
            platform_prefix="test-platform",
            platform_name="Test Platform",
            table_headers=[
                "Date Earned",
                "Credential Name",
                "Issuer",
                "Verification Type",
            ],
            table_alignments=[":---:", ":---", ":---", ":---:"],
            formatted_rows=formatted_rows,
            readme_lines=readme_lines,
            marker_start="<!-- TEST_START -->",
            marker_end="<!-- TEST_END -->",
            archive_dir=archive_dir,
            readme_path=readme_path,
        )

        # Parse the generated monolith
        monolith_path = Path(archive_dir) / "test-platform-complete.md"
        content = monolith_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        from generate_jsonld import extract_table_data_rows

        parsed_rows = extract_table_data_rows(lines)

        assert len(parsed_rows) == 2
        assert "Badge 1" in parsed_rows[0][1][1]
        assert "Badge 2" in parsed_rows[1][1][1]
