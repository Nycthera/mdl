"""Shared HTTP infrastructure — ports the best speed wins from AIO-Webtoon-Downloader.

This module provides:
  * `build_session()`            — aiohttp.ClientSession with a tuned TCPConnector
                                    (keepalive, ttl, force_close=False, cleanup_closed).
  * `classify_failure()`         — 4-bucket failure classifier
                                    (rate_limit / origin_error / retryable / permanent)
                                    so 429, CF 520-527, network blips, and 4xx are
                                    retried with the right policy instead of one
                                    blanket backoff.
  * `compute_backoff()`          — bounded exponential backoff with jitter, per class.
  * `HostConcurrencyCap`         — per-host AIMD cap (multiplicative decrease on
                                    rate_limit, additive increase after N clean
                                    chapters) so one bad host can't pin the whole
                                    run to concurrency=1 forever.
  * `download_image_streaming()` — chunked download + asyncio.to_thread write so the
                                    event loop is never blocked on disk I/O, with
                                    atomic .pending tempfile + os.replace for crash
                                    safety.

Designed as a drop-in helper. Existing scrapers can adopt it incrementally.
"""

from __future__ import annotations

import asyncio
import os
import random
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import aiohttp

# ---------------------------------------------------------------------------
# 1. Tuned session builder
# ---------------------------------------------------------------------------

# Conservative defaults — host-aware callers can pass overrides.
DEFAULT_CONNECTOR_KWARGS = dict(
    limit=64,  # total in-flight connections across all hosts
    limit_per_host=32,  # per-host ceiling (will be further capped by AIMD)
    ttl=30,  # idle connection TTL in seconds (keepalive)
    force_close=False,  # keep connections alive (HTTP keep-alive)
    enable_cleanup_closed=True,  # close SSL sockets cleanly (avoid ResourceWarning)
)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_connect=10, sock_read=20)
HEAD_TIMEOUT = aiohttp.ClientTimeout(total=5, connect=5, sock_read=5)


def get_default_timeout() -> aiohttp.ClientTimeout:
    """Return the current DEFAULT_TIMEOUT.

    Always look up via this getter (or `http.DEFAULT_TIMEOUT` attribute access)
    instead of `from src.http import DEFAULT_TIMEOUT` — the latter captures the
    reference at import time and won't see updates from set_default_timeout().
    """
    return DEFAULT_TIMEOUT


def set_default_timeout(total_seconds: float) -> None:
    """Override the module-level DEFAULT_TIMEOUT at runtime.

    Called from main.py based on the --timeout CLI flag. Affects all subsequent
    GETs made via download_image_streaming() / make_request() / the patched
    MangaDex scraper. HEAD probes keep their own short timeout.
    """
    global DEFAULT_TIMEOUT
    total_seconds = max(5.0, float(total_seconds))
    # Scale connect/sock_read proportionally, with sane floors.
    connect = min(10.0, max(5.0, total_seconds * 0.33))
    sock_read = min(60.0, max(5.0, total_seconds * 0.66))
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(
        total=total_seconds,
        connect=connect,
        sock_connect=connect,
        sock_read=sock_read,
    )


def build_session(
    *,
    connector_kwargs: dict | None = None,
    timeout: aiohttp.ClientTimeout | None = None,
    headers: dict | None = None,
) -> aiohttp.ClientSession:
    """Construct an aiohttp.ClientSession with a tuned TCPConnector.

    Reusing ONE session across gather+download phases lets HTTP keep-alive
    amortize TLS handshakes — this alone is a 2-3x win on chapter batches
    that hit the same image host.
    """
    kwargs = {**DEFAULT_CONNECTOR_KWARGS, **(connector_kwargs or {})}
    # Cap limit_per_host to limit so we never deadlock on a single host.
    if kwargs["limit_per_host"] > kwargs["limit"]:
        kwargs["limit_per_host"] = kwargs["limit"]
    connector = aiohttp.TCPConnector(**kwargs)
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout or DEFAULT_TIMEOUT,
        headers=headers or {"User-Agent": "mdl/3.5 (+https://github.com/Nycthera/mdl)"},
    )


# ---------------------------------------------------------------------------
# 2. Failure classification (4 buckets, ported from AIO)
# ---------------------------------------------------------------------------

# Cloudflare origin errors — the upstream is sick, NOT a rate limit.
_CF_ORIGIN_STATUSES = {520, 521, 522, 523, 524, 525, 526, 527}

