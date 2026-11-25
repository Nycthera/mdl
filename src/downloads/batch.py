"""Concurrent download scheduling, progress, and durable run tracking."""

from __future__ import annotations

import asyncio
import os
import sqlite3

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

from src.database.history import begin_download_run
from src.database.library import record_download_from_folders
from src.downloads.single import download_image
from src.downloads.support import (
    AdaptiveHostLimiter,
    DownloadResult,
    _build_connector,
    _download_failed,
    _get_trackable_chapter_folders,
    _persist_run_history,
)
from src.network.retry import get_host_cap
from src.utils import Colors, _cancel_pending_tasks, _loop_time, image_filename

console = Console()
stop_signal = False
CLEAN_OUTPUT = False
DEV_MODE = False


async def download_all_pages(
    urls_to_download: list[tuple[str, str]],
    max_workers: int = 10,
    manga_name: str = "manga",
    track_to_db: bool = True,
    max_retries: int = 5,
    referer: str | None = None,
    session: aiohttp.ClientSession | None = None,
    source_type: str = "generic",
    source_url: str | None = None,
    source_id: str | None = None,
    language: str | None = None,
    output_path: str | None = None,
    track_history: bool | None = None,
    optimize_mode: str = "off",
    skip_archived: bool = False,
) -> DownloadResult:
    """Download all pages with progress tracking.

    Set track_to_db=False when the caller will handle a single consolidated DB write.
    Set referer=... for sources with anti-hotlink protection (e.g. Webtoons).
    Pass a session to reuse an existing connection pool across chapter batches.
    """
    if optimize_mode not in {"off", "lossless", "balanced", "small"}:
        raise ValueError(f"Unknown image optimization mode: {optimize_mode}")
    optimize_page = None
    if optimize_mode != "off":
        from src.image_optimizer import optimize_image

        optimize_page = optimize_image

    urls_to_download = list(dict.fromkeys(urls_to_download))
    total_pages = len(urls_to_download)
    if total_pages == 0:
        return DownloadResult(0, 0, [])

    if output_path is None:
        folders = [os.path.abspath(folder) for _, folder in urls_to_download]
        output_path = os.path.commonpath(folders)
        if len(set(folders)) == 1:
            output_path = os.path.dirname(output_path)

    archived_pages = {}
    if skip_archived:
        from src.cbz import index_cbz_pages

        archived_pages = await asyncio.to_thread(
            index_cbz_pages,
            output_path,
            folders={folder for _, folder in urls_to_download},
        )
    for url, folder in urls_to_download:
        if os.path.realpath(os.path.join(folder, image_filename(url))) not in archived_pages:
            os.makedirs(folder, exist_ok=True)

    # Tune the AIMD baseline to match the requested worker count and enforce
    # its changing per-host limits in the live scheduler.
    host_cap = get_host_cap()
    host_cap.set_baseline(max_workers)
    host_limiter = AdaptiveHostLimiter(max_workers)

    should_track_history = track_to_db if track_history is None else track_history
    run_id: int | None = None
    if should_track_history:
        try:
            run_id = await asyncio.to_thread(
                begin_download_run,
                manga_name,
                total_pages,
                source_type=source_type,
                source_url=source_url,
                source_id=source_id,
                language=language,
                output_path=output_path,
            )
        except (sqlite3.Error, OSError, ValueError):
            run_id = None

    owns_session = session is None
    if session is None:
        connector = _build_connector(max_workers)
        session = aiohttp.ClientSession(connector=connector)

    page_results: dict[tuple[str, str], str] = {}
    try:
        sem = asyncio.Semaphore(max(1, max_workers))
        optimize_sem = asyncio.Semaphore(max(1, min(4, os.cpu_count() or 1)))

        async def download_worker(args: tuple[str, str]) -> tuple[tuple[str, str], str]:
            url, folder = args
            if (
                not stop_signal
                and os.path.realpath(os.path.join(folder, image_filename(url))) in archived_pages
            ):
                return args, f"Already downloaded (CBZ): {image_filename(url)}"
            async with host_limiter.slot(url):
                async with sem:
                    result = await download_image(
                        url,
                        folder,
                        session=session,
                        max_retries=max_retries,
                        referer=referer,
                    )
            # Network slots are released before encoding; the next pages can
            # download while a bounded number of completed pages are optimized.
            if optimize_page is not None and "saved as" in result.lower():
                async with optimize_sem:
                    await asyncio.to_thread(
                        optimize_page,
                        os.path.join(folder, image_filename(url)),
                        optimize_mode,
                    )
            return args, result

        tasks = [asyncio.create_task(download_worker(item)) for item in urls_to_download]

        try:
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
                    task = progress.add_task("Downloading", total=total_pages, pages_per_sec="0.0")

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

        finally:
            await _cancel_pending_tasks(tasks)
    except asyncio.CancelledError:
        if run_id is not None:
            try:
                await asyncio.shield(
                    _persist_run_history(
                        run_id,
                        page_results,
                        total_pages,
                        interrupted=True,
                    )
                )
            except (sqlite3.Error, OSError):
                pass
        raise
    finally:
        if owns_session:
            await session.close()

    if track_to_db and not stop_signal and urls_to_download:
        try:
            chapter_folders = _get_trackable_chapter_folders(urls_to_download, page_results)
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
                    source_type=source_type,
                    source_url=source_url,
                    source_id=source_id,
                    language=language,
                    output_path=output_path,
                )
            elif DEV_MODE and not CLEAN_OUTPUT:
                console.print(
                    f"[bold blue][db][/bold blue] No fully completed contiguous chapters for '{manga_name}', skipping save"
                )
            if DEV_MODE and not CLEAN_OUTPUT:
                console.print(
                    f"[bold blue][db][/bold blue] Downloader save finished for '{manga_name}'"
                )
        except (sqlite3.Error, OSError, ValueError) as exc:
            # DB tracking should not block downloads.
            if not CLEAN_OUTPUT:
                console.print(
                    f"{Colors.YELLOW}Warning: Could not write download metadata for {manga_name}: {exc}{Colors.RESET}"
                )
    elif track_to_db and DEV_MODE and not stop_signal and not CLEAN_OUTPUT:
        console.print(
            f"[bold blue][db][/bold blue] Skipping save for '{manga_name}' because no pages were queued"
        )

    successful_pages = sum(not _download_failed(value) for value in page_results.values())
    if run_id is not None:
        try:
            await _persist_run_history(
                run_id,
                page_results,
                total_pages,
                interrupted=stop_signal,
            )
        except (sqlite3.Error, OSError):
            pass

    completed_folders = _get_trackable_chapter_folders(urls_to_download, page_results)
    return DownloadResult(successful_pages, total_pages, completed_folders)
