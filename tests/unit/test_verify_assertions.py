"""Unit and integration tests for lightweight HTTP assertion prober and JSON-LD integration."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from urllib3.exceptions import MaxRetryError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from generate_jsonld import parse_archive_monoliths
from verify_assertions import (
    extract_assertion_urls,
    is_cache_entry_fresh,
    is_verified_and_fresh,
    load_active_verifications,
    main,
    probe_single_url,
    run_verification,
    save_active_verifications,
    verify_urls_async,
)


class TestExtractAssertionUrls:
    """Tests for filtering credential_assertion URLs from credentials.jsonld."""

    def test_filters_only_issuer_credential_assertions(self):
        payload = {
            "mainEntity": {
                "hasCredential": [
                    {
                        "evidenceLevel": "issuer_credential",
                        "verificationUrlKind": "credential_assertion",
                        "verifyUrl": "https://www.credly.com/badges/1/public_url",
                        "url": "https://www.credly.com/badges/1/public_url",
                    },
                    {
                        "evidenceLevel": "issuer_credential",
                        "verificationUrlKind": "credential_assertion",
                        "verifyUrl": None,
                        "url": "https://badger.learning.sap.com/verify/abc",
                    },
                    {
                        "evidenceLevel": "issuer_credential",
                        "verificationUrlKind": "credential_assertion",
                        "verifyUrl": "https://www.credly.com/badges/1/public_url",
                    },
                    {
                        "evidenceLevel": "issuer_profile",
                        "verificationUrlKind": "profile_page",
                        "url": "https://skillsprofile.skillbuilder.aws/user/test",
                    },
                    {
                        "evidenceLevel": "platform_activity",
                        "verificationUrlKind": "catalog_page",
                        "url": "https://learn.microsoft.com/en-us/training/modules/m1",
                    },
                    {
                        "evidenceLevel": "issuer_credential",
                        "verificationUrlKind": "credential_assertion",
                        "verifyUrl": "ftp://invalid.example.com/1",
                    },
                ]
            }
        }
        urls = extract_assertion_urls(payload)
        assert urls == [
            "https://www.credly.com/badges/1/public_url",
            "https://badger.learning.sap.com/verify/abc",
        ]

    def test_extract_handles_malformed_payload(self):
        assert extract_assertion_urls({}) == []
        assert extract_assertion_urls({"mainEntity": None}) == []
        assert extract_assertion_urls({"mainEntity": {"hasCredential": "bad"}}) == []


class TestCacheFreshnessAndPersistence:
    """Tests for TTL freshness checks and atomic cache serialization."""

    def test_ttl_fresh_and_stale_boundaries(self):
        now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
        fresh_entry = {
            "last_verified_at": (now - timedelta(days=29, hours=23)).isoformat(),
            "http_status": 200,
            "alive": True,
        }
        stale_entry = {
            "last_verified_at": (now - timedelta(days=30)).isoformat(),
            "http_status": 200,
            "alive": True,
        }
        dead_entry = {
            "last_verified_at": (now - timedelta(days=1)).isoformat(),
            "http_status": 404,
            "alive": False,
        }

        assert is_cache_entry_fresh(fresh_entry, ttl_days=30, now=now) is True
        assert is_verified_and_fresh(fresh_entry, ttl_days=30, now=now) is True

        assert is_cache_entry_fresh(stale_entry, ttl_days=30, now=now) is False
        assert is_verified_and_fresh(stale_entry, ttl_days=30, now=now) is False

        assert is_cache_entry_fresh(dead_entry, ttl_days=30, now=now) is True
        assert is_verified_and_fresh(dead_entry, ttl_days=30, now=now) is False

    def test_z_suffix_and_invalid_timestamp(self):
        now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
        z_entry = {
            "last_verified_at": "2026-11-26T12:00:00Z",
            "alive": True,
        }
        assert is_verified_and_fresh(z_entry, ttl_days=30, now=now) is True
        assert (
            is_cache_entry_fresh({"last_verified_at": "not-a-date"}, now=now) is False
        )
        assert is_cache_entry_fresh(None, now=now) is False

    def test_save_and_load_cache_roundtrip(self, temp_dir):
        cache_path = temp_dir / "data" / "active_verifications.json"
        cache_data = {
            "https://b.example.com/2": {
                "last_verified_at": "2026-11-27T00:00:00+00:00",
                "http_status": 200,
                "alive": True,
            },
            "https://a.example.com/1": {
                "last_verified_at": "2026-11-27T00:00:00+00:00",
                "http_status": 404,
                "alive": False,
            },
        }
        save_active_verifications(cache_data, cache_path)
        loaded = load_active_verifications(cache_path)
        assert list(loaded.keys()) == [
            "https://a.example.com/1",
            "https://b.example.com/2",
        ]
        assert loaded["https://b.example.com/2"]["alive"] is True

    def test_load_cache_handles_missing_or_corrupt(self, temp_dir):
        missing = temp_dir / "missing.json"
        assert load_active_verifications(missing) == {}

        corrupt = temp_dir / "corrupt.json"
        corrupt.write_text("{bad json", encoding="utf-8")
        assert load_active_verifications(corrupt) == {}


class TestHttpProbing:
    """Tests for probe_single_url, fallback logic, and rate-limited async probing."""

    def test_head_success(self):
        mock_pool = MagicMock()
        mock_resp = MagicMock(status=200)
        mock_pool.request.return_value = mock_resp

        now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
        res = probe_single_url(
            mock_pool, "https://www.credly.com/badges/1/public_url", now=now
        )

        assert res["alive"] is True
        assert res["http_status"] == 200
        assert res["method"] == "HEAD"
        assert res["last_verified_at"] == "2026-11-27T10:00:00+00:00"
        mock_pool.request.assert_called_once()
        mock_resp.release_conn.assert_called_once()

    def test_head_405_falls_back_to_get_200(self):
        mock_pool = MagicMock()
        head_resp = MagicMock(status=405)
        get_resp = MagicMock(status=200)
        mock_pool.request.side_effect = [head_resp, get_resp]

        res = probe_single_url(mock_pool, "https://badger.learning.sap.com/verify/xyz")

        assert res["alive"] is True
        assert res["http_status"] == 200
        assert res["method"] == "GET"
        assert mock_pool.request.call_count == 2
        assert mock_pool.request.call_args_list[0].args[0] == "HEAD"
        assert mock_pool.request.call_args_list[1].args[0] == "GET"
        assert mock_pool.request.call_args_list[1].kwargs["preload_content"] is False
        head_resp.release_conn.assert_called_once()
        get_resp.release_conn.assert_called_once()

    def test_head_404_does_not_fallback_and_marks_dead(self):
        mock_pool = MagicMock()
        head_resp = MagicMock(status=404)
        mock_pool.request.return_value = head_resp

        res = probe_single_url(mock_pool, "https://verify.skilljar.com/c/missing")

        assert res["alive"] is False
        assert res["http_status"] == 404
        assert res["method"] == "HEAD"
        mock_pool.request.assert_called_once()

    def test_network_error_records_failure(self):
        mock_pool = MagicMock()
        mock_pool.request.side_effect = MaxRetryError(None, "https://example.com")

        res = probe_single_url(mock_pool, "https://credential.net/123")

        assert res["alive"] is False
        assert res["http_status"] is None
        assert "error" in res

    def test_verify_urls_async_skips_fresh_and_throttles(self):
        fresh_ts = datetime.now(UTC).isoformat()
        stale_ts = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        urls = [
            "https://www.credly.com/badges/fresh/public_url",
            "https://www.credly.com/badges/stale/public_url",
            "https://badger.learning.sap.com/verify/new1",
            "https://badger.learning.sap.com/verify/new2",
        ]
        initial_cache = {
            urls[0]: {"last_verified_at": fresh_ts, "http_status": 200, "alive": True},
            urls[1]: {"last_verified_at": stale_ts, "http_status": 200, "alive": True},
        }

        def fake_probe(pool, target_url, **kwargs):
            return {
                "last_verified_at": datetime.now(UTC).isoformat(),
                "http_status": 200,
                "alive": True,
                "method": "HEAD",
            }

        with (
            patch("verify_assertions.probe_single_url", side_effect=fake_probe),
            patch("verify_assertions.time.sleep") as mock_sleep,
        ):
            updated, stats = asyncio.run(
                verify_urls_async(
                    urls,
                    initial_cache,
                    ttl_days=30,
                    per_domain_concurrency=1,
                    min_domain_interval=0.05,
                    http=MagicMock(),
                )
            )

        assert stats["total_candidates"] == 4
        assert stats["skipped_fresh"] == 1
        assert stats["probed"] == 3
        assert stats["alive"] == 3
        assert stats["failed"] == 0
        assert updated[urls[0]]["last_verified_at"] == fresh_ts
        mock_sleep.assert_called_once_with(0.05)

    def test_verify_urls_async_retry_failed_and_limit(self):
        fresh_ts = datetime.now(UTC).isoformat()
        urls = [
            "https://www.credly.com/badges/dead/public_url",
            "https://www.credly.com/badges/new1/public_url",
            "https://www.credly.com/badges/new2/public_url",
        ]
        initial_cache = {
            urls[0]: {"last_verified_at": fresh_ts, "http_status": 503, "alive": False}
        }

        def fake_probe(pool, target_url, **kwargs):
            return {
                "last_verified_at": fresh_ts,
                "http_status": 200,
                "alive": True,
                "method": "HEAD",
            }

        with patch("verify_assertions.probe_single_url", side_effect=fake_probe):
            updated, stats = asyncio.run(
                verify_urls_async(
                    urls,
                    initial_cache,
                    ttl_days=30,
                    retry_failed=True,
                    limit=2,
                    min_domain_interval=0.0,
                    http=MagicMock(),
                )
            )

        assert stats["probed"] == 2
        assert updated[urls[0]]["alive"] is True
        assert urls[2] not in updated


class TestCliAndJsonLdIntegration:
    """Tests for run_verification CLI and generate_jsonld.py cache integration."""

    def test_run_verification_and_cli_main(self, temp_dir):
        jsonld_file = temp_dir / "credentials.jsonld"
        cache_file = temp_dir / "data" / "active_verifications.json"
        jsonld_file.write_text(
            json.dumps(
                {
                    "mainEntity": {
                        "hasCredential": [
                            {
                                "evidenceLevel": "issuer_credential",
                                "verificationUrlKind": "credential_assertion",
                                "verifyUrl": "https://badger.learning.sap.com/verify/1",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        mock_pool = MagicMock()
        mock_pool.request.return_value = MagicMock(status=200)
        with patch("verify_assertions.create_http_pool", return_value=mock_pool):
            main(
                [
                    "--jsonld",
                    str(jsonld_file),
                    "--cache",
                    str(cache_file),
                    "--min-domain-interval",
                    "0",
                ]
            )

        saved = load_active_verifications(cache_file)
        assert "https://badger.learning.sap.com/verify/1" in saved
        assert saved["https://badger.learning.sap.com/verify/1"]["alive"] is True

    def test_run_verification_missing_jsonld_exits(self, temp_dir):
        with pytest.raises(SystemExit) as exc_info:
            run_verification(jsonld_path=temp_dir / "missing.jsonld")
        assert exc_info.value.code == 1

    def test_generate_jsonld_elevates_verified_assertions_and_respects_ttl_and_retired(
        self, temp_dir
    ):
        archives_dir = temp_dir / "archives"
        archives_dir.mkdir()
        cache_path = temp_dir / "active_verifications.json"

        now = datetime.now(UTC)
        fresh_ts = (now - timedelta(days=2)).isoformat()
        stale_ts = (now - timedelta(days=45)).isoformat()

        (archives_dir / "linkedin-certifications-complete.md").write_text(
            "# Complete LinkedIn Certifications Archive\n\n"
            "| Date Earned | Credential Name | Issuing Authority | Verification Link |\n"
            "| :---: | :--- | :--- | :--- |\n"
            "| 2026-01-10 | **Verified Ext** | SAP | [Verify](https://badger.learning.sap.com/verify/fresh-ok) |\n"
            "| 2026-01-11 | **Stale Ext** | SAP | [Verify](https://badger.learning.sap.com/verify/stale-old) |\n"
            "| 2026-01-12 | **Dead Ext** | Skilljar | [Verify](https://verify.skilljar.com/c/dead-404) |\n"
            "| 2025-01-01 | **Retired Ext** | Credly | [Verify](https://www.credly.com/badges/ret-1/public_url) [WARN] *Content retired* |\n",
            encoding="utf-8",
        )
        (archives_dir / "aws-skills-complete.md").write_text(
            "# Complete AWS Skill Builder Archive\n\n"
            "| Date Earned | Credential Name | Issuer | Verification Type |\n"
            "| :---: | :--- | :--- | :---: |\n"
            "| 2026-01-15 | [AWS Profile Item](https://skillsprofile.skillbuilder.aws/user/u1) | Amazon Web Services | Digital course |\n",
            encoding="utf-8",
        )

        save_active_verifications(
            {
                "https://badger.learning.sap.com/verify/fresh-ok": {
                    "last_verified_at": fresh_ts,
                    "http_status": 200,
                    "alive": True,
                },
                "https://badger.learning.sap.com/verify/stale-old": {
                    "last_verified_at": stale_ts,
                    "http_status": 200,
                    "alive": True,
                },
                "https://verify.skilljar.com/c/dead-404": {
                    "last_verified_at": fresh_ts,
                    "http_status": 404,
                    "alive": False,
                },
                "https://www.credly.com/badges/ret-1/public_url": {
                    "last_verified_at": fresh_ts,
                    "http_status": 200,
                    "alive": True,
                },
                "https://skillsprofile.skillbuilder.aws/user/u1": {
                    "last_verified_at": fresh_ts,
                    "http_status": 200,
                    "alive": True,
                },
            },
            cache_path,
        )

        with (
            patch("generate_jsonld.ARCHIVE_DIR", str(archives_dir)),
            patch("generate_jsonld.ACTIVE_VERIFICATIONS_PATH", str(cache_path)),
            patch("generate_jsonld.ACTIVE_VERIFICATION_TTL_DAYS", 30),
        ):
            creds = parse_archive_monoliths()

        by_name = {c["name"]: c for c in creds}

        assert by_name["Verified Ext"]["verificationStatus"] == "verified"
        assert by_name["Verified Ext"]["lastVerifiedAt"] == fresh_ts

        assert by_name["Stale Ext"]["verificationStatus"] == "unverified"
        assert by_name["Stale Ext"]["lastVerifiedAt"] is None

        assert by_name["Dead Ext"]["verificationStatus"] == "unverified"
        assert by_name["Dead Ext"]["lastVerifiedAt"] is None

        assert by_name["Retired Ext"]["verificationStatus"] == "retired"
        assert by_name["Retired Ext"]["lastVerifiedAt"] == fresh_ts

        assert by_name["AWS Profile Item"]["verificationStatus"] == "unverified"
        assert by_name["AWS Profile Item"]["lastVerifiedAt"] is None