# Body keywords that indicate a Cloudflare challenge / rate-limit page
# (only inspected when status is 403/429/503 — never on 2xx).
_CF_BODY_KEYWORDS = (
    b"cf-error-code",
    b"cf_chl_opt",
    b"challenge-platform",
    b"checking your browser",
    b"error 1015",
    b"error 1010",
    b"just a moment",
)


def classify_failure(
    status: int | None,
    exc: BaseException | None = None,
    body_snippet: bytes = b"",
) -> str:
    """Classify an HTTP failure into one of four buckets.

    Returns one of:
      - "rate_limit"   — server is throttling us (429, 503+RL body). Back off hard.
      - "origin_error" — CF 520-527, upstream sickness. Quick fixed retry, no cooldown.
      - "retryable"    — 5xx (except origin_error), connection reset, timeout. Exp backoff.
      - "permanent"    — 4xx (except 429), DNS errors. Fail fast.
    """
    # Network-level errors first
    if status is None:
        if exc is not None:
            if isinstance(exc, asyncio.TimeoutError):
                return "retryable"
            if isinstance(
                exc, (aiohttp.ClientConnectorDNSError, aiohttp.ClientProxyConnectionError)
            ):
                return "permanent"
            if isinstance(exc, aiohttp.ClientError):
                return "retryable"
        return "retryable"

    # HTTP status available
    if status == 429:
        return "rate_limit"
    if status in _CF_ORIGIN_STATUSES:
        return "origin_error"
    if status == 503:
        # 503 is ambiguous — could be CF rate-limit or real origin down.
        if any(kw in body_snippet for kw in _CF_BODY_KEYWORDS):
            return "rate_limit"
        return "origin_error"
    if status == 403:
        # 403 with a CF challenge body is effectively a rate-limit; without it, permanent.
        if any(kw in body_snippet for kw in _CF_BODY_KEYWORDS):
            return "rate_limit"
        return "permanent"
    if 500 <= status < 600:
        return "retryable"
    if 400 <= status < 500:
        return "permanent"
    return "retryable"


# ---------------------------------------------------------------------------
# 3. Backoff computation (bounded exponential + jitter, per class)
# ---------------------------------------------------------------------------


def compute_backoff(cls: str, attempt: int, base: float = 1.0) -> float:
    """Return sleep seconds for a given failure class and attempt number (1-indexed).

    Per-class policy:
      - rate_limit:   max(3, min(12, base * (attempt+1))) × jitter(0.85, 1.15)
      - origin_error: 1.5 × jitter(0.85, 1.15)   (quick fixed retry)
      - retryable:    min(8, base * 2**attempt) × jitter(0.6, 1.4)
      - permanent:    0  (never retry)
    """
    if cls == "permanent":
        return 0.0
    if cls == "rate_limit":
        return max(3.0, min(12.0, base * (attempt + 1))) * random.uniform(0.85, 1.15)
    if cls == "origin_error":
        return 1.5 * random.uniform(0.85, 1.15)
    # retryable
    return min(8.0, base * (2 ** max(0, attempt - 1))) * random.uniform(0.6, 1.4)


# ---------------------------------------------------------------------------
# 4. Per-host AIMD concurrency cap
# ---------------------------------------------------------------------------


