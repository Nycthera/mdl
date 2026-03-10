"""Base URL scraper classes and utilities."""

import asyncio
import os
from typing import List, Tuple

import aiohttp
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from src.downloader import url_exists

console = Console()

# Global configuration
CLEAN_OUTPUT = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


async def _collect_existing_urls(
    urls: List[str],
    label: str,
    workers: int,
    session: aiohttp.ClientSession,
) -> List[str]:
    """Check which URLs exist and return the valid ones."""
    if not urls:
        return []

    sem = asyncio.Semaphore(max(1, workers))

    async def check_one(u: str) -> Tuple[str, bool]:
        async with sem:
            return u, await url_exists(session, u)

    tasks = [asyncio.create_task(check_one(u)) for u in urls]
    found_urls = []

    if not CLEAN_OUTPUT:
        with Progress(
            SpinnerColumn(style="yellow"),
            TextColumn(f"[bold yellow]{label}[/]"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.1f}%",
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Checking", total=len(urls))
            for coro in asyncio.as_completed(tasks):
                url, exists = await coro
                progress.update(task, advance=1)
                if exists:
                    found_urls.append(url)
    else:
        for coro in asyncio.as_completed(tasks):
            url, exists = await coro
            if exists:
                found_urls.append(url)

    return found_urls


def _build_chapter_urls(
    manga_name: str, chapter_str: str, start_page: int, max_pages: int, base_urls: List[str]
) -> List[str]:
    """Build list of chapter page URLs."""
    return [
        f"{base}{manga_name}/{chapter_str}-{page:03d}.png"
        for base in base_urls
        for page in range(start_page, max_pages + 1)
    ]


async def _collect_chapter_urls_for_download(
    manga_name: str,
    chapter_label: str,
    start_page: int,
    max_pages: int,
    folder_base: str,
    workers: int,
    session: aiohttp.ClientSession,
    base_urls: List[str],
) -> Tuple[List[str], str]:
    """Collect URLs for a single chapter."""
    chapter_folder = os.path.join(folder_base, f"chapter_{chapter_label}")
    os.makedirs(chapter_folder, exist_ok=True)
    urls = _build_chapter_urls(manga_name, chapter_label, start_page, max_pages, base_urls)
    found_urls = await _collect_existing_urls(
        urls, f"Checking Chapter {chapter_label}", workers, session
    )
    return found_urls, chapter_folder
