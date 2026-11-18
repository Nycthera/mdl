"""MangaPill (mangapill.com) scraper.

Plain server-rendered HTML, single domain, no anti-bot/JS gating on the
reader — pure aiohttp + BeautifulSoup, no browser launch needed.

Supports two URL shapes:
  1. Chapter URL:  https://mangapill.com/chapters/<id>-chapter-<num>
     -> downloads just that one chapter.
  2. Series URL:   https://mangapill.com/manga/<id>/<slug>
     -> fetches every chapter link, then fetches all chapters CONCURRENTLY
        (bounded by `workers`), same pattern as manganato.py.
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

BASE_URL = "https://mangapill.com"
MANGAPILL_DOMAINS = ("mangapill.com",)

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


def is_mangapill_url(url: str) -> bool:
    """True if the URL's host is mangapill.com."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in MANGAPILL_DOMAINS)


def _is_chapter_path(url: str) -> bool:
    return "/chapters/" in urlparse(url).path


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    node = soup.select_one("h1")
    text = node.get_text(strip=True) if node else ""
    return text or fallback


def _extract_chapter_images(soup: BeautifulSoup, page_url: str = BASE_URL) -> list[str]:
    images: list[str] = []
    for img in soup.select("picture img"):
        src = img.get("data-src") or img.get("src")
        if src:
            absolute = urljoin(page_url, src.strip())
            try:
                validate_http_url(absolute)
            except ValueError:
                continue
            if absolute not in images:
                images.append(absolute)
    return images


def _extract_chapter_number(text: str) -> str | None:
    m = _CHAPTER_NUM_RE.search(text)
    return m.group(1) if m else None


def _extract_chapter_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return [(chapter_url, chapter_label), ...] in oldest-first order."""
    rows: list[tuple[str, str]] = []
    for link in soup.select("#chapters > div > a"):
        href = link.get("href")
        if not href:
            continue
        title = link.get_text(strip=True)
        url = urljoin(BASE_URL, href)
        if is_mangapill_url(url) and _is_chapter_path(url) and url not in {row[0] for row in rows}:
            rows.append((url, title))
    rows.reverse()  # listed newest-first; reverse for chronological order
    return rows


def _chapter_folder_name(label: str, url: str, idx: int) -> str:
    num = _extract_chapter_number(label)
    if num is None:
        m = re.search(r"chapter-(\d+(?:\.\d+)?)", url)
        num = m.group(1) if m else None
    if num is not None:
        try:
            return f"chapter_{float(num):g}"
        except ValueError:
            pass
    return f"chapter_{idx:04d}"


async def fetch_mangapill_images(
    url: str,
    workers: int = 10,
    *,
    start_chapter: int = 0,
    max_retries: int = 5,
) -> tuple[list[tuple[str, str]], str]:
    """Fetch image URLs from a MangaPill URL.

    Returns (urls_to_download, title) where urls_to_download is a list of
    (image_url, chapter_folder) tuples ready for download_all_pages().

    Series pages fetch every chapter's image list CONCURRENTLY (bounded by
    `workers`) instead of one at a time.
    """
    try:
        validate_http_url(url, allowed_hosts=MANGAPILL_DOMAINS)
    except ValueError as exc:
        raise RuntimeError(f"Unsafe MangaPill URL: {exc}") from exc
    if not CLEAN_OUTPUT:
        console.print(
            Panel.fit(
                f"[bold magenta]MangaPill ✨[/bold magenta]\n[yellow]{url}[/]",
                title="[white on magenta] MangaPill Mode [/]",
                border_style="magenta",
            )
        )

    fallback_title = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
    urls_to_download: list[tuple[str, str]] = []

    async with build_session(headers={"Referer": BASE_URL + "/"}) as session:
        if _is_chapter_path(url):
            if not CLEAN_OUTPUT:
                console.print("[cyan]Single chapter URL detected.[/]")
            html = await _fetch_html(session, url, max_retries=max_retries)
            soup = BeautifulSoup(html, "html.parser")
            title = _extract_title(soup, fallback_title)
            images = _extract_chapter_images(soup, url)
            if not images:
                raise RuntimeError(f"No chapter images found at {url}")
            folder = _chapter_folder_name(title, url, 1)
            urls_to_download = [(u, folder) for u in images]
        else:
            if not CLEAN_OUTPUT:
                console.print("[cyan]Series URL detected — gathering chapter list.[/]")
            html = await _fetch_html(session, url, max_retries=max_retries)
            soup = BeautifulSoup(html, "html.parser")
            title = _extract_title(soup, fallback_title)
            chapters = _extract_chapter_links(soup)
            if not chapters:
                raise RuntimeError(f"No chapter links found on the series page: {url}")

            if not CLEAN_OUTPUT:
                console.print(f"[green]Found {len(chapters)} chapters — fetching concurrently.[/]")

            async def read_images(chapter_url):
                html = await _fetch_html(session, chapter_url, max_retries=max_retries)
                return _extract_chapter_images(BeautifulSoup(html, "html.parser"), chapter_url)

            urls_to_download = await collect_chapters(
                chapters,
                workers=workers,
                read_images=read_images,
                folder_name=_chapter_folder_name,
                stopped=lambda: stop_signal,
                start_chapter=start_chapter,
            )

    if not CLEAN_OUTPUT:
        table = Table(title="[bold magenta]MangaPill Extraction Summary[/bold magenta]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_row("Title", f"[bold white]{title}[/]")
        table.add_row("Chapters", f"[green]{len({f for _, f in urls_to_download})}[/]")
        table.add_row("Images Found", f"[green]{len(urls_to_download)}[/]")
        table.add_row(
            "Status",
            ("[bold green]Success[/]" if urls_to_download else "[bold red]No images found[/]"),
        )
        console.print()
        console.print(
            Panel(Align.center(table), border_style="magenta", title="✨ Scan Complete ✨")
        )

    return urls_to_download, title
