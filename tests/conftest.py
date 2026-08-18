"""
Shared pytest configuration and fixtures for my-credentials test suite.
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import responses
from freezegun import freeze_time

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# ==============================================================================
# PYTEST CONFIGURATION
# ==============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests for core modules")
    config.addinivalue_line("markers", "integration: Integration tests for provider pipelines")
    config.addinivalue_line("markers", "smoke: CLI smoke tests")
    config.addinivalue_line("markers", "slow: Tests that take longer than 5 seconds")


# ==============================================================================
# SHARED FIXTURES
# ==============================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """Provides isolated temporary directory for each test."""
    return tmp_path


@pytest.fixture
def mock_responses():
    """Provides responses mock for HTTP requests."""
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def freeze_time_now():
    """Freeze time to a fixed timestamp for deterministic tests."""
    with freeze_time("2024-06-15 12:00:00", tz_offset=0) as frozen:
        yield frozen


@pytest.fixture
def sample_aws_csv():
    """AWS CSV export fixture with various date formats and edge cases."""
    return """Title,Type,Completed On,URL,Image URL,ID
"AWS Cloud Practitioner Essentials","Digital course","Jan 15, 2024","https://example.com/1","https://img.com/1","aws-001"
"Amazon S3 Primer","Digital course","2024-02-20","https://example.com/2","","aws-002"
"AWS Lambda Foundations","Digital course","Mar 10, 2024","","https://img.com/3",""
"Invalid Entry","","","","",""
"Another Course","Digital course","Apr 5, 2024","https://example.com/4","https://img.com/4","aws-004"
"""


@pytest.fixture
def sample_aws_api_response():
    """AWS Skills API JSON response fixture."""
    return {
        "badges": [
            {
                "id": "aws-001",
                "title": "AWS Cloud Practitioner Essentials",
                "issued_at": "2024-01-15T10:00:00Z",
                "verify_url": "https://skillsprofile.skillbuilder.aws/user/test/badges/aws-001",
                "image_url": "https://img.com/1",
                "type": "AWS Skill Builder Badge",
                "skills": ["AWS", "Cloud Practitioner"],
            },
            {
                "id": "aws-002",
                "title": "Amazon S3 Primer",
                "issued_at": "1708435200000",
                "verify_url": "https://skillsprofile.skillbuilder.aws/user/test/badges/aws-002",
                "image_url": "",
                "type": "AWS Skill Builder Badge",
                "skills": ["S3", "Storage"],
            },
        ]
    }


@pytest.fixture
def sample_google_skills_json():
    """Google Skills API JSON response fixture."""
    return {
        "badges": [
            {
                "id": "123",
                "title": "Google Cloud Fundamentals",
                "earned_at": "2024-01-15T10:00:00Z",
                "verify_url": "https://skills.google/badges/123",
                "image_url": "https://img.com/1",
                "type": "Google Skill Badge",
                "skills": ["Google Cloud"],
            },
            {
                "id": "456",
                "title": "Kubernetes Engine Basics",
                "earned_at": "1705238400000",
                "verify_url": "https://skills.google/badges/456",
                "image_url": "",
                "type": "Google Skill Badge",
                "skills": ["Kubernetes"],
            },
        ]
    }


@pytest.fixture
def sample_google_skills_html():
    """Google Skills HTML profile page for scraping fallback."""
    return """
    <html>
    <body>
        <div class="public-profile-badge">
            <h3 class="title">Google Cloud Fundamentals</h3>
            <span class="date">Jan 15, 2024</span>
            <a href="/public_profiles/test/badges/123" class="link">Verify</a>
            <img src="https://img.com/1" class="image">
        </div>
        <div class="public-profile-badge">
            <h3 class="title">Kubernetes Engine Basics</h3>
            <span class="date">Feb 10, 2024</span>
            <a href="/public_profiles/test/badges/456" class="link">Verify</a>
            <img src="https://img.com/2" class="image">
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_ms_learn_json():
    """Microsoft Learn export JSON fixture with all data sections."""
    return {
        "Progress": {
            "completedLearningItems": [
                {"name": "Unit 1", "completedOn": "2024-01-10"},
                {"name": "Unit 2", "completedOn": "2024-01-12"},
            ],
            "learningPathPasses": [
                {
                    "id": "learn.path-1",
                    "title": "Azure Fundamentals",
                    "grantedOn": "2024-01-15",
                    "url": "learn.azure-fundamentals",
                }
            ],
            "moduleAssessments": [
                {
                    "id": "mod-1",
                    "title": "Cloud Concepts",
                    "grantedOn": "2024-01-10",
                    "url": "learn.cloud-concepts",
                }
            ],
        },
        "XP": {
            "xp": {"totalXp": 100000, "level": {"levelNumber": 5}},
            "achievements": [
                {
                    "id": "ACH001",
                    "title": "First Module",
                    "category": "module",
                    "grantedOn": "2024-01-15",
                    "url": "learn.module-1",
                },
                {
                    "id": "ACH002",
                    "title": "Learning Path Complete",
                    "category": "learningpath",
                    "grantedOn": "2024-01-20",
                    "url": "learn.path-1",
                },
                {
                    "id": "ACH003",
                    "title": "Trophy Unlocked",
                    "category": "trophy",
                    "grantedOn": "2024-01-25",
                    "url": "learn.trophy-1",
                },
            ],
        },
        "VerifiableCredentials": {
            "userCredentials": [
                {
                    "credentialId": "CRED001",
                    "sourceUid": "applied-skill.abc",
                    "awardedOn": "2024-02-01",
                    "credentialStatus": "Active",
                }
            ]
        },
    }


