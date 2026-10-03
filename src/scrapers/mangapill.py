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

import asyncio
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.http import DEFAULT_TIMEOUT, build_session, classify_failure, compute_backoff

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
    host = (urlparse(url).netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host in MANGAPILL_DOMAINS


def _is_chapter_path(url: str) -> bool:
    return "/chapters/" in urlparse(url).path


async def _fetch_html(session, url: str, *, max_retries: int = 4) -> str:
    """GET a page with the same classified-retry policy as image downloads."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=DEFAULT_TIMEOUT) as resp:
                if resp.status >= 400:
                    body = await resp.content.read(4096) if resp.status in (403, 503) else b""
                    cls = classify_failure(resp.status, body_snippet=body)
                    if cls == "permanent" or attempt == max_retries:
                        raise RuntimeError(f"HTTP {resp.status} fetching {url}")
                    await asyncio.sleep(compute_backoff(cls, attempt))
                    continue
                return await resp.text()
        except TimeoutError as e:
            last_exc = e
            if attempt == max_retries:
                raise RuntimeError(f"Timeout fetching {url}") from e
            await asyncio.sleep(compute_backoff("retryable", attempt))
    raise RuntimeError(f"Failed to fetch {url}") from last_exc


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    node = soup.select_one("h1")
    text = node.get_text(strip=True) if node else ""
    return text or fallback


def _extract_chapter_images(soup: BeautifulSoup) -> list[str]:
    images: list[str] = []
    for img in soup.select("picture img"):
        src = img.get("data-src") or img.get("src")
        if src and src not in images:
            images.append(src)
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
        url = href if href.startswith("http") else BASE_URL + href
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
) -> tuple[list[tuple[str, str]], str]:
    """Fetch image URLs from a MangaPill URL.

    Returns (urls_to_download, title) where urls_to_download is a list of
    (image_url, chapter_folder) tuples ready for download_all_pages().

    Series pages fetch every chapter's image list CONCURRENTLY (bounded by
    `workers`) instead of one at a time.
    """
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
            html = await _fetch_html(session, url)
            soup = BeautifulSoup(html, "html.parser")
            title = _extract_title(soup, fallback_title)
            images = _extract_chapter_images(soup)
            folder = _chapter_folder_name(title, url, 1)
            urls_to_download = [(u, folder) for u in images]
        else:
            if not CLEAN_OUTPUT:
                console.print("[cyan]Series URL detected — gathering chapter list.[/]")
            html = await _fetch_html(session, url)
            soup = BeautifulSoup(html, "html.parser")
            title = _extract_title(soup, fallback_title)
            chapters = _extract_chapter_links(soup)
            if not chapters:
                if not CLEAN_OUTPUT:
                    console.print("[red]No chapter links found on the series page.[/]")
                return [], title

            if not CLEAN_OUTPUT:
                console.print(f"[green]Found {len(chapters)} chapters — fetching concurrently.[/]")

            sem = asyncio.Semaphore(max(1, workers))

            async def _fetch_one(idx: int, chap_url: str, label: str) -> tuple[int, str, list[str]]:
                async with sem:
                    if stop_signal:
                        return idx, label, []
                    try:
                        chap_html = await _fetch_html(session, chap_url)
                    except Exception as e:
                        if not CLEAN_OUTPUT:
                            console.print(f"[yellow]Chapter '{label}' failed: {e}[/]")
                        return idx, label, []
                    chap_soup = BeautifulSoup(chap_html, "html.parser")
                    return idx, label, _extract_chapter_images(chap_soup)

            tasks = [
                asyncio.create_task(_fetch_one(idx, chap_url, label))
                for idx, (chap_url, label) in enumerate(chapters, start=1)
            ]

            results: list[tuple[int, str, list[str]]] = []
            done = 0
            for coro in asyncio.as_completed(tasks):
                idx, label, images = await coro
                done += 1
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[yellow]Fetched chapter {done}/{len(tasks)} "
                        f"({label or idx}): {len(images)} pages[/]"
                    )
                results.append((idx, label, images))

            for idx, label, images in sorted(results, key=lambda r: r[0]):
                if not images:
                    continue
                folder = _chapter_folder_name(label, chapters[idx - 1][0], idx)
                urls_to_download.extend((u, folder) for u in images)

    if not CLEAN_OUTPUT:
        table = Table(title="[bold magenta]MangaPill Extraction Summary[/bold magenta]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_row("Title", f"[bold white]{title}[/]")
        table.add_row("Chapters", f"[green]{len({f for _, f in urls_to_download})}[/]")
        table.add_row("Images Found", f"[green]{len(urls_to_download)}[/]")
        table.add_row(
            "Status",
            "[bold green]Success[/]" if urls_to_download else "[bold red]No images found[/]",
        )
        console.print()
        console.print(
            Panel(Align.center(table), border_style="magenta", title="✨ Scan Complete ✨")
        )

    return urls_to_download, title
