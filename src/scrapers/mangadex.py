"""MangaDex API scraper for manga downloads."""

import asyncio
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

import aiohttp
from rich.console import Console

from src.cbz import create_cbz_for_all
from src.database.manga_db import record_download
from src.downloader import DownloadResult, download_all_pages
from src.http import (
    classify_failure,
    compute_backoff,
    get_default_timeout,
)
from src.output_formats import create_output_for_all
from src.rate_limiter import rate_limiter_athome
from src.utils import sanitize_folder_name

console = Console()

API_ENDPOINT = "https://api.mangadex.org"

# Global configuration
CLEAN_OUTPUT = False
stop_signal = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def set_stop_signal(value: bool) -> None:
    """Set the stop signal globally."""
    global stop_signal
    stop_signal = value


def extract_manga_uuid(url: str) -> str | None:
    """Extract MangaDex UUID from URL."""
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "title":
            candidate_id = parts[1]
            try:
                # Validate that the extracted ID is a proper UUID
                uuid.UUID(candidate_id)
                return candidate_id
            except ValueError:
                # Not a valid UUID; fall through to return None
                pass
    except ValueError:
        pass
    return None


async def fetch_all_chapters_md(
    manga_uuid: str,
    lang: str = "en",
    session: aiohttp.ClientSession | None = None,
    max_retries: int = 5,
) -> list[dict[str, Any]]:
    """Fetch all chapters for a manga from MangaDex.

    Uses the shared classified-retry policy: 429 backs off 3-12s with jitter,
    5xx uses exponential backoff, 4xx fails fast. Every GET has a real
    ClientTimeout (was previously unbounded — could hang forever).
    """
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await fetch_all_chapters_md(
                manga_uuid, lang=lang, session=session, max_retries=max_retries
            )

    chapters = []
    limit = 100
    offset = 0

    while True:
        await rate_limiter_athome.acquire("mangadex_api")
        params = {
            "manga": manga_uuid,
            "translatedLanguage[]": lang,
            "limit": limit,
            "offset": offset,
            "order[chapter]": "asc",
        }
        for attempt in range(1, max_retries + 1):
            try:
                async with session.get(
                    f"{API_ENDPOINT}/chapter",
                    params=params,
                    timeout=get_default_timeout(),
                ) as resp:
                    if resp.status == 429:
                        wait = compute_backoff("rate_limit", attempt)
                        console.print(
                            f"[yellow]Rate limited by MangaDex, sleeping {wait:.1f}s...[/]"
                        )
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        cls = classify_failure(resp.status)
                        if cls == "permanent" or attempt == max_retries:
                            raise RuntimeError(
                                f"Error fetching MangaDex chapters: HTTP {resp.status}"
                            )
                        await asyncio.sleep(compute_backoff(cls, attempt))
                        continue
                    data = await resp.json()
                    break
            except (TimeoutError, aiohttp.ClientError) as e:
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Network error fetching MangaDex chapters: {e}"
                    ) from e
                await asyncio.sleep(compute_backoff("retryable", attempt))
        else:
            raise RuntimeError("MangaDex chapter lookup exhausted its retries")

        batch = data.get("data", [])
        chapters.extend(batch)
        total = data.get("total", 0)
        if offset + limit >= total:
            break
        offset += limit
    return chapters


async def get_images_md(
    chapter_id: str,
    use_saver: bool = False,
    max_retries: int = 5,
    session: aiohttp.ClientSession | None = None,
) -> list[str]:
    """Fetch image URLs for a specific chapter.

    Uses classified retry + bounded exponential backoff with jitter.
    Adds a real ClientTimeout to the at-home server GET (was unbounded).
    """
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await get_images_md(
                chapter_id,
                use_saver=use_saver,
                max_retries=max_retries,
                session=session,
            )

    for attempt in range(1, max_retries + 1):
        await rate_limiter_athome.acquire("mangadex_athome")
        try:
            async with session.get(
                f"https://api.mangadex.org/at-home/server/{chapter_id}",
                timeout=get_default_timeout(),
            ) as resp:
                if resp.status == 429:
                    wait = compute_backoff("rate_limit", attempt)
                    console.print(f"[yellow]Rate limited. Waiting {wait:.1f}s...[/]")
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    cls = classify_failure(resp.status)
                    if cls == "permanent" or attempt == max_retries:
                        console.print(
                            f"[red]Error fetching chapter {chapter_id}: {resp.status}[/]"
                        )
                        return []
                    await asyncio.sleep(compute_backoff(cls, attempt))
                    continue
                data = await resp.json()
                chapter_data = data.get("chapter", {})
                base_url = data.get("baseUrl")
                hash_code = chapter_data.get("hash")
                pages = chapter_data.get("dataSaver" if use_saver else "data", [])
                if not base_url or not hash_code or not pages:
                    return []
                mode = "data-saver" if use_saver else "data"
                return [f"{base_url}/{mode}/{hash_code}/{page}" for page in pages]
        except (TimeoutError, aiohttp.ClientError) as e:
            if attempt == max_retries:
                console.print(
                    f"[red]Network error fetching chapter {chapter_id}: {e}[/]"
                )
                return []
            await asyncio.sleep(compute_backoff("retryable", attempt))
    return []