@pytest.fixture
def sample_credly_api_page1():
    """Credly API page 1 response fixture."""
    return {
        "data": [
            {
                "id": "badge-001",
                "badge_template": {
                    "name": "Python Developer",
                    "issuer": {"summary": "Python Institute"},
                    "image_url": "https://img.credly.com/1",
                    "skills": [{"name": "Python"}, {"name": "Development"}],
                },
                "issued_at": "2024-01-15T10:00:00Z",
            },
            {
                "id": "badge-002",
                "badge_template": {
                    "name": "AWS Certified",
                    "issuer": {"summary": "Amazon Web Services"},
                    "image_url": "https://img.credly.com/2",
                    "skills": [{"name": "AWS"}],
                },
                "issued_at": "2024-02-20T10:00:00Z",
            },
        ],
        "metadata": {"next_page": 2, "next_page_url": "https://www.credly.com/users/test/badges.json?page=2"},
    }


@pytest.fixture
def sample_credly_api_page2():
    """Credly API page 2 response fixture."""
    return {
        "data": [
            {
                "id": "badge-003",
                "badge_template": {
                    "name": "Docker Expert",
                    "issuer": {"summary": "Docker Inc"},
                    "image_url": "https://img.credly.com/3",
                    "skills": [{"name": "Docker"}, {"name": "Containers"}],
                },
                "issued_at": "2024-03-10T10:00:00Z",
            }
        ],
        "metadata": {"next_page": None},
    }


@pytest.fixture
def sample_credly_external_badges():
    """Credly external badges API response fixture."""
    return {
        "data": [
            {
                "id": "ext-001",
                "external_badge": {
                    "badge_name": "External Cert",
                    "issuer_name": "External Org",
                    "badge_url": "https://external.org/cert/001",
                    "issued_at_date": "2024-01-01",
                    "image_url": "https://img.external.com/1",
                    "skills": ["External Skill"],
                    "credly_record_id": "ext-001",
                }
            }
        ]
    }


