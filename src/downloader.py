"""Image downloading functionality.

Speed wins ported from AIO-Webtoon-Downloader:
  * Classified retry (4 buckets: rate_limit / origin_error / retryable / permanent)
    so 429, CF 520-527, network blips, and 4xx are retried with the right policy.
  * Exponential backoff with jitter (was linear: 1s, 2s, 3s, 4s).
  * Per-host AIMD concurrency cap — bad hosts back off without crippling the run.
  * Async file writes via asyncio.to_thread — event loop is never blocked on disk.
  * Atomic .pending_<name> + os.replace — partial downloads never appear at the
    final path, so a crash mid-write leaves only .pending_* files.
  * Tuned TCPConnector (keepalive, ttl=30, enable_cleanup_closed).
"""

import asyncio
import os
from collections import defaultdict
from typing import List, Tuple

import aiohttp
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.database.manga_db import record_download_from_folders
from src.http import (
    DEFAULT_TIMEOUT,
    HEAD_TIMEOUT,
    build_session,
    classify_failure,
    compute_backoff,
    download_image_streaming,
    get_default_timeout,
    get_host_cap,
)
from src.utils import Colors, _loop_time, _cancel_pending_tasks

console = Console()

# Global state for interruption handling
stop_signal = False
CLEAN_OUTPUT = False
DEV_MODE = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def set_dev_mode(value: bool) -> None:
    """Set developer debug mode globally."""
    global DEV_MODE
    DEV_MODE = value


def set_stop_signal(value: bool) -> None:
    """Set the stop signal globally."""
    global stop_signal
    stop_signal = value


def _is_stopped() -> bool:
    return stop_signal


async def url_exists(session: aiohttp.ClientSession, url: str) -> bool:
    """Check if a URL exists with a HEAD request."""
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=HEAD_TIMEOUT,
        ) as response:
            return response.status == 200
    except Exception:
        return False


def _write_file_sync(filepath: str, data: bytes) -> None:
    """Synchronous write helper — runs in a worker thread via asyncio.to_thread."""
    with open(filepath, "wb") as f:
        f.write(data)


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

    os.makedirs(folder, exist_ok=True)
    filename = os.path.basename(url) or "image.bin"
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
    host = host_cap.host_of(url)
    headers = {"Referer": referer} if referer else None

    last_error = "unknown"
    for attempt in range(1, max_retries + 1):
        if stop_signal:
            return f"{Colors.RED}Download interrupted{Colors.RESET}"
        try:
            async with session.get(
                url, timeout=get_default_timeout(), headers=headers
            ) as r:
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
                    await asyncio.sleep(
                        compute_backoff("retryable", attempt, backoff_factor)
                    )
                    continue

                # Atomic write: pending tempfile -> os.replace to final path.
                # The disk I/O runs in a thread so the event loop stays free.
                await asyncio.to_thread(_write_file_sync, pending_path, content)
                await asyncio.to_thread(os.replace, pending_path, filepath)
                host_cap.record_success(url)
                return f"{Colors.GREEN}Saved as {filepath}{Colors.RESET}"

        except asyncio.TimeoutError as e:
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


# Backward-compat: some callers may import download_image_streaming from here.
__all__ = [
    "download_image",
    "download_image_streaming",
    "url_exists",
    "download_all_pages",
    "set_clean_output",
    "set_dev_mode",
    "set_stop_signal",
]


def _download_failed(result: str) -> bool:
    """Return whether a download result represents a failed page."""
    lowered = result.lower()
    return (
        "failed to download" in lowered
        or "unexpected error" in lowered
        or "download interrupted" in lowered
    )


def _get_trackable_chapter_folders(
    urls_to_download: List[Tuple[str, str]],
    page_results: dict[Tuple[str, str], str],
) -> list[str]:
    """Return the fully completed contiguous chapter folders from the queue start."""
    expected_pages: dict[str, int] = defaultdict(int)
    successful_pages: dict[str, int] = defaultdict(int)
    folder_order: list[str] = []

    for item in urls_to_download:
        _, folder = item
        if folder not in expected_pages:
            folder_order.append(folder)
        expected_pages[folder] += 1
        result = page_results.get(item)
        if result is not None and not _download_failed(result):
            successful_pages[folder] += 1

    completed_folders: list[str] = []
    for folder in folder_order:
        if successful_pages[folder] != expected_pages[folder]:
            break
        completed_folders.append(folder)
    return completed_folders


