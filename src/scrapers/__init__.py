"""Base URL scraper classes and utilities."""

import asyncio
import os

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
    urls: list[str],
    label: str,
    workers: int,
    session: aiohttp.ClientSession,
) -> list[str]:
    """Check which URLs exist and return the valid ones."""
    if not urls:
        return []

    sem = asyncio.Semaphore(max(1, workers))

    async def check_one(u: str) -> tuple[str, bool]:
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
    manga_name: str,
    chapter_str: str,
    start_page: int,
    max_pages: int,
    base_urls: list[str],
) -> list[str]:
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
    base_urls: list[str],
) -> tuple[list[str], str]:
    """Collect a contiguous chapter, preferring the first responsive mirror.

    Direct-image chapters are contiguous. Probe the responsive source across the
    requested range in one concurrent pass, then consult the remaining mirrors only
    for the first gap. This avoids paying for every absent trailing page on every
    mirror (the common case at the end of every chapter).
    """
    chapter_folder = os.path.join(folder_base, f"chapter_{chapter_label}")
    urls = _build_chapter_urls(
        manga_name, chapter_label, start_page, max_pages, base_urls
    )
    if not urls or not base_urls:
        return [], chapter_folder

    page_names = [
        f"{chapter_label}-{page:03d}.png" for page in range(start_page, max_pages + 1)
    ]
    primary_urls = [
        f"{base_urls[0]}{manga_name}/{page_name}" for page_name in page_names
    ]
    found_primary = await _collect_existing_urls(
        primary_urls, f"Checking Chapter {chapter_label}", workers, session
    )
    available_primary = set(found_primary)
    selected: dict[str, str] = {
        page_name: url
        for page_name, url in zip(page_names, primary_urls, strict=True)
        if url in available_primary
    }

    for page_name in page_names:
        if page_name in selected:
            continue

        fallback_urls = [f"{base}{manga_name}/{page_name}" for base in base_urls[1:]]
        found_fallbacks = set(
            await _collect_existing_urls(
                fallback_urls,
                f"Checking Chapter {chapter_label} boundary",
                workers,
                session,
            )
        )
        for url in fallback_urls:
            if url in found_fallbacks:
                selected[page_name] = url
                break
        else:
            # The first page absent from every mirror marks the chapter boundary.
            break

    return [selected[name] for name in page_names if name in selected], chapter_folder