@pytest.fixture
def sample_credly_merged():
    """Credly merged badges fixture (native + external)."""
    return [
        {
            "id": "badge-001",
            "title": "Python Developer",
            "name": "Python Developer",
            "issuer": "Python Institute",
            "issuer_name": "Python Institute",
            "issued_at": "2024-01-15",
            "issued_at_date": "2024-01-15",
            "date": "2024-01-15",
            "image_url": "https://img.credly.com/1",
            "verify_url": "https://www.credly.com/badges/badge-001/public_url",
            "url": "https://www.credly.com/badges/badge-001/public_url",
            "type": "Credly Verified Badge",
            "verification_type": "Credly Verified Badge",
            "skills": ["Python", "Development"],
            "retired": False,
        },
        {
            "id": "badge-002",
            "title": "AWS Certified",
            "name": "AWS Certified",
            "issuer": "Amazon Web Services",
            "issuer_name": "Amazon Web Services",
            "issued_at": "2024-02-20",
            "issued_at_date": "2024-02-20",
            "date": "2024-02-20",
            "image_url": "https://img.credly.com/2",
            "verify_url": "https://www.credly.com/badges/badge-002/public_url",
            "url": "https://www.credly.com/badges/badge-002/public_url",
            "type": "Credly Verified Badge",
            "verification_type": "Credly Verified Badge",
            "skills": ["AWS"],
            "retired": False,
        },
        {
            "id": "ext-001",
            "title": "External Cert",
            "name": "External Cert",
            "issuer": "External Org",
            "issuer_name": "External Org",
            "issued_at": "2024-01-01",
            "issued_at_date": "2024-01-01",
            "date": "2024-01-01",
            "image_url": "https://img.external.com/1",
            "verify_url": "https://external.org/cert/001",
            "url": "https://external.org/cert/001",
            "type": "Credly External Badge",
            "verification_type": "Credly External Badge",
            "skills": ["External Skill"],
            "retired": False,
        },
    ]


@pytest.fixture
def sample_linkedin_csv_tab():
    """LinkedIn certifications CSV (tab-delimited) fixture."""
    return "Name\tAuthority\tUrl\tLicense Number\tStarted On\tFinished On\nPython Certification\tPython Institute\thttps://example.com/1\tLIC-001\tJan 2024\tFeb 2024\nAWS Solutions Architect\tAmazon Web Services\thttps://example.com/2\tLIC-002\tMar 2024\tApr 2024\n"


@pytest.fixture
def sample_linkedin_csv_comma():
    """LinkedIn certifications CSV (comma-delimited) fixture."""
    return "Name,Authority,Url,License Number,Started On,Finished On\nPython Certification,Python Institute,https://example.com/1,LIC-001,Jan 2024,Feb 2024\nAWS Solutions Architect,Amazon Web Services,https://example.com/2,LIC-002,Mar 2024,Apr 2024\n"


@pytest.fixture
def sample_google_developer_rpc():
    """Google Developer RPC batchexecute response fixture."""
    return """
    0["gQeJTc",[[["110772055890077594470",[["/awards/pathways/cloud-architecture",1705312800000],["/awards/pathways/data-engineering",1705399200000]]]]]]
    1["RwSpuf",[[["110772055890077594470",[["/awards/badges/cloud-architect",1705485600000],["/awards/badges/data-engineer",1705572000000]]]]]]
    """


@pytest.fixture
def sample_google_developer_learnings():
    """Google Developer local learnings.txt (Serbian format) fixture."""
    return """Setup Basic OpenTelemetry Plugin in gRPC Python
check_circle_outline You have this badge!
17. август 2024.
Учење
Setup Basic OpenTelemetry Plugin in gRPC Java
check_circle_outline You have this badge!
17. август 2024.
Учење
Build Event-Driven Applications with Eventarc
check_circle_outline You have this badge!
13. август 2024.
Учење
Mastering Slash Commands of Antigravity 2.0: AI-Native Game Solver & Balance Tester ✨
check_circle_outline You have this badge!
13. august 2024.
Учење
Fraud Detection with BigQuery Graph 🔍
check_circle_outline You have this badge!
13. august 2024.
Учење
"""


@pytest.fixture
def sample_retired_rules():
    """Test retired credentials rules fixture."""
    return {
        "microsoft-learn": [
            {
                "id": "learn.retired-path",
                "match_type": "uid",
                "url": "https://learn.microsoft.com/en-us/training/paths/retired-path",
                "reason": "Content retired by Microsoft Learn",
                "retired_at": "2024-01-01",
            }
        ],
        "google-skills": [
            {
                "id": "https://skills.google/badges/retired",
                "match_type": "url",
                "url": "https://skills.google/badges/retired",
                "reason": "Badge retired by Google",
                "retired_at": "2024-02-01",
            }
        ],
        "aws-skills": [],
        "credly": [],
        "linkedin-certifications": [],
        "google-developer": [],
    }


