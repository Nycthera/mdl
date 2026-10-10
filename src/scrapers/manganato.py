"""Manganato / Mangakakalot family scraper.

Covers the long-running Manganato/Mangakakalot/Manganelo aggregator family,
which has rotated through many domains over the years while keeping the same
underlying site template. Plain server-rendered HTML — no JS needed to read
chapter images, so this is a pure aiohttp + BeautifulSoup scraper (no browser
launch), unlike weebcentral.py's Playwright fallback or webtoons.py.

Supports two URL shapes:
  1. Single chapter URL (e.g. ".../manga-xx/chapter-12")
     -> downloads just that one chapter.
  2. Series page URL (e.g. ".../manga-xx" or "/manga/some-title")
     -> fetches every chapter link, then fetches all chapters CONCURRENTLY
        (bounded by `workers`) rather than one at a time — the primary
        speed win over the sequential per-episode loop in webtoons.py.

Chapter vs. series is detected by DOM shape rather than URL path, since the
domain forks in this family don't agree on a single URL convention.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.http import build_session, validate_http_url
from src.scrapers.html_common import collect_chapters
from src.scrapers.html_common import fetch_html as _fetch_html

console = Console()

# Every domain this template family is currently known to run under.
# The family rotates domains periodically; add new ones here as they appear.
MANGANATO_DOMAINS = (
    "manganato.com",
    "chapmanganato.com",
    "chapmanganato.to",
    "readmanganato.com",
    "mangabats.com",
    "mangakakalot.fan",
    "mangakakalot.gg",
    "mangakakalove.com",
    "manganato.gg",
    "natomanga.com",
    "nelomanga.com",
    "nelomanga.net",
    "zazamanga.com",
    "zinmanga.net",
    "mangakakalot.com",
    "manganelo.com",
)

_CHAPTER_NUM_RE = re.compile(r"chapter[\s_-]*(\d+(?:\.\d+)?)", re.IGNORECASE)

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


def is_manganato_url(url: str) -> bool:
    """True if the URL's host belongs to the Manganato/Mangakakalot family."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith(f".{d}") for d in MANGANATO_DOMAINS)


def _absolute(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href:
        return None
    absolute = urljoin(base, href)
    if urlparse(absolute).scheme not in ("http", "https"):
        return None
    return absolute


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    for selector in ("h1.manga-info-title", ".manga-info-text h1", "h1"):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    return fallback


def _is_chapter_page(soup: BeautifulSoup) -> bool:
    """DOM-sniff: does this page look like a chapter reader, not a series page?"""
    return bool(
        soup.select_one(
            "#chapter-content img, .reading-detail img, "
            ".page_chapter img, .container-chapter-reader img"
        )
    )


def _extract_chapter_images(soup: BeautifulSoup, page_url: str) -> list[str]:
    images: list[str] = []
    for img in soup.select(
        "#chapter-content img, .reading-detail img, .page_chapter img, .container-chapter-reader img"
    ):
        src = img.get("data-src") or img.get("data-original") or img.get("src")
        absolute = _absolute(page_url, src)
        if absolute and absolute not in images:
            images.append(absolute)
    return images


def _extract_chapter_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    """Return [(chapter_url, chapter_label), ...] in oldest-first order."""
    selectors = (
        ".row-content-chapter li a",
        ".chapter-list li a",
        ".list-chapter li a",
        ".chapter-list .row a",
    )
    seen = set()
    rows: list[tuple[str, str]] = []
    for selector in selectors:
        for anchor in soup.select(selector):
            href = anchor.get("href")
            absolute = _absolute(page_url, href)
            if not absolute or not is_manganato_url(absolute) or absolute in seen:
                continue
            seen.add(absolute)
            rows.append((absolute, anchor.get_text(strip=True)))
        if rows:
            break  # first selector that matched anything wins
    rows.reverse()  # site lists newest-first; reverse for chronological order
    return rows


def _chapter_folder_name(label: str, url: str, idx: int) -> str:
    m = _CHAPTER_NUM_RE.search(label) or _CHAPTER_NUM_RE.search(url)
    if m:
        try:
            return f"chapter_{float(m.group(1)):g}"
        except ValueError:
            pass
    return f"chapter_{idx:04d}"


async def fetch_manganato_images(
    url: str,
    workers: int = 10,
    *,
    start_chapter: int = 0,
    max_retries: int = 5,
) -> tuple[list[tuple[str, str]], str]:
    """Fetch image URLs from a Manganato/Mangakakalot-family URL.

    Returns (urls_to_download, title) where urls_to_download is a list of
    (image_url, chapter_folder) tuples ready for download_all_pages().

    Series pages fetch every chapter's image list CONCURRENTLY (bounded by
    `workers`) instead of one at a time.
    """
    try:
        validate_http_url(url, allowed_hosts=MANGANATO_DOMAINS)
    except ValueError as exc:
        raise RuntimeError(f"Unsafe Manganato URL: {exc}") from exc
    if not CLEAN_OUTPUT:
        console.print(
            Panel.fit(
                f"[bold magenta]Manganato ✨[/bold magenta]\n[yellow]{url}[/]",
                title="[white on magenta] Manganato Mode [/]",
                border_style="magenta",
            )
        )

    fallback_title = (
        urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
    )
    urls_to_download: list[tuple[str, str]] = []

    async with build_session(headers={"Referer": url}) as session:
        html = await _fetch_html(session, url, max_retries=max_retries)
        soup = BeautifulSoup(html, "html.parser")

        if _is_chapter_page(soup):
            if not CLEAN_OUTPUT:
                console.print("[cyan]Single chapter URL detected.[/]")
            title = _extract_title(soup, fallback_title)
            images = _extract_chapter_images(soup, url)
            folder = _chapter_folder_name(title, url, 1)
            urls_to_download = [(u, folder) for u in images]
        else:
            if not CLEAN_OUTPUT:
                console.print("[cyan]Series page detected — gathering chapter list.[/]")
            title = _extract_title(soup, fallback_title)
            chapters = _extract_chapter_links(soup, url)
            if not chapters:
                raise RuntimeError(f"No chapter links found on the series page: {url}")

            if not CLEAN_OUTPUT:
                console.print(
                    f"[green]Found {len(chapters)} chapters — fetching concurrently.[/]"
                )

            async def read_images(chapter_url):
                html = await _fetch_html(session, chapter_url, max_retries=max_retries)
                return _extract_chapter_images(
                    BeautifulSoup(html, "html.parser"), chapter_url
                )

            urls_to_download = await collect_chapters(
                chapters,
                workers=workers,
                read_images=read_images,
                folder_name=_chapter_folder_name,
                stopped=lambda: stop_signal,
                start_chapter=start_chapter,
            )

    if not CLEAN_OUTPUT:
        table = Table(title="[bold magenta]Manganato Extraction Summary[/bold magenta]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_row("Title", f"[bold white]{title}[/]")
        table.add_row("Chapters", f"[green]{len({f for _, f in urls_to_download})}[/]")
        table.add_row("Images Found", f"[green]{len(urls_to_download)}[/]")
        table.add_row(
            "Status",
            (
                "[bold green]Success[/]"
                if urls_to_download
                else "[bold red]No images found[/]"
            ),
        )
        console.print()
        console.print(
            Panel(
                Align.center(table), border_style="magenta", title="✨ Scan Complete ✨"
            )
        )

    return urls_to_download, title
