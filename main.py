#!/usr/bin/env python3
"""Manga Downloader - A Python-based manga downloader supporting multiple sources."""

import asyncio
import os
import signal
import sys
from urllib.parse import urlparse

try:
    from rich.align import Align
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:  # Fallback to stdlib-only behavior when Rich is not installed
    RICH_AVAILABLE = False

    class Console:
        """Minimal fallback console that prints directly to stdout."""

        def print(self, *args, **kwargs):
            # Ignore Rich-specific kwargs like style, justify, etc.
            print(*args)

    class Align:
        """Fallback Align that simply stores the renderable."""

        def __init__(self, renderable, *_, **__):
            self.renderable = renderable

    class Panel:
        """Fallback Panel that simply stores the renderable."""

        def __init__(self, renderable, *_, **__):
            self.renderable = renderable

    class Table:
        """Fallback Table that records rows for later printing."""

        def __init__(self, *_, **__):
            self._rows = []

        def add_column(self, *_, **__):
            # Column metadata is ignored in the fallback implementation.
            pass

        def add_row(self, *columns):
            self._rows.append(columns)


from src.cbz import create_cbz_for_all
from src.cbz import set_clean_output as set_cbz_clean_output
from src.cli import parse_args
from src.config import load_config, save_config
from src.database.manga_db import (
    get_tracked_manga,
)
from src.database.manga_db import (
    set_clean_output as set_db_clean_output,
)
from src.database.manga_db import (
    set_dev_mode as set_db_dev_mode,
)
from src.downloader import (
    download_all_pages,
)
from src.downloader import (
    set_clean_output as set_downloader_clean_output,
)
from src.downloader import (
    set_dev_mode as set_downloader_dev_mode,
)
from src.downloader import (
    set_stop_signal as set_downloader_stop_signal,
)
from src.http import set_default_timeout
from src.scrapers.generic import (
    gather_all_urls,
)
from src.scrapers.generic import (
    set_clean_output as set_generic_clean_output,
)
from src.scrapers.generic import (
    set_stop_signal as set_generic_stop_signal,
)
from src.scrapers.mangadex import (
    download_md_chapters,
)
from src.scrapers.mangadex import (
    set_clean_output as set_md_clean_output,
)
from src.scrapers.mangadex import (
    set_stop_signal as set_md_stop_signal,
)
from src.scrapers.webtoons import (
    WEBTOONS_REFERER,
    fetch_webtoons_images,
)
from src.scrapers.webtoons import (
    set_clean_output as set_webtoons_clean_output,
)
from src.scrapers.webtoons import (
    set_stop_signal as set_webtoons_stop_signal,
)
from src.scrapers.weebcentral import (
    fetch_weebcentral_images,
)
from src.scrapers.weebcentral import (
    set_clean_output as set_weeb_clean_output,
)
from src.system_utils import credits, update
from src.utils import get_slug_and_pretty, validate_manga_input

console = Console()

# Global state
stop_signal = False
CLEAN_OUTPUT = False
DEV_MODE = False


def set_global_clean_output(value: bool) -> None:
    """Set clean output mode globally across all modules."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value
    set_downloader_clean_output(value)
    set_cbz_clean_output(value)
    set_generic_clean_output(value)
    set_md_clean_output(value)
    set_weeb_clean_output(value)
    set_webtoons_clean_output(value)
    set_db_clean_output(value)


def set_global_stop_signal(value: bool) -> None:
    """Set stop signal globally across all modules."""
    global stop_signal
    stop_signal = value
    set_downloader_stop_signal(value)
    set_generic_stop_signal(value)
    set_md_stop_signal(value)
    set_webtoons_stop_signal(value)


def set_global_dev_mode(value: bool) -> None:
    """Set developer debug mode globally across modules."""
    global DEV_MODE
    DEV_MODE = value
    set_downloader_dev_mode(value)
    set_db_dev_mode(value)


def print_clean_summary(title: str, chapters: int, pages: int, cbz_path: str | None = None) -> None:
    """Print a single boxed summary for clean-output mode."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Title", title)
    table.add_row("Chapters", str(chapters))
    table.add_row("Pages", str(pages))
    if cbz_path:
        table.add_row("CBZ", cbz_path)

    console.print(
        Panel(
            Align.center(table),
            border_style="cyan",
            title="[white on cyan] Summary [/]",
        )
    )


