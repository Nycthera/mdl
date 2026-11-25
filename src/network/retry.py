"""HTTP failure classification, backoff, and per-host concurrency."""

from __future__ import annotations

import asyncio
import random
import threading
from urllib.parse import urlparse

import aiohttp

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
                exc,
                (aiohttp.ClientConnectorDNSError, aiohttp.ClientProxyConnectionError),
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

    def set_baseline(self, baseline: int) -> None:
        """Update the uncapped limit and clamp recovering hosts to it."""
        baseline = max(1, int(baseline))
        with self._lock:
            self._baseline = baseline
            for host, cap in list(self._caps.items()):
                if cap >= baseline:
                    self._caps.pop(host, None)
                    self._streaks.pop(host, None)

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


_host_cap = HostConcurrencyCap(baseline=10, recovery_streak=3)


def get_host_cap() -> HostConcurrencyCap:
    """Return the process-wide HostConcurrencyCap singleton."""
    return _host_cap
