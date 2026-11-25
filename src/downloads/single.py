"""Single image URL checks and retrying downloads."""

from __future__ import annotations

import asyncio
import os

import aiohttp

from src.network.client import HEAD_TIMEOUT, get_default_timeout
from src.network.downloads import _write_file_sync
from src.network.retry import classify_failure, compute_backoff, get_host_cap
from src.network.urls import redirect_target, validate_http_url
from src.utils import Colors, image_filename

stop_signal = False


def set_stop_signal(value: bool) -> None:
    global stop_signal
    stop_signal = value


async def url_exists(session: aiohttp.ClientSession, url: str) -> bool:
    """Check if a URL exists with a HEAD request."""
    try:
        current_url = validate_http_url(url)
        for _ in range(10):
            async with session.head(
                current_url,
                allow_redirects=False,
                timeout=HEAD_TIMEOUT,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    current_url = redirect_target(current_url, response.headers.get("Location"))
                    continue
                return response.status == 200
    except (aiohttp.ClientError, TimeoutError, ValueError, OSError):
        return False
    return False


async def download_image(
    url: str,
    folder: str,
    session: aiohttp.ClientSession,
    max_retries: int = 5,
    backoff_factor: float = 1.0,
    referer: str | None = None,
) -> str:
    """Download a single image with classified retry + async writes + atomic rename.

    Interface preserved for backward compatibility: returns a human-readable
    status string (used by tests and by _download_failed()).
    """
    if stop_signal:
        return f"{Colors.RED}Download interrupted{Colors.RESET}"
    try:
        validate_http_url(url)
    except ValueError as exc:
        return f"{Colors.RED}Unsafe URL: {exc}{Colors.RESET}"

    os.makedirs(folder, exist_ok=True)
    filename = image_filename(url)
    filepath = os.path.join(folder, filename)

    if os.path.exists(filepath):
        return f"{Colors.YELLOW}Already downloaded: {filename}{Colors.RESET}"

    pending_path = os.path.join(folder, f".pending_{filename}")
    # Clean up any stale .pending from a previous interrupted run.
    if os.path.exists(pending_path):
        try:
            os.remove(pending_path)
        except OSError:
            pass

    host_cap = get_host_cap()
    headers = {"Referer": referer} if referer else None

    last_error = "unknown"
    for attempt in range(1, max_retries + 1):
        if stop_signal:
            return f"{Colors.RED}Download interrupted{Colors.RESET}"
        try:
            async with session.get(
                url,
                timeout=get_default_timeout(),
                headers=headers,
                allow_redirects=False,
            ) as r:
                if r.status in {301, 302, 303, 307, 308}:
                    return f"{Colors.RED}Unsafe redirect rejected for {filename}{Colors.RESET}"
                if r.status >= 400:
                    # Best-effort body sniff for Cloudflare classification.
                    body_snippet = b""
                    if r.status in (403, 503):
                        try:
                            body_snippet = await r.content.read(4096)
                        except Exception:
                            body_snippet = b""
                    cls = classify_failure(r.status, body_snippet=body_snippet)
                    host_cap.record_failure(url, cls)
                    last_error = f"HTTP {r.status}"
                    if cls == "permanent" or attempt == max_retries:
                        return (
                            f"{Colors.RED}Failed to download {filename} after "
                            f"{max_retries} attempts: HTTP {r.status}{Colors.RESET}"
                        )
                    await asyncio.sleep(compute_backoff(cls, attempt, backoff_factor))
                    continue

                # Buffer the response (typical manga page < 2 MB).
                content = await r.read()

                if not content:
                    host_cap.record_failure(url, "retryable")
                    last_error = "empty response"
                    if attempt == max_retries:
                        return (
                            f"{Colors.RED}Failed to download {filename} after "
                            f"{max_retries} attempts: empty response{Colors.RESET}"
                        )
                    await asyncio.sleep(compute_backoff("retryable", attempt, backoff_factor))
                    continue

                # Atomic write: pending tempfile -> os.replace to final path.
                # The disk I/O runs in a thread so the event loop stays free.
                await asyncio.to_thread(_write_file_sync, pending_path, content)
                await asyncio.to_thread(os.replace, pending_path, filepath)
                host_cap.record_success(url)
                return f"{Colors.GREEN}Saved as {filepath}{Colors.RESET}"

        except TimeoutError as e:
            host_cap.record_failure(url, "retryable")
            last_error = f"timeout: {e}"
            if attempt == max_retries:
                return (
                    f"{Colors.RED}Failed to download {filename} after "
                    f"{max_retries} attempts: {e}{Colors.RESET}"
                )
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_factor))
        except aiohttp.ClientError as e:
            cls = classify_failure(None, exc=e)
            host_cap.record_failure(url, cls)
            last_error = str(e)
            if cls == "permanent" or attempt == max_retries:
                return (
                    f"{Colors.RED}Failed to download {filename} after "
                    f"{max_retries} attempts: {e}{Colors.RESET}"
                )
            await asyncio.sleep(compute_backoff(cls, attempt, backoff_factor))
        except Exception as e:
            last_error = f"unexpected: {e}"
            if attempt == max_retries:
                return f"{Colors.RED}Unexpected error for {filename}: {e}{Colors.RESET}"
            await asyncio.sleep(compute_backoff("retryable", attempt, backoff_factor))

    return (
        f"{Colors.RED}Failed to download {filename} after "
        f"{max_retries} attempts: {last_error}{Colors.RESET}"
    )
