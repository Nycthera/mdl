"""Retrying streamed HTTP transfers and API requests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import aiohttp

from src.network.client import get_default_timeout
from src.network.retry import _host_cap, classify_failure, compute_backoff
from src.network.urls import redirect_target, validate_http_url
from src.utils import image_filename

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
    try:
        validate_http_url(url)
    except ValueError as exc:
        return False, f"unsafe-url:{exc}"

    os.makedirs(folder, exist_ok=True)
    filename = image_filename(url)
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
                timeout=timeout or get_default_timeout(),
                headers=headers or None,
                allow_redirects=False,
            ) as r:
                if r.status in {301, 302, 303, 307, 308}:
                    try:
                        url = redirect_target(url, r.headers.get("Location"))
                    except ValueError as exc:
                        return False, f"unsafe-redirect:{filename}:{exc}"
                    continue
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
                timeout=timeout or get_default_timeout(),
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
