"""Webtoons.com scraper using Playwright for browser automation.

Follows the existing mdl scraper convention (same as weebcentral.py):
  * Module-level `set_clean_output()` / `set_stop_signal()` for global state.
  * One main async entry coroutine that returns image URLs + title.
  * Caller (main.py) is responsible for invoking download_all_pages() and
    create_cbz_for_all().

Supports two URL shapes:
  1. Single episode viewer URL:
     https://www.webtoons.com/en/{genre}/{title}/{episode}/viewer?title_no=X&episode_no=Y
     -> downloads just that one episode.
  2. Series list URL:
     https://www.webtoons.com/en/{genre}/{title}/list?title_no=X
     -> fetches every episode link, downloads all of them sequentially.

Webtoons image CDN (webtoon-phinf.pstatic.net) enforces anti-hotlink:
the Referer header MUST be https://www.webtoons.com/ or images 403.
This is handled by passing referer=... to download_all_pages().
"""

import asyncio
import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Webtoons image CDN hosts — used to filter <img> tags after the page renders.
_WEBTOON_IMG_HOSTS = (
    "webtoon-phinf.pstatic.net",
    "webtoons-phinf.pstatic.net",
    "webtoon.com",
)

# Referer required by Webtoons anti-hotlink protection.
WEBTOONS_REFERER = "https://www.webtoons.com/"

# Episode list / viewer URL detection.
_LIST_PATH_RE = re.compile(r"/list", re.IGNORECASE)
_VIEWER_PATH_RE = re.compile(r"/viewer", re.IGNORECASE)
_TITLE_NO_RE = re.compile(r"[?&]title_no=(\d+)", re.IGNORECASE)
_EPISODE_NO_RE = re.compile(r"[?&]episode_no=(\d+)", re.IGNORECASE)

# Series title pattern from a Webtoons URL path: /en/{genre}/{title}/...
_TITLE_FROM_PATH_RE = re.compile(r"/[^/]+/[^/]+/([^/]+)/", re.IGNORECASE)

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


def _is_series_list_url(url: str) -> bool:
    """True if the URL points to a series episode-list page (not a single episode)."""
    path = urlparse(url).path.lower()
    return bool(_LIST_PATH_RE.search(path))


def _is_viewer_url(url: str) -> bool:
    """True if the URL points to a single-episode viewer page."""
    path = urlparse(url).path.lower()
    return bool(_VIEWER_PATH_RE.search(path))


def _extract_title_from_url(url: str) -> str:
    """Best-effort series title extraction from a Webtoons URL path."""
    path = urlparse(url).path
    m = _TITLE_FROM_PATH_RE.search(path)
    if m:
        # Convert "some-cool-webtoon" -> "some cool webtoon"
        return m.group(1).replace("-", " ").replace("_", " ").strip().title()
    return "Unknown_Webtoon"


def _episode_folder_name(viewer_url: str, episode_idx: int) -> str:
    """Build a stable chapter folder name from the viewer URL.

    Prefer the episode_no query param (stable across renames); fall back to a
    zero-padded sequence index.
    """
    m = _EPISODE_NO_RE.search(viewer_url)
    if m:
        return f"episode_{int(m.group(1)):04d}"
    return f"episode_{episode_idx:04d}"


async def _launch_browser(p):
    """Try webkit -> firefox -> chromium (same fallback order as weebcentral)."""
    for name, engine in [
        ("webkit", p.webkit),
        ("firefox", p.firefox),
        ("chromium", p.chromium),
    ]:
        try:
            if not CLEAN_OUTPUT:
                console.print(f"[cyan]Trying {name} browser...[/]")
            browser = await engine.launch(headless=True, args=[])
            if not CLEAN_OUTPUT:
                console.print(f"[green]Using {name} browser[/]")
            return browser
        except Exception as e:
            if not CLEAN_OUTPUT:
                console.print(f"[yellow]{name} failed: {e}[/]")
    return None