def signal_handler(sig, frame):
    """Handle interrupt signals gracefully."""
    set_global_stop_signal(True)
    console.print("\n[red]Received interrupt. Stopping gracefully...[/]")


signal.signal(signal.SIGINT, signal_handler)


def _calculate_resume_chapter(latest_local: float) -> int:
    """Pick a safe chapter to resume from when checking for updates.

    We start from the integer part so decimal chapters after that point are not skipped.
    """
    return max(1, int(latest_local))


def _detect_source_from_input(manga_input: str) -> str | None:
    """Detect known source from a user input URL.

    Returns one of: "mangadex", "weebcentral", "webtoons", or None.
    """
    text = (manga_input or "").strip()
    if not text:
        return None

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if not host and text.lower().startswith("www."):
        # Handle inputs like "www.example.com/..." without a scheme.
        host = text.lower().split("/", 1)[0]

    if host == "mangadex.org" or host.endswith(".mangadex.org"):
        return "mangadex"
    if host == "weebcentral.com" or host.endswith(".weebcentral.com"):
        return "weebcentral"
    if host == "webtoons.com" or host.endswith(".webtoons.com"):
        return "webtoons"
    return None


async def _auto_update_from_db(
    workers: int,
    start_page: int,
    max_pages: int,
    cbz_flag: bool,
    max_retries: int = 5,
) -> None:
    """Process all tracked manga and fetch only new chapters."""
    tracked = get_tracked_manga()
    if not tracked:
        if not CLEAN_OUTPUT:
            console.print("[yellow]No tracked manga found in database.[/]")
        return

    if not CLEAN_OUTPUT:
        console.print(f"[bold cyan]DB auto-update: checking {len(tracked)} tracked manga[/]")

    processed = 0
    updated = 0

    for item in tracked:
        if stop_signal:
            break

        manga_name = str(item["manga_name"])
        latest_local = float(item["latest_chapter_local"])
        # Stored source numbers are a snapshot, not a live release check.
        # Always probe the source; otherwise up-to-date rows never update again.

        start_chapter = _calculate_resume_chapter(latest_local)

        if not CLEAN_OUTPUT:
            console.print(
                f"[cyan]Checking '{manga_name}' from chapter {start_chapter} (db latest={latest_local})[/]"
            )

        slug, pretty_name = get_slug_and_pretty(manga_name)
        urls_to_download = await gather_all_urls(
            slug,
            start_chapter=start_chapter,
            start_page=start_page,
            max_pages=max_pages,
            max_decimals=10,
            workers=workers,
            folder_base=pretty_name,
        )

        processed += 1
        if not urls_to_download:
            if not CLEAN_OUTPUT:
                console.print(f"[yellow]No new pages for '{manga_name}'.[/]")
            continue

        download_result = await download_all_pages(
            urls_to_download,
            max_workers=workers,
            manga_name=pretty_name,
            max_retries=max_retries,
        )
        updated += int(download_result.complete)

        if cbz_flag and not stop_signal and download_result.complete:
            if os.path.isdir(pretty_name) and any(
                f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
            ):
                # Archive file operations are synchronous — run in a thread
                # so the event loop is not blocked during CBZ packaging.
                cbz_created_path = await asyncio.to_thread(create_cbz_for_all, pretty_name)
                if cbz_created_path and not CLEAN_OUTPUT:
                    console.print(
                        f"[bold green]CBZ created successfully:[/] [cyan]{cbz_created_path}[/]"
                    )

    if not CLEAN_OUTPUT:
        console.print(
            f"[bold cyan]DB auto-update complete:[/] checked={processed}, updated={updated}"
        )


# ============================================================================
# MAIN FUNCTION
# ============================================================================