async def get_manga_name_from_md(
    manga_url: str,
    lang: str = "en",
    session: aiohttp.ClientSession | None = None,
    max_retries: int = 3,
) -> str:
    """Get manga title from MangaDex API."""
    from src.utils import extract_manga_name_from_url

    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        return extract_manga_name_from_url(manga_url)
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await get_manga_name_from_md(
                manga_url, lang=lang, session=session, max_retries=max_retries
            )
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(
                f"{API_ENDPOINT}/manga/{manga_uuid}",
                timeout=get_default_timeout(),
            ) as resp:
                if resp.status != 200:
                    cls = classify_failure(resp.status)
                    if cls == "permanent" or attempt == max_retries:
                        return extract_manga_name_from_url(manga_url)
                    await asyncio.sleep(compute_backoff(cls, attempt))
                    continue
                data = await resp.json()
                data_obj = data.get("data", {})
                attributes = data_obj.get("attributes", {})
                title_dict = attributes.get("title", {})
                return (
                    title_dict.get(lang)
                    or title_dict.get("en")
                    or next(iter(title_dict.values()), None)
                    or extract_manga_name_from_url(manga_url)
                )
        except (TimeoutError, aiohttp.ClientError):
            if attempt == max_retries:
                return extract_manga_name_from_url(manga_url)
            await asyncio.sleep(compute_backoff("retryable", attempt))
    return extract_manga_name_from_url(manga_url)