@pytest.fixture
def sample_sanitize_data():
    """Test data for sanitize_ms_export.py with various secret patterns."""
    return {
        "scriptResult": "Initial Key : ABC123DEF456GHI789JKL==\nNew Key1 : xyz789+/==\nConnection String : DefaultEndpointsProtocol=https;AccountName=test;AccountKey=supersecretkey123456789==\n\"Key\" : \"mysecretkey123456789\"\n\"Connection String\" : \"AccountKey=anothersecretkey123456789==\"\nNormal text without secrets.\n-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQD...\n-----END PRIVATE KEY-----",
        "password": "should_be_redacted",
        "normal_field": "should_remain",
        "nested": {
            "secret": "nested_secret",
            "public": "nested_public",
        },
        "list_field": [
            {"access_token": "token123"},
            {"normal": "value"},
        ],
    }


# ==============================================================================
# FIXTURE FILE LOADERS
# ==============================================================================

def load_fixture(platform: str, filename: str) -> Any:
    """Load a fixture file from tests/fixtures/<platform>/<filename>."""
    fixture_path = Path(__file__).parent / "fixtures" / platform / filename
    if not fixture_path.exists():
        return None
    with open(fixture_path, "r", encoding="utf-8") as f:
        if filename.endswith(".json"):
            return json.load(f)
        return f.read()
    return None


@pytest.fixture
def microsoft_learn_export():
    """Load Microsoft Learn export fixture from file if exists."""
    return load_fixture("microsoft_learn", "export.json")


@pytest.fixture
def google_skills_profile():
    """Load Google Skills profile fixture from file if exists."""
    return load_fixture("google_skills", "profile.json")


@pytest.fixture
def aws_skills_transcript():
    """Load AWS Skills transcript fixture from file if exists."""
    return load_fixture("aws_skills", "transcript.csv")


@pytest.fixture
def credly_merged():
    """Load Credly merged fixture from file if exists."""
    return load_fixture("credly", "merged.json")


@pytest.fixture
def linkedin_certifications():
    """Load LinkedIn certifications fixture from file if exists."""
    return load_fixture("linkedin", "certifications.csv")


@pytest.fixture
def google_developer_rpc():
    """Load Google Developer RPC fixture from file if exists."""
    return load_fixture("google_developer", "rpc_response.txt")


# ==============================================================================
# MOCK HELPERS
# ==============================================================================

@pytest.fixture
def mock_archiver(monkeypatch):
    """Mock archiver module to avoid file I/O in tests."""
    mock_generate = MagicMock(return_value="test-platform-2024-06-part-01.md")
    mock_safe_write = MagicMock(return_value=True)
    monkeypatch.setattr("archiver.generate_platform_archive", mock_generate)
    monkeypatch.setattr("archiver.safe_write_file", mock_safe_write)
    monkeypatch.setattr("archiver.RAW_BASE_DEFAULT", "https://raw.githubusercontent.com/test/test/main/archives")
    return mock_generate, mock_safe_write


@pytest.fixture
def mock_loss_guard(monkeypatch):
    """Mock loss_guard module to avoid baseline file I/O."""
    mock_execute = MagicMock()
    mock_anomaly = type("PipelineDataLossAnomaly", (Exception,), {})
    monkeypatch.setattr("loss_guard.execute_content_loss_guard", mock_execute)
    monkeypatch.setattr("loss_guard.PipelineDataLossAnomaly", mock_anomaly)
    return mock_execute


@pytest.fixture
def mock_retired_rules(monkeypatch, sample_retired_rules):
    """Mock retired rules loading."""
    def mock_load(platform):
        return sample_retired_rules.get(platform, [])
    monkeypatch.setattr("update_ms_learn.load_retired_rules", mock_load)
    monkeypatch.setattr("update_google_skills.load_retired_rules", mock_load)
    monkeypatch.setattr("update_aws_skills.load_retired_rules", mock_load)
    monkeypatch.setattr("update_credly_badges.load_retired_rules", mock_load)
    monkeypatch.setattr("update_linkedin.load_retired_rules", mock_load)
    monkeypatch.setattr("update_google_developer.load_retired_rules", mock_load)
    return mock_load


