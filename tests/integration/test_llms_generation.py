"""
Integration tests for LLMS generation (generate_llms_txt.py, generate_llms_full.py).
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from generate_llms_full import (
    MONOLITH_CONFIGS as FULL_MONOLITH_CONFIGS,
)
from generate_llms_full import (
    generate_llms_full,
    read_file_safe,
)
from generate_llms_txt import (
    MONOLITH_CONFIGS,
    _get_file_stats,
    _scrape_index,
    calculate_domain_breakdown,
    extract_dataset_items,
    generate_llms_txt,
    read_portfolio_counts,
)


class TestLlmsHelpers:
    """Tests for LLMS helper functions."""

    def test_get_file_stats(self, temp_dir):
        filepath = temp_dir / "test.txt"
        filepath.write_text("Hello world\n" * 100)
        
        size_kb, tokens = _get_file_stats(str(filepath))
        assert size_kb > 0
        assert tokens > 0

    def test_get_file_stats_missing(self, temp_dir):
        size_kb, tokens = _get_file_stats(str(temp_dir / "missing.txt"))
        assert size_kb == 0.0
        assert tokens == 0

    def test_scrape_index(self, temp_dir):
        index_file = temp_dir / "index.md"
        index_file.write_text("Total Records Archived: 123\nTotal Credentials: 456")
        
        import re
        pattern = re.compile(r"Total[^:]*:\**\s*([\d,]+)", re.IGNORECASE)
        
        with patch("generate_llms_txt.ARCHIVE_DIR", str(temp_dir)):
            result = _scrape_index("index.md", pattern)
            assert result == "123"

    def test_scrape_index_missing(self, temp_dir):
        import re
        pattern = re.compile(r"Total[^:]*:\**\s*([\d,]+)", re.IGNORECASE)
        
        with patch("generate_llms_txt.ARCHIVE_DIR", str(temp_dir)):
            result = _scrape_index("missing.md", pattern)
            assert result == "[unavailable]"

    def test_extract_dataset_items(self):
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


class TestPortfolioCounts:
    """Tests for portfolio count scraping."""

    def test_read_portfolio_counts(self, temp_dir):
        # Create mock README
        readme = temp_dir / "README.md"
        readme.write_text("""<!-- MS_LEARN_START -->
Total Experience Points (XP): 100,000
Completed Individual Units: 500
Badges Earned (Profile): 200
<!-- MS_LEARN_END -->
""")
        
        # Create mock index files
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        (archives_dir / "microsoft-learn-index.md").write_text("Total Records Archived: 1000")
        (archives_dir / "google-skills-index.md").write_text("Total Records Archived: 2000")
        
        with patch("generate_llms_txt.README_PATH", str(readme)), \
             patch("generate_llms_txt.ARCHIVE_DIR", str(archives_dir)):
            counts = read_portfolio_counts()
            assert counts["ms_learn_xp"] == "100000"
            assert counts["ms_learn_units"] == "500"
            assert counts["ms_learn_badges"] == "200"
            assert counts["ms_learn_achievements"] == "1000"
            assert counts["gcp_badges"] == "2000"


class TestDomainBreakdown:
    """Tests for domain classification."""

    def test_calculate_domain_breakdown(self, temp_dir):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        
        monolith = archives_dir / "test-complete.md"
        monolith.write_text("""# Complete Archive

## Verified Records Archive

| Date Earned | Credential Name | Issuer | Verification Type |
| :---: | :--- | :--- | :---: |
| 2024-01-15 | **AWS Cloud Security** | AWS | Badge |
| 2024-01-10 | **Google Cloud AI** | Google | Badge |
| 2024-01-05 | **Python Development** | Python | Badge |
""")
        
        with patch("generate_llms_txt.ARCHIVE_DIR", str(archives_dir)):
            domain_counts, total_parsed = calculate_domain_breakdown()
            
            assert total_parsed == 3
            # AWS Cloud Security -> DevOps, Security & Governance (security, cloud)
            # Google Cloud AI -> AI, Machine Learning & Data (ai, cloud)
            # Python Development -> App Engineering & Software Development (python, development)
            assert sum(domain_counts.values()) == 3


class TestLlmsTxtGeneration:
    """Tests for llms.txt generation."""

    def test_generate_llms_txt(self, temp_dir):
        # Create mock files
        readme = temp_dir / "README.md"
        readme.write_text("Test README")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        
        for name, filename in MONOLITH_CONFIGS:
            (archives_dir / filename).write_text(f"# {name}\n\nContent")
        
        (archives_dir / "aws-skills-2024-01-part-01.md").write_text("# Slice")
        
        with patch("generate_llms_txt.README_PATH", str(readme)), \
             patch("generate_llms_txt.ARCHIVE_DIR", str(archives_dir)), \
             patch("generate_llms_txt.LLMS_PATH", str(temp_dir / "llms.txt")), \
             patch("generate_llms_txt.RAW_BASE_URL", "https://raw.githubusercontent.com/test/test/main/archives"), \
             patch("generate_llms_txt.read_portfolio_counts", return_value={
                 "ms_learn_units": "100", "ms_learn_xp": "1000", "ms_learn_badges": "50",
                 "ms_learn_achievements": "200", "gcp_badges": "300", "aws_activities": "400",
                 "credly_credentials": "50", "linkedin_certs": "60", "gdev_badges": "70",
                 "gdev_activities": "80",
             }), \
             patch("generate_llms_txt.calculate_domain_breakdown", return_value=({
                 "🤖 AI, Machine Learning & Data": 100,
                 "🛡️ DevOps, Security & Governance": 50,
                 "☁️ Cloud & Infrastructure": 50,
                 "💻 App Engineering & Software Development": 50,
                 "👔 Enterprise & Professional Development": 50,
             }, 300)):
            
            generate_llms_txt()
            
            output = temp_dir / "llms.txt"
            assert output.exists()
            content = output.read_text()
            assert "Vojislav Miloradovic" in content
            assert "Portfolio Overview" in content
            assert "Domain Focus" in content
            assert "Platform Master Indexes" in content
            assert "Complete Monolithic Datasets" in content
            assert "Latest Chunked Slices" in content


class TestLlmsFullGeneration:
    """Tests for llms-full.txt generation."""

    def test_read_file_safe(self, temp_dir):
        filepath = temp_dir / "test.txt"
        filepath.write_text("Content")
        assert read_file_safe(str(filepath)) == "Content"
        
        assert read_file_safe(str(temp_dir / "missing.txt")) == "\n\n<!-- missing.txt not found -->\n"

    def test_generate_llms_full(self, temp_dir):
        readme = temp_dir / "README.md"
        readme.write_text("# README Content")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        
        for filename, filepath in FULL_MONOLITH_CONFIGS:
            (archives_dir / filename).write_text(f"# {filename}\n\nArchive content")
        
        jsonld = temp_dir / "credentials.jsonld"
        jsonld.write_text('{"@context": "https://schema.org"}')
        
        with patch("generate_llms_full.README_PATH", str(readme)), \
             patch("generate_llms_full.ARCHIVE_DIR", str(archives_dir)), \
             patch("generate_llms_full.JSONLD_PATH", str(jsonld)), \
             patch("generate_llms_full.LLMS_FULL_PATH", str(temp_dir / "llms-full.txt")):
            
            generate_llms_full()
            
            output = temp_dir / "llms-full.txt"
            assert output.exists()
            content = output.read_text()
            assert "VOJISLAV MILORADOVIC" in content
            assert "README.md" in content
            assert "aws-skills-complete.md" in content
            assert "credentials.jsonld" in content