class HostConcurrencyCap:
    """Per-host Additive-Increase / Multiplicative-Decrease concurrency cap.

    Ported (and simplified) from AIO-Webtoon-Downloader.

    Why: if a host starts rate-limiting us at concurrency=10, we want to drop
    to 5 fast. But if we then get 3 clean chapters in a row, we want to climb
    back toward the baseline so a single bad host doesn't permanently cripple
    throughput for the rest of the run.

    Thread-safe (uses an internal lock); safe to share across async tasks.
    """

    def __init__(
        self,
        baseline: int = 8,
        recovery_streak: int = 3,
        min_cap: int = 1,
    ):
        self._baseline = max(1, int(baseline))
        self._recovery_streak = max(1, int(recovery_streak))
        self._min_cap = max(1, int(min_cap))
        self._caps: dict[str, int] = {}
        self._streaks: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def host_of(url: str) -> str:
        try:
            return (urlparse(url).hostname or "").lower() or "unknown"
        except Exception:
            return "unknown"

    def effective(self, url: str, base: int | None = None) -> int:
        """Return min(base, cap[host]) if host is capped; else base."""
        host = self.host_of(url)
        b = self._baseline if base is None else max(1, int(base))
        with self._lock:
            cap = self._caps.get(host)
        return min(b, cap) if cap is not None else b

    def record_failure(self, url: str, cls: str) -> None:
        """Multiplicative decrease on rate_limit; -1 on retryable; no-op otherwise."""
        host = self.host_of(url)
        with self._lock:
            current = self._caps.get(host, self._baseline)
            if cls == "rate_limit":
                new_cap = max(self._min_cap, current // 2)
            elif cls == "retryable":
                new_cap = max(self._min_cap, current - 1)
            else:
                return  # origin_error / permanent: don't touch the cap
            self._caps[host] = new_cap
            self._streaks[host] = 0  # reset clean streak

    def record_success(self, url: str) -> None:
        """Additive increase after N consecutive clean chapters; delete cap when recovered."""
        host = self.host_of(url)
        with self._lock:
            if host not in self._caps:
                return  # not capped, nothing to do
            streak = self._streaks.get(host, 0) + 1
            if streak < self._recovery_streak:
                self._streaks[host] = streak
                return
            # Recovery threshold hit — bump cap by 1.
            current = self._caps[host]
            new_cap = current + 1
            if new_cap >= self._baseline:
                # Fully recovered — remove the cap entirely.
                self._caps.pop(host, None)
                self._streaks.pop(host, None)
            else:
                self._caps[host] = new_cap
                self._streaks[host] = 0  # reset streak after a bump


# Module-level singleton — shared across all download_image_streaming calls.
# Baseline matches the default `--workers` of 10; AIMD will dial down per-host
# as needed and climb back after 3 consecutive clean chapters.
_host_cap = HostConcurrencyCap(baseline=10, recovery_streak=3)


def get_host_cap() -> HostConcurrencyCap:
    """Return the process-wide HostConcurrencyCap singleton."""
    return _host_cap


# ---------------------------------------------------------------------------
# 5. Streaming download with async writes + atomic rename
# ---------------------------------------------------------------------------

# 128 KB chunks — same as AIO. Big enough to amortize Python overhead,
# small enough that early-abort on cancel happens within ~1 chunk.
CHUNK_SIZE = 128 * 1024


def _write_file_sync(filepath: str, data: bytes) -> None:
    """Synchronous write helper — runs in a worker thread via asyncio.to_thread."""
    with open(filepath, "wb") as f:
        f.write(data)


def _append_chunk_sync(fh, chunk: bytes) -> None:
    fh.write(chunk)


async def download_image_streaming(
    url: str,
    folder: str,
    session: aiohttp.ClientSession,
    *,
    max_retries: int = 5,
    backoff_base: float = 1.0,
    timeout: aiohttp.ClientTimeout | None = None,
    sem: asyncio.Semaphore | None = None,
    referer: str | None = None,
    stop_check: Callable[[], bool] | None = None,
    on_failure_class: Callable[[str, str], None] | None = None,
) -> tuple[bool, str]:
    """Download a single image with classified retry + streaming + async write.

    Returns (success, message).

    Speed wins over the previous download_image():
      * Streaming chunked read (128 KB) — no full-buffer memory spike on large images.
      * asyncio.to_thread() for the final write — event loop is never blocked on disk.
      * Atomic .pending_<name> + os.replace — partial downloads never appear at the
        final path, so a crash or Ctrl+C mid-write leaves only .pending_* files that
        the next run can safely ignore / clean up.
      * Classified retry — 429 backs off 3-12s, CF 520-527 retries quickly without
        cooldown, 4xx fails fast instead of wasting 5 retries.
      * Per-host AIMD cap — concurrent failures on one host dial down its semaphore
        without affecting other hosts.
    """
    if stop_check is not None and stop_check():
        return False, "interrupted"

    os.makedirs(folder, exist_ok=True)
    filename = os.path.basename(url) or "image.bin"
    filepath = os.path.join(folder, filename)
    if os.path.exists(filepath):
        return True, f"already-downloaded:{filename}"

    pending_path = os.path.join(folder, f".pending_{filename}")
    # Clean up any stale .pending from a previous interrupted run.
    if os.path.exists(pending_path):
        try:
            os.remove(pending_path)
        except OSError:
            pass

    headers = {}
    if referer:
        headers["Referer"] = referer

    host = _host_cap.host_of(url)
    last_cls = "retryable"

    for attempt in range(1, max_retries + 1):
        if stop_check is not None and stop_check():
            return False, "interrupted"
        try:
            async with session.get(
                url,
                timeout=timeout or DEFAULT_TIMEOUT,
                headers=headers or None,
            ) as r:
                if r.status >= 400:
                    # Sniff body for CF classification (cap at 4 KB to bound cost).
                    body_snippet = await r.content.read(4096) if r.status in (403, 503) else b""
                    cls = classify_failure(r.status, body_snippet=body_snippet)
                    last_cls = cls
                    if on_failure_class:
                        on_failure_class(host, cls)
                    _host_cap.record_failure(url, cls)
                    if cls == "permanent" or attempt == max_retries:
                        return False, f"http-{r.status}:{filename}"
                    await asyncio.sleep(compute_backoff(cls, attempt, backoff_base))
                    continue

                # Stream into memory in chunks (typical manga page < 2 MB).
                chunks: list[bytes] = []
                total = 0
                async for chunk in r.content.iter_chunked(CHUNK_SIZE):
                    if stop_check is not None and stop_check():
                        return False, "interrupted"
                    chunks.append(chunk)
                    total += len(chunk)
                content = b"".join(chunks) if len(chunks) != 1 else chunks[0]

                if total == 0:
                    last_cls = "retryable"
                    if attempt == max_retries:
                        return False, f"empty-response:{filename}"
                    await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))
                    continue

                # Atomic write: pending tempfile -> os.replace to final path.
                # Runs the actual disk I/O in a thread so the event loop stays free.
                await asyncio.to_thread(_write_file_sync, pending_path, content)
                await asyncio.to_thread(os.replace, pending_path, filepath)
                _host_cap.record_success(url)
                return True, f"saved:{filepath}"

        except TimeoutError as e:
            last_cls = "retryable"
            _host_cap.record_failure(url, "retryable")
            if on_failure_class:
                on_failure_class(host, "retryable")
            if attempt == max_retries:
                return False, f"timeout:{filename}:{e}"
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))
        except aiohttp.ClientError as e:
            cls = classify_failure(None, exc=e)
            last_cls = cls
            _host_cap.record_failure(url, cls)
            if on_failure_class:
                on_failure_class(host, cls)
            if cls == "permanent" or attempt == max_retries:
                return False, f"client-error:{filename}:{e}"
            await asyncio.sleep(compute_backoff(cls, attempt, backoff_base))
        except Exception as e:
            last_cls = "retryable"
            if attempt == max_retries:
                return False, f"unexpected:{filename}:{e}"
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))

    return False, f"exhausted:{filename}:{last_cls}"