async def _fetch_episode_image_urls(
    page,
    viewer_url: str,
) -> list[str]:
    """Navigate to a viewer URL and extract all episode image URLs.

    Webtoons lazy-loads images, so we scroll the page to force every image
    to load before scraping. We also wait briefly for the JS to swap
    data-url -> src on the visible images.
    """
    try:
        response = await page.goto(viewer_url, wait_until="load", timeout=45000)
        if not response or response.status != 200:
            if not CLEAN_OUTPUT:
                console.print(
                    f"[red]Failed to load viewer page "
                    f"(status {response.status if response else 0})[/]"
                )
            return []
    except Exception as e:
        if not CLEAN_OUTPUT:
            console.print(f"[red]Viewer page load warning: {e}[/]")
        return []

    # Webtoons viewer pages can be very tall (long-strip). Scroll to the
    # bottom in increments so every <img> gets its real src loaded.
    if not CLEAN_OUTPUT:
        console.print("[yellow]Scrolling viewer page for lazy-loaded images...[/]")
    last_height = 0
    for _ in range(60):  # cap at 60 iterations to avoid infinite loops
        if stop_signal:
            return []
        await page.mouse.wheel(0, 2000)
        await asyncio.sleep(0.4)
        # Break when the page stops growing.
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == last_height:
            # Try one more scroll to be sure.
            await page.mouse.wheel(0, 2000)
            await asyncio.sleep(0.5)
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == last_height:
                break
        last_height = current_height

    # Final settle delay for any in-flight image loads.
    await asyncio.sleep(1.5)

    img_elements = await page.query_selector_all("img")
    img_urls: list[str] = []
    for img in img_elements:
        # Try src first; if empty or placeholder, try data-url.
        src = await img.get_attribute("src")
        if not src:
            src = await img.get_attribute("data-url")
        if not src:
            continue
        # Filter: only keep Webtoons CDN images, with image extensions.
        if not any(h in src for h in _WEBTOON_IMG_HOSTS):
            continue
        if not src.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            # Some URLs have query strings (?type=q90); accept those too.
            if "?" not in src:
                continue
        img_urls.append(urljoin(viewer_url, src))

    # De-duplicate while preserving order (Webtoons sometimes duplicates img tags).
    seen = set()
    unique_urls: list[str] = []
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    return unique_urls


async def _fetch_episode_links(page, list_url: str) -> list[str]:
    """Scrape the episode list page and return viewer URLs in oldest-first order.

    Webtoons list pages show newest episodes first by default. We reverse the
    list so downloads proceed chronologically.
    """
    try:
        response = await page.goto(list_url, wait_until="load", timeout=45000)
        if not response or response.status != 200:
            if not CLEAN_OUTPUT:
                console.print(
                    f"[red]Failed to load list page "
                    f"(status {response.status if response else 0})[/]"
                )
            return []
    except Exception as e:
        if not CLEAN_OUTPUT:
            console.print(f"[red]List page load warning: {e}[/]")
        return []

    # Scroll to bottom to ensure all episodes are rendered (Webtoons paginates
    # the episode list via infinite scroll on some series).
    if not CLEAN_OUTPUT:
        console.print("[yellow]Scrolling episode list to load all episodes...[/]")
    last_height = 0
    for _ in range(40):
        if stop_signal:
            return []
        await page.mouse.wheel(0, 1500)
        await asyncio.sleep(0.3)
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == last_height:
            await asyncio.sleep(0.5)
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == last_height:
                break
        last_height = current_height

    # Episode links live in ul#_listUl li a (Webtoons' canonical list container).
    # Fall back to any anchor whose href contains "/viewer?".
    links: list[str] = []
    seen = set()

    # Primary selector.
    anchors = await page.query_selector_all("ul#_listUl a[href*='viewer']")
    if not anchors:
        # Fallback: any viewer link on the page.
        anchors = await page.query_selector_all("a[href*='/viewer']")

    for a in anchors:
        href = await a.get_attribute("href")
        if not href:
            continue
        full = urljoin(list_url, href)
        # Keep only viewer URLs that have an episode_no.
        if "/viewer" not in full.lower():
            continue
        if not _EPISODE_NO_RE.search(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)

    # Webtoons lists newest-first; reverse for chronological download order.
    links.reverse()
    return links


