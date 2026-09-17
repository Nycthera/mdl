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
from src.downloader import download_all_pages
from src.http import (
    classify_failure,
    compute_backoff,
    get_default_timeout,
)
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
    except Exception:
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
                            console.print(f"[red]Error fetching chapters: {resp.status}[/]")
                            return chapters
                        await asyncio.sleep(compute_backoff(cls, attempt))
                        continue
                    data = await resp.json()
                    break
            except (TimeoutError, aiohttp.ClientError) as e:
                if attempt == max_retries:
                    console.print(f"[red]Network error fetching chapters: {e}[/]")
                    return chapters
                await asyncio.sleep(compute_backoff("retryable", attempt))
        else:
            # Retry loop exhausted without break — bail out.
            break

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
                        console.print(f"[red]Error fetching chapter {chapter_id}: {resp.status}[/]")
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
                return [f"{base_url}/data/{hash_code}/{page}" for page in pages]
        except (TimeoutError, aiohttp.ClientError) as e:
            if attempt == max_retries:
                console.print(f"[red]Network error fetching chapter {chapter_id}: {e}[/]")
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
    max_workers: int = 10,
) -> None:
    """Download all chapters from a MangaDex manga.

    `max_workers` controls per-chapter image download concurrency. Was
    previously hardcoded to 10; now respects the CLI --workers flag.
    """
    # Extract UUID and clean manga title
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        console.print("[red]Could not extract manga UUID from URL[/]")
        return

    # Single shared session across all MangaDex API + at-home calls —
    # HTTP keep-alive amortizes TLS handshakes across the whole run.
    from src.downloader import _build_connector

    connector = _build_connector(max_workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        manga_name_clean = await get_manga_name_from_md(manga_url, lang=lang, session=session)
        manga_name_clean = sanitize_folder_name(manga_name_clean)

        # Root folder named after manga
        manga_root_folder = manga_name_clean
        os.makedirs(manga_root_folder, exist_ok=True)

        if not CLEAN_OUTPUT:
            console.print(f"[cyan]Downloading '{manga_name_clean}' in language '{lang}'[/]")
        chapters = await fetch_all_chapters_md(manga_uuid, lang, session=session)
        if not CLEAN_OUTPUT:
            console.print(f"[green]Found {len(chapters)} chapters[/]")

        total_pages_downloaded = 0
        total_chapters_downloaded = 0
        latest_chapter_local = 0.0
        latest_chapter_from_mangadex = 0.0

        for chapter in chapters:
            attr = chapter.get("attributes", {})
            chapter_num = attr.get("chapter", "Unknown")
            chapter_title = attr.get("title", "")
            chap_id = chapter.get("id")
            chapter_match = re.search(r"(\d+(?:\.\d+)?)", str(chapter_num))
            if chapter_match:
                chapter_val = float(chapter_match.group(1))
                latest_chapter_from_mangadex = max(latest_chapter_from_mangadex, chapter_val)

            # Subfolder per chapter
            chapter_folder_name = f"Chapter_{chapter_num}_{chapter_title}".strip("_")
            chapter_folder_name = sanitize_folder_name(chapter_folder_name)
            chapter_folder = os.path.join(manga_root_folder, chapter_folder_name)

            images = await get_images_md(chap_id, use_saver=use_saver, session=session)
            if not images:
                if not CLEAN_OUTPUT:
                    console.print(f"[yellow]Skipping Chapter {chapter_num} (no images)[/]")
                continue

            os.makedirs(chapter_folder, exist_ok=True)
            if not CLEAN_OUTPUT:
                console.print(f"[yellow]Downloading Chapter {chapter_num}: {chapter_title}[/]")

            urls_to_download = [(url, chapter_folder) for url in images]
            await download_all_pages(
                urls_to_download,
                max_workers=max_workers,
                manga_name=manga_name_clean,
                track_to_db=False,
            )

            total_pages_downloaded += len(images)
            total_chapters_downloaded += 1
            if chapter_match:
                latest_chapter_local = max(latest_chapter_local, chapter_val)

            if not os.listdir(chapter_folder):
                if not CLEAN_OUTPUT:
                    console.print(f"[red]Removing empty folder {chapter_folder_name}[/]")
                os.rmdir(chapter_folder)

        # Create CBZ from the manga root folder.
        # zipfile + shutil.rmtree are synchronous — run them in a thread so
        # the event loop is not blocked during CBZ packaging.
        cbz_path = None
        if create_cbz:
            cbz_path = await asyncio.to_thread(create_cbz_for_all, manga_root_folder)
            if cbz_path and not CLEAN_OUTPUT:
                console.print(f"[bold green]CBZ created successfully:[/] [cyan]{cbz_path}[/]")

        # Summary output for clean mode
        if CLEAN_OUTPUT:
            msg = (
                f"Downloaded '{manga_name_clean}' (lang={lang}): "
                f"chapters={total_chapters_downloaded}, pages={total_pages_downloaded}"
            )
            if cbz_path:
                msg += f", cbz='{cbz_path}'"
            print(msg)

        if total_pages_downloaded > 0:
            # SQLite writes are synchronous — run in a thread to avoid
            # blocking the event loop during the DB write.
            await asyncio.to_thread(
                record_download,
                manga_name=manga_name_clean,
                latest_chapter_local=latest_chapter_local,
                latest_chapter_from_mangadex=latest_chapter_from_mangadex,
            )
