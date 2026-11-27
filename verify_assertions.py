"""Lightweight asynchronous HTTP assertion prober for credential_assertion URLs."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import urllib3
from urllib3.exceptions import HTTPError
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

JSONLD_PATH = "credentials.jsonld"
CACHE_PATH = "data/active_verifications.json"
DEFAULT_TTL_DAYS = 30
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_GLOBAL_CONCURRENCY = 10
DEFAULT_PER_DOMAIN_CONCURRENCY = 2
DEFAULT_MIN_DOMAIN_INTERVAL_SECONDS = 0.25
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; CredentialAssertionVerifier/1.0)"
_HEAD_FALLBACK_STATUSES = frozenset({400, 403, 405, 501})


def extract_assertion_urls(jsonld_payload: dict[str, Any]) -> list[str]:
    """Extract unique HTTP(S) assertion URLs where evidenceLevel=='issuer_credential'
    and verificationUrlKind=='credential_assertion'.
    """
    main_entity = jsonld_payload.get("mainEntity")
    if not isinstance(main_entity, dict):
        return []

    credentials = main_entity.get("hasCredential")
    if not isinstance(credentials, list):
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for cred in credentials:
        if not isinstance(cred, dict):
            continue
        if cred.get("evidenceLevel") != "issuer_credential":
            continue
        if cred.get("verificationUrlKind") != "credential_assertion":
            continue

        raw_url = cred.get("verifyUrl") or cred.get("url")
        if not isinstance(raw_url, str):
            continue
        url = raw_url.strip()
        if not url or url in seen:
            continue

        parsed = urlparse(url)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            seen.add(url)
            urls.append(url)

    return urls


def load_active_verifications(
    cache_path: str | Path = CACHE_PATH,
) -> dict[str, dict[str, Any]]:
    """Load persistent active verification cache mapping url -> status metadata."""
    path = Path(cache_path)
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to read verification cache {path}: {exc}")
        return {}

    if not isinstance(raw, dict):
        return {}

    return {
        str(k): v for k, v in raw.items() if isinstance(k, str) and isinstance(v, dict)
    }


def save_active_verifications(
    cache: dict[str, dict[str, Any]],
    cache_path: str | Path = CACHE_PATH,
) -> None:
    """Atomically persist active verification cache sorted by URL."""
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: cache[k] for k in sorted(cache)}
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(ordered, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _parse_iso_utc(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_cache_entry_fresh(
    entry: dict[str, Any] | None,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> bool:
    """Return True if cache entry has a valid last_verified_at newer than ttl_days."""
    if not isinstance(entry, dict) or ttl_days <= 0:
        return False

    verified_at = _parse_iso_utc(entry.get("last_verified_at"))
    if verified_at is None:
        return False

    current_time = now if now is not None else datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)

    age = current_time - verified_at
    return timedelta(minutes=-5) <= age < timedelta(days=ttl_days)


def is_verified_and_fresh(
    entry: dict[str, Any] | None,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> bool:
    """Return True if cache entry confirms alive==True within TTL."""
    if not isinstance(entry, dict) or entry.get("alive") is not True:
        return False
    return is_cache_entry_fresh(entry, ttl_days=ttl_days, now=now)


class DomainRateLimiter:
    """Per-domain concurrency and minimum-interval rate limiter for async probing."""

    def __init__(
        self,
        *,
        max_concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
        per_domain_concurrency: int = DEFAULT_PER_DOMAIN_CONCURRENCY,
        min_domain_interval: float = DEFAULT_MIN_DOMAIN_INTERVAL_SECONDS,
    ) -> None:
        self._global_sem = asyncio.Semaphore(max(1, max_concurrency))
        self._per_domain_concurrency = max(1, per_domain_concurrency)
        self._min_domain_interval = max(0.0, float(min_domain_interval))
        self._domain_sems: dict[str, asyncio.Semaphore] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._last_request_at: dict[str, float] = {}

    def _get_domain_controls(
        self, domain: str
    ) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        if domain not in self._domain_sems:
            self._domain_sems[domain] = asyncio.Semaphore(self._per_domain_concurrency)
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_sems[domain], self._domain_locks[domain]

    async def throttle(
        self, domain: str
    ) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
        """Acquire global + per-domain slots and enforce minimum domain spacing."""
        domain_sem, domain_lock = self._get_domain_controls(domain)
        await self._global_sem.acquire()
        try:
            await domain_sem.acquire()
        except Exception:
            self._global_sem.release()
            raise

        try:
            if self._min_domain_interval > 0:
                async with domain_lock:
                    now = time.monotonic()
                    last_at = self._last_request_at.get(domain)
                    if last_at is not None:
                        elapsed = now - last_at
                        if 0 <= elapsed < self._min_domain_interval:
                            await asyncio.to_thread(
                                time.sleep, self._min_domain_interval - elapsed
                            )
                    self._last_request_at[domain] = time.monotonic()
        except Exception:
            domain_sem.release()
            self._global_sem.release()
            raise

        return self._global_sem, domain_sem


def create_http_pool(max_pools: int = 32) -> urllib3.PoolManager:
    """Create a configured urllib3 PoolManager with bounded connection pools."""
    return urllib3.PoolManager(num_pools=max_pools, maxsize=DEFAULT_GLOBAL_CONCURRENCY)


def _close_response(resp: Any) -> None:
    """Safely release/close a urllib3 HTTPResponse."""
    release_fn = getattr(resp, "release_conn", None)
    if callable(release_fn):
        release_fn()
    close_fn = getattr(resp, "close", None)
    if callable(close_fn):
        close_fn()


def probe_single_url(
    http: urllib3.PoolManager,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Probe a single credential assertion URL via HEAD with GET fallback."""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    timeout_cfg = urllib3.Timeout(connect=min(timeout, 5.0), read=timeout)
    retries = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["HEAD", "GET"]),
        raise_on_status=False,
    )
    checked_at = (now if now is not None else datetime.now(UTC)).isoformat()

    status_code: int | None = None
    used_method = "HEAD"
    error_message: str | None = None

    try:
        head_resp = http.request(
            "HEAD",
            url,
            headers=headers,
            timeout=timeout_cfg,
            retries=retries,
            redirect=True,
        )
        try:
            status_code = int(head_resp.status)
        finally:
            _close_response(head_resp)

        if status_code in _HEAD_FALLBACK_STATUSES:
            used_method = "GET"
            get_resp = http.request(
                "GET",
                url,
                headers=headers,
                timeout=timeout_cfg,
                retries=retries,
                redirect=True,
                preload_content=False,
            )
            try:
                status_code = int(get_resp.status)
            finally:
                _close_response(get_resp)
    except (HTTPError, OSError, ValueError) as exc:
        error_message = str(exc)

    alive = status_code is not None and 200 <= status_code < 300
    result: dict[str, Any] = {
        "last_verified_at": checked_at,
        "http_status": status_code,
        "alive": alive,
        "method": used_method,
    }
    if error_message:
        result["error"] = error_message
    return result