async def download_md_chapters(
    manga_url: str,
    lang: str = "en",
    use_saver: bool = False,
    create_cbz: bool = True,
    output_format: str = "cbz",
    max_workers: int = 10,
    max_retries: int = 5,
    start_chapter: int = 0,
    optimize_mode: str = "off",
    output_path: str | None = None,
    cbz_layout: str = "series",
    reading_direction: str = "auto",
    metadata_language: str | None = None,
) -> DownloadResult:
    """Download all chapters from a MangaDex manga.

    `max_workers` controls per-chapter image download concurrency. Was
    previously hardcoded to 10; now respects the CLI --workers flag.
    """
    # Extract UUID and clean manga title
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        raise ValueError("Could not extract manga UUID from URL")

    # Single shared session across all MangaDex API + at-home calls —
    # HTTP keep-alive amortizes TLS handshakes across the whole run.
    from src.downloader import _build_connector

    connector = _build_connector(max_workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        manga_name_clean = await get_manga_name_from_md(
            manga_url, lang=lang, session=session, max_retries=max_retries
        )
        manga_title = manga_name_clean
        manga_name_clean = sanitize_folder_name(manga_name_clean)

        # Root folder named after manga
        manga_root_folder = output_path or manga_name_clean
        os.makedirs(manga_root_folder, exist_ok=True)

        if not CLEAN_OUTPUT:
            console.print(
                f"[cyan]Downloading '{manga_name_clean}' in language '{lang}'[/]"
            )
        chapters = await fetch_all_chapters_md(
            manga_uuid, lang, session=session, max_retries=max_retries
        )
        if not CLEAN_OUTPUT:
            console.print(f"[green]Found {len(chapters)} chapters[/]")

        total_pages_downloaded = 0
        total_pages_expected = 0
        completed_folders = []
        chapter_metadata = {}
        total_chapters_downloaded = 0
        latest_chapter_local = 0.0
        latest_chapter_from_mangadex = 0.0

        all_complete = True
        selected_chapters: list[
            tuple[dict[str, Any], re.Match[str] | None, float | None]
        ] = []
        for chapter in chapters:
            attr = chapter.get("attributes", {})
            chapter_num = attr.get("chapter", "Unknown")
            chapter_match = re.search(r"(\d+(?:\.\d+)?)", str(chapter_num))
            chapter_val = None
            if chapter_match:
                chapter_val = float(chapter_match.group(1))
                latest_chapter_from_mangadex = max(
                    latest_chapter_from_mangadex, chapter_val
                )
            if chapter_match and chapter_val < start_chapter:
                continue
            selected_chapters.append((chapter, chapter_match, chapter_val))

        async def fetch_chapter_images(chapter: dict[str, Any]) -> list[str]:
            return await get_images_md(
                chapter.get("id"),
                use_saver=use_saver,
                session=session,
                max_retries=max_retries,
            )

        prefetch_task = (
            asyncio.create_task(fetch_chapter_images(selected_chapters[0][0]))
            if selected_chapters
            else None
        )
        try:
            for index, (chapter, chapter_match, chapter_val) in enumerate(
                selected_chapters
            ):
                if stop_signal:
                    all_complete = False
                    break
                attr = chapter.get("attributes", {})
                chapter_num = attr.get("chapter", "Unknown")
                chapter_title = attr.get("title", "")

                images = await prefetch_task
                prefetch_task = (
                    asyncio.create_task(
                        fetch_chapter_images(selected_chapters[index + 1][0])
                    )
                    if index + 1 < len(selected_chapters)
                    else None
                )

                if not images:
                    all_complete = False
                    if not CLEAN_OUTPUT:
                        console.print(
                            f"[yellow]Skipping Chapter {chapter_num} (no images)[/]"
                        )
                    continue

                # Subfolder per chapter
                chapter_folder_name = f"Chapter_{chapter_num}_{chapter_title}".strip(
                    "_"
                )
                chapter_folder_name = sanitize_folder_name(chapter_folder_name)
                chapter_folder = os.path.join(manga_root_folder, chapter_folder_name)
                chapter_metadata[chapter_folder_name] = {
                    "Title": chapter_title or f"Chapter {chapter_num}",
                    "Number": attr.get("chapter"),
                    "Web": f"https://mangadex.org/chapter/{chapter['id']}",
                }

                if not CLEAN_OUTPUT:
                    console.print(
                        f"[yellow]Downloading Chapter {chapter_num}: {chapter_title}[/]"
                    )

                urls_to_download = [(url, chapter_folder) for url in images]
                result = await download_all_pages(
                    urls_to_download,
                    max_workers=max_workers,
                    manga_name=manga_name_clean,
                    track_to_db=False,
                    max_retries=max_retries,
                    session=session,
                    source_type="mangadex",
                    source_url=manga_url,
                    source_id=manga_uuid,
                    language=lang,
                    output_path=manga_root_folder,
                    track_history=True,
                    optimize_mode=optimize_mode,
                    skip_archived=create_cbz and output_format == "cbz",
                )

                total_pages_downloaded += result.successful_pages
                total_pages_expected += result.total_pages
                total_chapters_downloaded += int(result.complete)
                all_complete = all_complete and result.complete
                if all_complete:
                    completed_folders.extend(result.completed_folders)
                if (
                    chapter_match
                    and chapter_val is not None
                    and all_complete
                    and not stop_signal
                ):
                    latest_chapter_local = max(latest_chapter_local, chapter_val)

                if os.path.isdir(chapter_folder) and not os.listdir(chapter_folder):
                    if not CLEAN_OUTPUT:
                        console.print(
                            f"[red]Removing empty folder {chapter_folder_name}[/]"
                        )
                    os.rmdir(chapter_folder)
        finally:
            if prefetch_task is not None and not prefetch_task.done():
                prefetch_task.cancel()
                await asyncio.gather(prefetch_task, return_exceptions=True)

        # Create CBZ from the manga root folder.
        # Archive file operations are synchronous — run them in a thread so
        # the event loop is not blocked during CBZ packaging.
        cbz_path = None
        if create_cbz and all_complete and not stop_signal:
            metadata = {
                "series": manga_title,
                "language": metadata_language or lang,
                "reading_direction": (
                    "rtl" if reading_direction == "auto" else reading_direction
                ),
                "source_url": manga_url,
                "chapter_metadata": chapter_metadata,
            }
            if output_format == "cbz" and cbz_layout == "series":
                cbz_path = await asyncio.to_thread(
                    create_cbz_for_all, manga_root_folder, **metadata
                )
            else:
                cbz_path = await asyncio.to_thread(
                    create_output_for_all,
                    manga_root_folder,
                    output_format,
                    cbz_layout=cbz_layout,
                    **metadata,
                )
            if cbz_path and not CLEAN_OUTPUT:
                console.print(f"[bold green]Output created:[/] [cyan]{cbz_path}[/]")

        # Summary output for clean mode
        if CLEAN_OUTPUT:
            msg = (
                f"Downloaded '{manga_name_clean}' (lang={lang}): "
                f"chapters={total_chapters_downloaded}, pages={total_pages_downloaded}"
            )
            if cbz_path:
                msg += f", output='{cbz_path}'"
            print(msg)

        if latest_chapter_local > 0 and not stop_signal:
            # SQLite writes are synchronous — run in a thread to avoid
            # blocking the event loop during the DB write.
            await asyncio.to_thread(
                record_download,
                manga_name=manga_name_clean,
                latest_chapter_local=latest_chapter_local,
                latest_chapter_from_mangadex=latest_chapter_from_mangadex,
                source_type="mangadex",
                source_url=manga_url,
                source_id=manga_uuid,
                language=lang,
                output_path=manga_root_folder,
            )
        return DownloadResult(
            total_pages_downloaded,
            total_pages_expected,
            completed_folders,
            discovery_complete=all_complete and not stop_signal,
        )