async def main():
    """Main entry point for the manga downloader."""
    args = parse_args()
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        console.print(f"[red]Cannot load configuration: {exc}[/]")
        raise SystemExit(1) from exc
    set_global_stop_signal(False)

    manga_name = args.manga or config.get("manga_name")
    start_chapter = (
        args.start_chapter if args.start_chapter is not None else config.get("start_chapter", 1)
    )
    start_page = args.start_page or config.get("start_page", 1)
    max_pages = args.max_pages or config.get("max_pages", 50)
    workers = args.workers or config.get("workers", 10)
    cbz_flag = args.cbz if args.cbz is not None else config.get("cbz", True)
    md_lang = args.md_lang or config.get("md_language", "en")
    update_flag = args.update or config.get("update", False)
    auto_update_db_flag = args.auto_update_db
    dev_flag = args.dev
    clean_flag = args.clean_output or config.get("clean_output", False)
    credits_flag = args.credits
    max_retries = getattr(args, "max_retries", 5) or 5
    timeout = getattr(args, "timeout", 30) or 30

    # Apply the timeout globally to all HTTP clients (downloader + MangaDex API).
    set_default_timeout(timeout)

    # Configure output mode globally
    set_global_dev_mode(bool(dev_flag))
    set_global_clean_output(bool(clean_flag))

    if update_flag:
        update()
        return

    if credits_flag:
        credits(show=True)
        return

    if auto_update_db_flag:
        await _auto_update_from_db(
            workers=workers,
            start_page=start_page,
            max_pages=max_pages,
            cbz_flag=cbz_flag,
            max_retries=max_retries,
        )
        return

    if not config.get("credits_shown", False):
        credits(show=True)
        config["credits_shown"] = True
        save_config(config)

    validate_manga_input(manga_name)

    if str(manga_name).lower().startswith("www."):
        manga_name = "https://" + str(manga_name)
    source = _detect_source_from_input(str(manga_name))

    # ---- MangaDex case ----
    if source == "mangadex":
        await download_md_chapters(
            manga_name,
            lang=md_lang,
            use_saver=False,
            create_cbz=cbz_flag,
            max_workers=workers,
            max_retries=max_retries,
            start_chapter=args.start_chapter if args.start_chapter is not None else 0,
        )
        return

    # ---- WeebCentral explicit URL case ----
    if source == "weebcentral":
        if not CLEAN_OUTPUT:
            console.print(
                Panel.fit(
                    "[bold magenta] Entering WeebCentral Mode [/]",
                    border_style="magenta",
                )
            )
        img_urls, title = await fetch_weebcentral_images(str(manga_name))
        if not img_urls:
            console.print("[red]No images detected, exiting WeebCentral mode.[/]")
            sys.exit(1)

        slug, pretty_name = get_slug_and_pretty(title)
        if not CLEAN_OUTPUT:
            console.print(
                f"[yellow] Starting downloads for: [bold cyan]{pretty_name}[/bold cyan][/]"
            )

        # Download the images actually extracted from the requested chapter.
        # Its stable URL id keeps different chapters in separate folders.
        chapter_id = urlparse(str(manga_name)).path.rstrip("/").rsplit("/", 1)[-1]
        from src.utils import sanitize_folder_name

        chapter_folder = os.path.join(pretty_name, sanitize_folder_name(chapter_id))
        urls_to_download = [(url, chapter_folder) for url in dict.fromkeys(img_urls)]
        if not urls_to_download:
            console.print(f"[yellow]No pages found for '{manga_name}'.[/]")

        download_result = await download_all_pages(
            urls_to_download,
            max_workers=workers,
            manga_name=pretty_name,
            max_retries=max_retries,
        )

        cbz_created_path = None
        if cbz_flag and not stop_signal and download_result.complete:
            if os.path.isdir(pretty_name) and any(
                f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
            ):
                # Archive file operations are synchronous — run in a thread
                # so the event loop is not blocked during CBZ packaging.
                cbz_created_path = await asyncio.to_thread(create_cbz_for_all, pretty_name)
                if cbz_created_path and not CLEAN_OUTPUT:
                    console.print(
                        f"[bold green]CBZ created successfully:[/] [cyan]{cbz_created_path}[/]"
                    )
            else:
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[yellow]No downloaded files for '{pretty_name}' — skipping CBZ creation.[/]"
                    )

        # Summary output for clean mode
        if CLEAN_OUTPUT:
            total_pages = download_result.successful_pages
            total_chapters = len(download_result.completed_folders)
            print_clean_summary(pretty_name, total_chapters, total_pages, cbz_created_path)
        return

    # ---- Webtoons.com case ----
    if source == "webtoons":
        if not CLEAN_OUTPUT:
            console.print(
                Panel.fit(
                    "[bold magenta] Entering Webtoons Mode [/]",
                    border_style="magenta",
                )
            )
        urls_to_download, title = await fetch_webtoons_images(str(manga_name))
        if not urls_to_download:
            console.print("[red]No images detected, exiting Webtoons mode.[/]")
            sys.exit(1)

        # Use the title from the scraper as the folder name (it's already
        # human-readable: "Some Cool Webtoon").
        from src.utils import sanitize_folder_name

        pretty_name = sanitize_folder_name(title)
        urls_to_download = [
            (url, os.path.join(pretty_name, folder)) for url, folder in urls_to_download
        ]
        if not CLEAN_OUTPUT:
            console.print(
                f"[yellow] Starting downloads for: [bold cyan]{pretty_name}[/bold cyan][/]"
            )

        download_result = await download_all_pages(
            urls_to_download,
            max_workers=workers,
            manga_name=pretty_name,
            max_retries=max_retries,
            referer=WEBTOONS_REFERER,  # required — Webtoons CDN enforces anti-hotlink
        )

        cbz_created_path = None
        if cbz_flag and not stop_signal and download_result.complete:
            if os.path.isdir(pretty_name) and any(
                f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
            ):
                cbz_created_path = await asyncio.to_thread(create_cbz_for_all, pretty_name)
                if cbz_created_path and not CLEAN_OUTPUT:
                    console.print(
                        f"[bold green]CBZ created successfully:[/] [cyan]{cbz_created_path}[/]"
                    )
            else:
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[yellow]No downloaded files for '{pretty_name}' — skipping CBZ creation.[/]"
                    )

        if CLEAN_OUTPUT:
            total_pages = download_result.successful_pages
            total_chapters = len(download_result.completed_folders)
            print_clean_summary(pretty_name, total_chapters, total_pages, cbz_created_path)
        return

    # ---- Regular direct image source case ----
    slug, pretty_name = get_slug_and_pretty(str(manga_name))
    urls_to_download = await gather_all_urls(
        slug,
        start_chapter=start_chapter,
        start_page=start_page,
        max_pages=max_pages,
        max_decimals=10,
        workers=workers,
        folder_base=pretty_name,
    )

    if not urls_to_download:
        if not CLEAN_OUTPUT:
            console.print(f"[yellow]No pages found for '{manga_name}' (slug: {slug}).[/]")
        return

    download_result = await download_all_pages(
        urls_to_download,
        max_workers=workers,
        manga_name=pretty_name,
        max_retries=max_retries,
    )

    # ---- CBZ packaging ----
    cbz_created_path = None
    if cbz_flag and not stop_signal and download_result.complete:
        if os.path.isdir(pretty_name) and any(
            f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
        ):
            # Archive file operations are synchronous — run in a thread
            # so the event loop is not blocked during CBZ packaging.
            cbz_created_path = await asyncio.to_thread(create_cbz_for_all, pretty_name)
            if cbz_created_path and not CLEAN_OUTPUT:
                console.print(
                    f"[bold green]CBZ created successfully:[/] [cyan]{cbz_created_path}[/]"
                )
        else:
            if not CLEAN_OUTPUT:
                console.print(
                    f"[yellow]No downloaded files for '{pretty_name}' — skipping CBZ creation.[/]"
                )

    # Summary output for clean mode
    if CLEAN_OUTPUT:
        total_pages = download_result.successful_pages
        total_chapters = len(download_result.completed_folders)
        print_clean_summary(pretty_name, total_chapters, total_pages, cbz_created_path)


if __name__ == "__main__":
    # Skip banner when clean output requested via CLI
    if "--clean-output" not in sys.argv:
        print("""
\033[96m          
 _ __ ___   __ _ _ __   __ _  __ _                       
| '_ ` _ \\ / _` | '_ \\ / _` |/ _` |                      
| | | | | | (_| | | | | (_| | (_| |                      
|_| |_| |_|\\__,_|_| |_|\\__, |\\__,_|                      
     _                 |___/                 _           
  __| | _____      ___ __ | | ___   __ _  __| |
 / _` |/ _ \\ \\ /\\ / / '_ \\| |/ _ \\ / _` |/ _` |
| (_| |  __/\\ V  V /| | | | | (_) | (_| | (_| |
 \\__,_|\\___| \\_/\\_/ |_| |_|_|\\___/ \\__,_|\\__,_|
\033[0m
""")
    asyncio.run(main())
