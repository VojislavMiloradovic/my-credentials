"""
Integration tests for LinkedIn pipeline (update_linkedin.py).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from update_linkedin import (
    MARKER_END,
    MARKER_START,
    LinkedInCertModel,
    execute_data_loss_guard,
    locate_certifications_csv,
    main,
    parse_certifications_csv,
    parse_linkedin_date,
)


class TestLinkedInHelpers:
    """Tests for LinkedIn helper functions."""

    @pytest.mark.parametrize("input_val,expected", [
        ("Jan 2024", "2024-01"),
        ("January 2024", "2024-01"),
        ("2024-01", "2024-01"),
        ("2024-01-15", "2024-01-15"),
        ("Mar 2024", "2024-03"),
        ("", "N/A"),
        (None, "N/A"),
    ])
    def test_parse_linkedin_date(self, input_val, expected):
        assert parse_linkedin_date(input_val) == expected


class TestLinkedInModels:
    """Tests for LinkedIn Pydantic models."""

    def test_linkedin_cert_model_valid(self, linkedin_cert_builder):
        cert = linkedin_cert_builder()
        model = LinkedInCertModel(**cert)
        assert model.name == cert["name"]
        assert model.authority == cert["authority"]

    def test_linkedin_cert_model_date_coercion(self):
        cert = LinkedInCertModel(
            name="Test",
            authority="Test",
            issued="Jan 2024",
        )
        assert cert.issued == "2024-01"


class TestLinkedInParsers:
    """Tests for LinkedIn parsing functions."""

    def test_locate_certifications_csv(self, temp_dir, sample_linkedin_csv_tab):
        csv_file = temp_dir / "Certifications.csv"
        csv_file.write_text(sample_linkedin_csv_tab)
        
        with patch("update_linkedin.os.path.exists", lambda p: p == str(csv_file)), \
             patch("update_linkedin.glob.glob", return_value=[]):
            found = locate_certifications_csv()
            assert found == str(csv_file)

    def test_parse_certifications_csv_tab(self, temp_dir, sample_linkedin_csv_tab):
        csv_file = temp_dir / "Certifications.csv"
        csv_file.write_text(sample_linkedin_csv_tab)
        
        certs = parse_certifications_csv(str(csv_file))
        assert len(certs) == 2
        assert certs[0]["name"] == "Python Certification"
        assert certs[0]["license"] == "LIC-001"

    def test_parse_certifications_csv_comma(self, temp_dir, sample_linkedin_csv_comma):
        csv_file = temp_dir / "Certifications.csv"
        csv_file.write_text(sample_linkedin_csv_comma)
        
        certs = parse_certifications_csv(str(csv_file))
        assert len(certs) == 2
        assert certs[0]["license"] == "LIC-001"

    def test_parse_certifications_csv_date_heuristic(self, temp_dir):
        """Test date heuristic swap when dates appear inverted."""
        csv_content = "Name,Authority,Url,License Number,Started On,Finished On\nFuture Cert,Test,,LIC-001,Dec 2025,Jan 2024\n"
        csv_file = temp_dir / "Certifications.csv"
        csv_file.write_text(csv_content)
        
        certs = parse_certifications_csv(str(csv_file))
        # Should swap because Started > Finished and Finished <= current
        assert certs[0]["issued"] == "2024-01"


class TestLinkedInLossGuard:
    """Tests for LinkedIn loss guard functions."""

    def test_execute_data_loss_guard(self, temp_dir):
        monolith = temp_dir / "linkedin-certifications-complete.md"
        monolith.write_text("""# Header

| Date Completed | Certification Title | Issuing Authority | Verification Reference |
| :---: | :--- | :--- | :--- |
| 2024-01 | Cert 1 | Authority 1 | [Verify](url) |
| 2024-02 | Cert 2 | Authority 2 | [Verify](url) |
| 2024-03 | Cert 3 | Authority 3 | [Verify](url) |
""")
        
        certs = [
            {"name": "Cert 1", "authority": "Authority 1", "issued": "2024-01"},
            {"name": "Cert 2", "authority": "Authority 2", "issued": "2024-02"},
            {"name": "Cert 3", "authority": "Authority 3", "issued": "2024-03"},
        ]
        
        with patch("update_linkedin.ARCHIVE_MONOLITH", str(monolith)):
            execute_data_loss_guard(certs)


class TestLinkedInPipelineIntegration:
    """Integration tests for the full LinkedIn pipeline."""

    def test_main_pipeline_success(self, temp_dir, sample_linkedin_csv_tab, mock_archiver, mock_loss_guard, mock_retired_rules):
        csv_file = temp_dir / "Certifications.csv"
        csv_file.write_text(sample_linkedin_csv_tab)
        
        readme = temp_dir / "README.md"
        readme.write_text(f"Before\n{MARKER_START}\nOld\n{MARKER_END}\nAfter")
        
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        validation_dir = temp_dir / "for_validation"
        validation_dir.mkdir()
        
        with patch("update_linkedin.README_PATH", str(readme)), \
             patch("update_linkedin.ARCHIVE_DIR", str(archives_dir)), \
             patch("update_linkedin.ARCHIVE_MONOLITH", str(archives_dir / "linkedin-certifications-complete.md")), \
             patch("update_linkedin.VALIDATION_DIR", str(validation_dir)), \
             patch("update_linkedin.locate_certifications_csv", return_value=str(csv_file)):
            
            main()
            
            validation_file = validation_dir / "linkedin-certifications.json"
            assert validation_file.exists()
            data = json.loads(validation_file.read_text())
            assert data["platform"] == "linkedin-certifications"
            assert len(data["certifications"]) == 2