# ==============================================================================
# TEST DATA BUILDERS
# ==============================================================================

def build_aws_badge(**overrides) -> dict:
    """Build a valid AWS badge dict for testing."""
    base = {
        "id": "aws-test-001",
        "title": "Test AWS Badge",
        "name": "Test AWS Badge",
        "issuer": "Amazon Web Services",
        "issuer_name": "Amazon Web Services",
        "issued_at": "2024-01-15",
        "issued_at_date": "2024-01-15",
        "date": "2024-01-15",
        "image_url": "https://img.com/test",
        "verify_url": "https://skillsprofile.skillbuilder.aws/user/test/badges/test",
        "url": "https://skillsprofile.skillbuilder.aws/user/test/badges/test",
        "type": "AWS Skill Builder Badge",
        "verification_type": "AWS Skill Builder Badge",
        "skills": ["AWS", "Test"],
        "retired": False,
    }
    base.update(overrides)
    return base


def build_google_badge(**overrides) -> dict:
    """Build a valid Google Skills badge dict for testing."""
    base = {
        "id": "google-test-001",
        "title": "Test Google Badge",
        "name": "Test Google Badge",
        "issuer": "Google Cloud",
        "issuer_name": "Google Cloud",
        "issued_at": "2024-01-15",
        "issued_at_date": "2024-01-15",
        "date": "2024-01-15",
        "image_url": "https://img.com/test",
        "verify_url": "https://skills.google/badges/test",
        "url": "https://skills.google/badges/test",
        "type": "Google Skill Badge",
        "verification_type": "Google Skill Badge",
        "skills": ["Google Cloud", "Test"],
        "retired": False,
    }
    base.update(overrides)
    return base


def build_ms_achievement(**overrides) -> dict:
    """Build a valid MS Learn achievement dict for testing."""
    base = {
        "id": "ACH-TEST-001",
        "title": "Test Achievement",
        "category": "module",
        "grantedOn": "2024-01-15",
        "url": "learn.test-achievement",
        "retired": False,
    }
    base.update(overrides)
    return base


def build_credly_badge(**overrides) -> dict:
    """Build a valid Credly badge dict for testing."""
    base = {
        "id": "credly-test-001",
        "title": "Test Credly Badge",
        "name": "Test Credly Badge",
        "issuer": "Test Issuer",
        "issuer_name": "Test Issuer",
        "issued_at": "2024-01-15",
        "issued_at_date": "2024-01-15",
        "date": "2024-01-15",
        "image_url": "https://img.credly.com/test",
        "verify_url": "https://www.credly.com/badges/test/public_url",
        "url": "https://www.credly.com/badges/test/public_url",
        "type": "Credly Verified Badge",
        "verification_type": "Credly Verified Badge",
        "skills": ["Test"],
        "retired": False,
    }
    base.update(overrides)
    return base


def build_linkedin_cert(**overrides) -> dict:
    """Build a valid LinkedIn certification dict for testing."""
    base = {
        "name": "Test Certification",
        "authority": "Test Authority",
        "issued": "2024-01",
        "url": "https://example.com/test",
        "license": "LIC-TEST-001",
        "original_order": 0,
        "retired": False,
    }
    base.update(overrides)
    return base


def build_gdev_badge(**overrides) -> dict:
    """Build a valid Google Developer badge dict for testing."""
    base = {
        "title": "Test GDev Badge",
        "date": "2024-01-15",
        "description": "Test Google Developer badge description",
        "source": "public_rpc",
        "retired": False,
    }
    base.update(overrides)
    return base


# Export builders as fixtures
@pytest.fixture
def aws_badge_builder():
    return build_aws_badge


@pytest.fixture
def google_badge_builder():
    return build_google_badge


@pytest.fixture
def ms_achievement_builder():
    return build_ms_achievement


@pytest.fixture
def credly_badge_builder():
    return build_credly_badge


@pytest.fixture
def linkedin_cert_builder():
    return build_linkedin_cert


@pytest.fixture
def gdev_badge_builder():
    return build_gdev_badge