async def verify_urls_async(
    urls: list[str],
    cache: dict[str, dict[str, Any]],
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    force: bool = False,
    retry_failed: bool = False,
    limit: int | None = None,
    concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
    per_domain_concurrency: int = DEFAULT_PER_DOMAIN_CONCURRENCY,
    min_domain_interval: float = DEFAULT_MIN_DOMAIN_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    http: urllib3.PoolManager | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Asynchronously probe stale/missing assertion URLs with per-domain throttling."""
    updated_cache = dict(cache)
    now = datetime.now(UTC)

    stale_urls: list[str] = []
    skipped_fresh = 0
    for url in urls:
        entry = updated_cache.get(url)
        fresh = is_cache_entry_fresh(entry, ttl_days=ttl_days, now=now)
        should_skip = (
            not force
            and fresh
            and not (retry_failed and entry is not None and entry.get("alive") is False)
        )
        if should_skip:
            skipped_fresh += 1
        else:
            stale_urls.append(url)

    if limit is not None and limit >= 0:
        stale_urls = stale_urls[:limit]

    limiter = DomainRateLimiter(
        max_concurrency=concurrency,
        per_domain_concurrency=per_domain_concurrency,
        min_domain_interval=min_domain_interval,
    )
    own_pool = http is None
    pool = http if http is not None else create_http_pool()

    async def _probe_with_limit(target_url: str) -> tuple[str, dict[str, Any]]:
        domain = urlparse(target_url).netloc.lower()
        global_sem, domain_sem = await limiter.throttle(domain)
        try:
            res = await asyncio.to_thread(
                probe_single_url, pool, target_url, timeout=timeout
            )
            return target_url, res
        finally:
            domain_sem.release()
            global_sem.release()

    probed_alive = 0
    probed_failed = 0
    try:
        if stale_urls:
            results = await asyncio.gather(*(_probe_with_limit(u) for u in stale_urls))
            for target_url, result in results:
                updated_cache[target_url] = result
                if result.get("alive") is True:
                    probed_alive += 1
                else:
                    probed_failed += 1
    finally:
        if own_pool:
            pool.clear()

    stats = {
        "total_candidates": len(urls),
        "skipped_fresh": skipped_fresh,
        "probed": len(stale_urls),
        "alive": probed_alive,
        "failed": probed_failed,
    }
    return updated_cache, stats


def run_verification(
    *,
    jsonld_path: str | Path = JSONLD_PATH,
    cache_path: str | Path = CACHE_PATH,
    ttl_days: int = DEFAULT_TTL_DAYS,
    force: bool = False,
    retry_failed: bool = False,
    limit: int | None = None,
    concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
    per_domain_concurrency: int = DEFAULT_PER_DOMAIN_CONCURRENCY,
    min_domain_interval: float = DEFAULT_MIN_DOMAIN_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Load JSON-LD assertion URLs, probe stale entries, and persist cache."""
    jsonld_file = Path(jsonld_path)
    if not jsonld_file.exists():
        logger.error(f"JSON-LD file not found: {jsonld_file}")
        sys.exit(1)

    payload = json.loads(jsonld_file.read_text(encoding="utf-8"))
    urls = extract_assertion_urls(payload)
    cache = load_active_verifications(cache_path)

    updated_cache, stats = asyncio.run(
        verify_urls_async(
            urls,
            cache,
            ttl_days=ttl_days,
            force=force,
            retry_failed=retry_failed,
            limit=limit,
            concurrency=concurrency,
            per_domain_concurrency=per_domain_concurrency,
            min_domain_interval=min_domain_interval,
            timeout=timeout,
        )
    )

    if not dry_run:
        save_active_verifications(updated_cache, cache_path)

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Lightweight HTTP assertion prober for credential_assertion URLs."
    )
    parser.add_argument(
        "--jsonld", default=JSONLD_PATH, help="Path to credentials.jsonld"
    )
    parser.add_argument(
        "--cache",
        default=CACHE_PATH,
        help="Path to persistent active_verifications.json cache",
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=DEFAULT_TTL_DAYS,
        help="Re-check links older than this many days (default: 30)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_GLOBAL_CONCURRENCY,
        help="Max concurrent requests globally (default: 10)",
    )
    parser.add_argument(
        "--per-domain-concurrency",
        type=int,
        default=DEFAULT_PER_DOMAIN_CONCURRENCY,
        help="Max concurrent requests per domain (default: 2)",
    )
    parser.add_argument(
        "--min-domain-interval",
        type=float,
        default=DEFAULT_MIN_DOMAIN_INTERVAL_SECONDS,
        help="Minimum seconds between request starts per domain (default: 0.25)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP read timeout in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on URLs to probe in a single run",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-probe cached entries marked alive=false even within TTL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache TTL and re-probe all assertion URLs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run probes without writing cache file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    stats = run_verification(
        jsonld_path=args.jsonld,
        cache_path=args.cache,
        ttl_days=args.ttl_days,
        force=args.force,
        retry_failed=args.retry_failed,
        limit=args.limit,
        concurrency=args.concurrency,
        per_domain_concurrency=args.per_domain_concurrency,
        min_domain_interval=args.min_domain_interval,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    print(
        f"Assertion verification complete: candidates={stats['total_candidates']}, "
        f"skipped_fresh={stats['skipped_fresh']}, probed={stats['probed']}, "
        f"alive={stats['alive']}, failed={stats['failed']}"
    )


if __name__ == "__main__":
    main()
