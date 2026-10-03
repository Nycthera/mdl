"""Generic scraper for direct image source URLs."""

import asyncio

import aiohttp
from rich.console import Console

from src.downloader import url_exists
from src.scrapers import _collect_chapter_urls_for_download
from src.scrapers import set_clean_output as set_scraper_clean_output
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


async def _find_chapter_source(
    session: aiohttp.ClientSession,
    manga_name: str,
    chapter_label: str,
    base_urls: list[str],
) -> str | None:
    """Return the first source that confirms a chapter, cancelling slower mirrors."""

    async def check(base: str) -> str | None:
        url = f"{base}{manga_name}/{chapter_label}-001.png"
        return base if await url_exists(session, url) else None

    check_tasks = [asyncio.create_task(check(base)) for base in base_urls]
    try:
        for check in asyncio.as_completed(check_tasks):
            if source := await check:
                return source
        return None
    finally:
        for task in check_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*check_tasks, return_exceptions=True)


async def _chapter_exists(
    session: aiohttp.ClientSession,
    manga_name: str,
    chapter_label: str,
    base_urls: list[str],
) -> bool:
    """Return whether a chapter has at least one page on any configured source."""
    return await _find_chapter_source(session, manga_name, chapter_label, base_urls) is not None


async def gather_all_urls(
    manga_name: str,
    start_chapter: int = 1,
    start_page: int = 1,
    max_pages: int = 50,
    max_decimals: int = 5,
    workers: int = 10,
    folder_base: str | None = None,
) -> list[tuple[str, str]]:
    """Gather all available page URLs for a manga."""
    urls_to_download = []
    folder_base = folder_base or sanitize_folder_name(manga_name)

    if not CLEAN_OUTPUT:
        console.print(f"[yellow]Gathering pages for {manga_name}...[/]")

    # Reuse one session to reduce overhead when probing many URLs
    connector = aiohttp.TCPConnector(
        limit=max(1, workers * 2),
        limit_per_host=max(1, workers),
        keepalive_timeout=30,
        ttl_dns_cache=300,
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        chapter = start_chapter
        while True:
            if stop_signal:
                break

            chapter_str = f"{chapter:04d}"
            chapter_labels = [chapter_str]
            chapter_labels.extend(f"{chapter_str}.{dec}" for dec in range(1, max_decimals + 1))

            # A missing decimal used to cost one full network round trip each.
            # Probe the integer and decimal variants together; the connector still
            # bounds actual socket concurrency to the configured worker budget.
            sources = await asyncio.gather(
                *(
                    _find_chapter_source(session, manga_name, label, BASE_URLS)
                    for label in chapter_labels
                )
            )
            found_chapters = [
                (label, source)
                for label, source in zip(chapter_labels, sources, strict=True)
                if source is not None
            ]

            for found_label, source in found_chapters:
                # The chapter probe already identified a responsive mirror. Try it
                # first during page discovery rather than repeating failed probes
                # against every configured source.
                ordered_sources = [source, *(base for base in BASE_URLS if base != source)]
                found_urls, chapter_folder = await _collect_chapter_urls_for_download(
                    manga_name,
                    found_label,
                    start_page,
                    max_pages,
                    folder_base,
                    workers,
                    session,
                    ordered_sources,
                )
                urls_to_download.extend((url, chapter_folder) for url in found_urls)
                if not CLEAN_OUTPUT:
                    console.print(f"[green]Chapter {found_label}: {len(found_urls)} pages found[/]")

            if not found_chapters:
                if not CLEAN_OUTPUT:
                    console.print(f"[red]Chapter {chapter_str} not found. Stopping.[/]")
                break

            chapter += 1

    return urls_to_download