def _build_connector(max_workers: int) -> aiohttp.TCPConnector:
    """Construct a tuned TCPConnector sized for the requested worker count.

    - limit = max_workers * 2 (ceiling 64 to avoid socket exhaustion)
    - limit_per_host = max_workers (so one host can't starve others)
    - keepalive enabled, ttl=30s, cleanup_closed=True
    """
    limit = max(8, min(64, max_workers * 2))
    limit_per_host = max(1, min(limit, max_workers))
    return aiohttp.TCPConnector(
        limit=limit,
        limit_per_host=limit_per_host,
        force_close=False,
        enable_cleanup_closed=True,
    )


async def download_all_pages(
    urls_to_download: List[Tuple[str, str]],
    max_workers: int = 10,
    manga_name: str = "manga",
    track_to_db: bool = True,
    max_retries: int = 5,
    referer: str | None = None,
) -> None:
    """Download all pages with progress tracking.

    Set track_to_db=False when the caller will handle a single consolidated DB write.
    Set referer=... for sources with anti-hotlink protection (e.g. Webtoons).
    """
    total_pages = len(urls_to_download)
    if total_pages == 0:
        return

    # Sync makedirs is cheap and avoids an asyncio.to_thread call per folder.
    for _, folder in urls_to_download:
        os.makedirs(folder, exist_ok=True)

    # Tune the AIMD baseline to match the requested worker count so per-host
    # caps scale with the user's --workers setting.
    host_cap = get_host_cap()
    host_cap._baseline = max(
        1, max_workers
    )  # noqa: SLF001 — intentional internal access

    connector = _build_connector(max_workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(max(1, max_workers))
        page_results: dict[Tuple[str, str], str] = {}

        async def download_worker(args: Tuple[str, str]) -> Tuple[Tuple[str, str], str]:
            async with sem:
                url, folder = args
                return args, await download_image(
                    url,
                    folder,
                    session=session,
                    max_retries=max_retries,
                    referer=referer,
                )

        tasks = [
            asyncio.create_task(download_worker(item)) for item in urls_to_download
        ]

        if not CLEAN_OUTPUT:
            with Progress(
                SpinnerColumn(style="green"),
                TextColumn("[bold green]Downloading[/]"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                TextColumn("{task.fields[pages_per_sec]} pages/sec"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task(
                    "Downloading", total=total_pages, pages_per_sec="0.0"
                )

                start_time = _loop_time()
                completed = 0
                for future in asyncio.as_completed(tasks):
                    item, result = await future
                    page_results[item] = result
                    completed += 1
                    if stop_signal:
                        await _cancel_pending_tasks(tasks)
                        break
                    elapsed = max(_loop_time() - start_time, 0.001)
                    pps = completed / elapsed
                    progress.update(task, advance=1, pages_per_sec=f"{pps:.2f}")
                    if "Failed" in result or "HTTP" in result:
                        console.print(result)
        else:
            for future in asyncio.as_completed(tasks):
                item, result = await future
                page_results[item] = result
                if stop_signal:
                    await _cancel_pending_tasks(tasks)
                    break

    if track_to_db and not stop_signal and urls_to_download:
        try:
            chapter_folders = _get_trackable_chapter_folders(
                urls_to_download, page_results
            )
            if DEV_MODE and not CLEAN_OUTPUT:
                console.print(
                    f"[bold blue][db][/bold blue] Triggering save from downloader for '{manga_name}'"
                )
            if chapter_folders:
                # SQLite calls are synchronous — run them in a thread so the
                # event loop is not blocked during the DB write.
                await asyncio.to_thread(
                    record_download_from_folders,
                    manga_name=manga_name,
                    chapter_folders=chapter_folders,
                )
            elif DEV_MODE and not CLEAN_OUTPUT:
                console.print(
                    f"[bold blue][db][/bold blue] No fully completed contiguous chapters for '{manga_name}', skipping save"
                )
            if DEV_MODE and not CLEAN_OUTPUT:
                console.print(
                    f"[bold blue][db][/bold blue] Downloader save finished for '{manga_name}'"
                )
        except Exception:
            # DB tracking should not block downloads.
            if not CLEAN_OUTPUT:
                console.print(
                    f"{Colors.YELLOW}Warning: Could not write download metadata for {manga_name}{Colors.RESET}"
                )
    elif track_to_db and DEV_MODE and not stop_signal and not CLEAN_OUTPUT:
        console.print(
            f"[bold blue][db][/bold blue] Skipping save for '{manga_name}' because no pages were queued"
        )