# ---------------------------------------------------------------------------
# 6. Generic classified retry helper for non-image GETs (API calls etc.)
# ---------------------------------------------------------------------------


async def make_request(
    session: aiohttp.ClientSession,
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 5,
    backoff_base: float = 1.0,
    timeout: aiohttp.ClientTimeout | None = None,
    expect_json: bool = True,
) -> tuple[Any | None, int | None]:
    """Make an HTTP request with classified retry. Returns (data, status).

    If `expect_json` is True and the response is OK, returns parsed JSON.
    Otherwise returns the raw response body (bytes).

    On terminal failure, returns (None, last_status_seen).
    """
    last_status: int | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with session.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=timeout or DEFAULT_TIMEOUT,
            ) as r:
                last_status = r.status
                if r.status >= 400:
                    body_snippet = await r.content.read(4096) if r.status in (403, 503) else b""
                    cls = classify_failure(r.status, body_snippet=body_snippet)
                    _host_cap.record_failure(url, cls)
                    if cls == "permanent" or attempt == max_retries:
                        return None, r.status
                    await asyncio.sleep(compute_backoff(cls, attempt, backoff_base))
                    continue
                # Success
                if expect_json:
                    return await r.json(), r.status
                return await r.read(), r.status
        except TimeoutError:
            _host_cap.record_failure(url, "retryable")
            if attempt == max_retries:
                return None, last_status
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))
        except aiohttp.ClientError:
            _host_cap.record_failure(url, "retryable")
            if attempt == max_retries:
                return None, last_status
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))
        except Exception:
            if attempt == max_retries:
                return None, last_status
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_base))

    return None, last_status
