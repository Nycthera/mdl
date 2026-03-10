"""MangaDex API scraper for manga downloads."""

import asyncio
import os
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import aiohttp
from rich.console import Console

from src.downloader import download_all_pages
from src.cbz import create_cbz_for_all
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


def extract_manga_uuid(url: str) -> Optional[str]:
    """Extract MangaDex UUID from URL."""
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "title":
            return parts[1]
    except Exception:
        pass
    return None


async def fetch_all_chapters_md(
    manga_uuid: str,
    lang: str = "en",
    session: Optional[aiohttp.ClientSession] = None,
) -> List[Dict[str, Any]]:
    """Fetch all chapters for a manga from MangaDex."""
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await fetch_all_chapters_md(manga_uuid, lang=lang, session=session)

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
        async with session.get(f"{API_ENDPOINT}/chapter", params=params) as resp:
            if resp.status == 429:
                console.print(
                    "[yellow]Rate limited by MangaDex, sleeping 5 seconds...[/]"
                )
                await asyncio.sleep(5)
                continue
            elif resp.status != 200:
                console.print(f"[red]Error fetching chapters: {resp.status}[/]")
                break
            data = await resp.json()
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
    session: Optional[aiohttp.ClientSession] = None,
) -> List[str]:
    """Fetch image URLs for a specific chapter."""
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await get_images_md(
                chapter_id,
                use_saver=use_saver,
                max_retries=max_retries,
                session=session,
            )

    for attempt in range(max_retries):
        await rate_limiter_athome.acquire("mangadex_athome")
        async with session.get(
            f"https://api.mangadex.org/at-home/server/{chapter_id}"
        ) as resp:
            if resp.status == 429:
                wait = (attempt + 1) * 5
                console.print(f"[yellow]Rate limited. Waiting {wait}s...[/]")
                await asyncio.sleep(wait)
                continue
            elif resp.status != 200:
                console.print(
                    f"[red]Error fetching chapter {chapter_id}: {resp.status}[/]"
                )
                return []
            data = await resp.json()
            chapter_data = data.get("chapter", {})
            base_url = data.get("baseUrl")
            hash_code = chapter_data.get("hash")
            pages = chapter_data.get("dataSaver" if use_saver else "data", [])
            if not base_url or not hash_code or not pages:
                return []
            return [f"{base_url}/data/{hash_code}/{page}" for page in pages]
    return []


async def get_manga_name_from_md(
    manga_url: str,
    lang: str = "en",
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    """Get manga title from MangaDex API."""
    from src.utils import extract_manga_name_from_url
    
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        return extract_manga_name_from_url(manga_url)
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await get_manga_name_from_md(manga_url, lang=lang, session=session)
    async with session.get(f"{API_ENDPOINT}/manga/{manga_uuid}") as resp:
        if resp.status != 200:
            return extract_manga_name_from_url(manga_url)
        data = await resp.json()
        data_obj = data.get("data", {})
        attributes = data_obj.get("attributes", {})
        title_dict = attributes.get("title", {})
        return (
            title_dict.get(lang)
            or title_dict.get("en")
            or list(title_dict.values())[0]
        )


async def download_md_chapters(
    manga_url: str,
    lang: str = "en",
    use_saver: bool = False,
    create_cbz: bool = True,
) -> None:
    """Download all chapters from a MangaDex manga."""
    # Extract UUID and clean manga title
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        console.print("[red]Could not extract manga UUID from URL[/]")
        return

    async with aiohttp.ClientSession() as session:
        manga_name_clean = await get_manga_name_from_md(
            manga_url, lang=lang, session=session
        )
        manga_name_clean = sanitize_folder_name(manga_name_clean)

        # Root folder named after manga
        manga_root_folder = manga_name_clean
        os.makedirs(manga_root_folder, exist_ok=True)

        if not CLEAN_OUTPUT:
            console.print(
                f"[cyan]Downloading '{manga_name_clean}' in language '{lang}'[/]"
            )
        chapters = await fetch_all_chapters_md(manga_uuid, lang, session=session)
        if not CLEAN_OUTPUT:
            console.print(f"[green]Found {len(chapters)} chapters[/]")

        total_pages_downloaded = 0
        total_chapters_downloaded = 0

        for chapter in chapters:
            attr = chapter.get("attributes", {})
            chapter_num = attr.get("chapter", "Unknown")
            chapter_title = attr.get("title", "")
            chap_id = chapter.get("id")

            # Subfolder per chapter
            chapter_folder_name = f"Chapter_{chapter_num}_{chapter_title}".strip("_")
            chapter_folder_name = sanitize_folder_name(chapter_folder_name)
            chapter_folder = os.path.join(manga_root_folder, chapter_folder_name)

            images = await get_images_md(chap_id, use_saver=use_saver, session=session)
            if not images:
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[yellow]Skipping Chapter {chapter_num} (no images)[/]"
                    )
                continue

            os.makedirs(chapter_folder, exist_ok=True)
            if not CLEAN_OUTPUT:
                console.print(
                    f"[yellow]Downloading Chapter {chapter_num}: {chapter_title}[/]"
                )

            urls_to_download = [(url, chapter_folder) for url in images]
            await download_all_pages(
                urls_to_download, max_workers=10, manga_name=manga_name_clean
            )

            total_pages_downloaded += len(images)
            total_chapters_downloaded += 1

            if not os.listdir(chapter_folder):
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[red]Removing empty folder {chapter_folder_name}[/]"
                    )
                os.rmdir(chapter_folder)

        # Create CBZ from the manga root folder
        cbz_path = None
        if create_cbz:
            cbz_path = create_cbz_for_all(manga_root_folder)
            if cbz_path and not CLEAN_OUTPUT:
                console.print(
                    f"[bold green]CBZ created successfully:[/] [cyan]{cbz_path}[/]"
                )

        # Summary output for clean mode
        if CLEAN_OUTPUT:
            msg = (
                f"Downloaded '{manga_name_clean}' (lang={lang}): "
                f"chapters={total_chapters_downloaded}, pages={total_pages_downloaded}"
            )
            if cbz_path:
                msg += f", cbz='{cbz_path}'"
            print(msg)
