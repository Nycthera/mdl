"""Generic scraper for direct image source URLs."""

import asyncio
from typing import List, Tuple

import aiohttp
from rich.console import Console

from src.downloader import url_exists
from src.scrapers import _collect_chapter_urls_for_download, set_clean_output as set_scraper_clean_output
from src.utils import sanitize_folder_name

console = Console()

# Global configuration
CLEAN_OUTPUT = False
stop_signal = False

# Base URLs for different manga sources
BASE_URLS = [
    "https://scans.lastation.us/manga/",
    "https://official.lowee.us/manga/",
    "https://hot.planeptune.us/manga/",
    "https://scans-hot.planeptune.us/manga/",
]


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value
    set_scraper_clean_output(value)


def set_stop_signal(value: bool) -> None:
    """Set the stop signal globally."""
    global stop_signal
    stop_signal = value


async def gather_all_urls(
    manga_name: str,
    start_chapter: int = 1,
    start_page: int = 1,
    max_pages: int = 50,
    max_decimals: int = 5,
    workers: int = 10,
    folder_base: str | None = None,
) -> List[Tuple[str, str]]:
    """Gather all available page URLs for a manga."""
    urls_to_download = []
    folder_base = folder_base or sanitize_folder_name(manga_name)
    
    if not CLEAN_OUTPUT:
        console.print(f"[yellow]Gathering pages for {manga_name}...[/]")

    # Reuse one session to reduce overhead when probing many URLs
    connector = aiohttp.TCPConnector(
        limit=max(1, workers * 2),
        limit_per_host=max(1, workers),
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        chapter = start_chapter
        while True:
            if stop_signal:
                break

            chapter_str = f"{chapter:04d}"
            check_tasks = [
                url_exists(session, f"{base}{manga_name}/{chapter_str}-001.png")
                for base in BASE_URLS
            ]
            results = await asyncio.gather(*check_tasks)
            found_any = any(results)

            if found_any:
                found_urls, chapter_folder = await _collect_chapter_urls_for_download(
                    manga_name,
                    chapter_str,
                    start_page,
                    max_pages,
                    folder_base,
                    workers,
                    session,
                    BASE_URLS,
                )
                urls_to_download.extend((url, chapter_folder) for url in found_urls)
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[green]Chapter {chapter_str}: {len(found_urls)} pages found[/]"
                    )
            else:
                # Fallback: look for decimal chapters like 0001.5 when 0001 is missing
                decimal_found_any = False
                for dec in range(1, max_decimals + 1):
                    chapter_decimal_str = f"{chapter_str}.{dec}"
                    first_page_url = (
                        f"{BASE_URLS[0]}{manga_name}/{chapter_decimal_str}-001.png"
                    )
                    if await url_exists(session, first_page_url):
                        decimal_found_any = True
                        found_urls, chapter_folder = await _collect_chapter_urls_for_download(
                            manga_name,
                            chapter_decimal_str,
                            start_page,
                            max_pages,
                            folder_base,
                            workers,
                            session,
                            BASE_URLS,
                        )
                        urls_to_download.extend(
                            (url, chapter_folder) for url in found_urls
                        )
                        if not CLEAN_OUTPUT:
                            console.print(
                                f"[green]Chapter {chapter_decimal_str}: {len(found_urls)} pages found[/]"
                            )

                if not decimal_found_any:
                    if not CLEAN_OUTPUT:
                        console.print(
                            f"[red]Chapter {chapter_str} not found. Stopping.[/]"
                        )
                    break

            chapter += 1

    return urls_to_download
