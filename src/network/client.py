"""Shared aiohttp session configuration."""

from __future__ import annotations

import aiohttp

from src.network.urls import PublicAddressResolver

DEFAULT_CONNECTOR_KWARGS = dict(
    limit=64,  # total in-flight connections across all hosts
    limit_per_host=32,  # per-host ceiling (will be further capped by AIMD)
    keepalive_timeout=30,  # idle connection TTL in seconds (keepalive)
    force_close=False,  # keep connections alive (HTTP keep-alive)
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
    kwargs["resolver"] = PublicAddressResolver(kwargs.get("resolver"))
    connector = aiohttp.TCPConnector(**kwargs)
    return aiohttp.ClientSession(
        connector=connector,
        timeout=timeout or DEFAULT_TIMEOUT,
        headers=headers or {"User-Agent": "mdl/3.5 (+https://github.com/Nycthera/mdl)"},
    )