async def fetch_webtoons_images(
    url: str,
) -> tuple[list[tuple[str, str]], str]:
    """Fetch image URLs from a Webtoons.com URL.

    Returns (urls_to_download, title) where urls_to_download is a list of
    (image_url, chapter_folder) tuples ready for download_all_pages().

    The caller is responsible for calling download_all_pages(referer=WEBTOONS_REFERER)
    and create_cbz_for_all() — Webtoons' CDN requires a Referer header.
    """
    if not CLEAN_OUTPUT:
        console.print(
            Panel.fit(
                f"[bold magenta]Webtoons ✨[/bold magenta]\n[yellow]{url}[/]",
                title="[white on magenta] Webtoons Mode [/]",
                border_style="magenta",
            )
        )

    title = _extract_title_from_url(url)
    urls_to_download: list[tuple[str, str]] = []

    async with Stealth().use_async(async_playwright()) as p:
        browser = await _launch_browser(p)
        if not browser:
            raise RuntimeError("Failed to launch any Playwright browser")

        try:
            page = await browser.new_page()
            # Set a realistic User-Agent + the Webtoons referer on the page context
            # so the initial page load passes anti-bot checks.
            await page.set_extra_http_headers({"Referer": WEBTOONS_REFERER})

            if _is_viewer_url(url):
                # Single-episode mode.
                if not CLEAN_OUTPUT:
                    console.print("[cyan]Single-episode URL detected.[/]")
                img_urls = await _fetch_episode_image_urls(page, url)
                folder = _episode_folder_name(url, 1)
                urls_to_download = [(u, folder) for u in img_urls]

            elif _is_series_list_url(url):
                # Series mode: scrape episode list, then each viewer page.
                if not CLEAN_OUTPUT:
                    console.print("[cyan]Series list URL detected.[/]")
                episode_links = await _fetch_episode_links(page, url)
                if not episode_links:
                    if not CLEAN_OUTPUT:
                        console.print("[red]No episode links found on the list page.[/]")
                    return [], title

                if not CLEAN_OUTPUT:
                    console.print(f"[green]Found {len(episode_links)} episodes.[/]")

                for idx, ep_url in enumerate(episode_links, start=1):
                    if stop_signal:
                        break
                    if not CLEAN_OUTPUT:
                        console.print(f"[yellow]Fetching episode {idx}/{len(episode_links)}...[/]")
                    img_urls = await _fetch_episode_image_urls(page, ep_url)
                    if not img_urls:
                        if not CLEAN_OUTPUT:
                            console.print(f"[yellow]No images for episode {idx}; skipping.[/]")
                        continue
                    folder = _episode_folder_name(ep_url, idx)
                    urls_to_download.extend((u, folder) for u in img_urls)
            else:
                # Unknown URL shape — try treating it as a viewer URL.
                if not CLEAN_OUTPUT:
                    console.print("[yellow]Unrecognized URL shape; trying as viewer URL.[/]")
                img_urls = await _fetch_episode_image_urls(page, url)
                folder = _episode_folder_name(url, 1)
                urls_to_download = [(u, folder) for u in img_urls]
        finally:
            await browser.close()

    if not CLEAN_OUTPUT:
        table = Table(title="[bold magenta]Webtoons Extraction Summary[/bold magenta]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_row("Title", f"[bold white]{title}[/]")
        table.add_row("Episodes", f"[green]{len({f for _, f in urls_to_download})}[/]")
        table.add_row("Images Found", f"[green]{len(urls_to_download)}[/]")
        table.add_row(
            "Status",
            "[bold green]Success[/]" if urls_to_download else "[bold red]No images found[/]",
        )
        console.print()
        console.print(
            Panel(
                Align.center(table),
                border_style="magenta",
                title="✨ Scan Complete ✨",
            )
        )

    return urls_to_download, title
