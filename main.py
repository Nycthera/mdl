#!/usr/bin/env python3
"""Manga Downloader - A Python-based manga downloader supporting multiple sources."""

import asyncio
import os
import signal
import sys

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cli import parse_args
from src.config import load_config, save_config
from src.utils import validate_manga_input, get_slug_and_pretty
from src.downloader import (
    download_all_pages,
    set_clean_output as set_downloader_clean_output,
    set_dev_mode as set_downloader_dev_mode,
    set_stop_signal as set_downloader_stop_signal,
)
from src.cbz import create_cbz_for_all, set_clean_output as set_cbz_clean_output
from src.scrapers.generic import (
    gather_all_urls,
    set_clean_output as set_generic_clean_output,
    set_stop_signal as set_generic_stop_signal,
)
from src.scrapers.mangadex import (
    download_md_chapters,
    set_clean_output as set_md_clean_output,
    set_stop_signal as set_md_stop_signal,
)
from src.scrapers.weebcentral import (
    fetch_weebcentral_images,
    set_clean_output as set_weeb_clean_output,
)
from src.system_utils import update, credits
from src.database.manga_db import (
    get_tracked_manga,
    set_clean_output as set_db_clean_output,
    set_dev_mode as set_db_dev_mode,
)

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
    set_db_clean_output(value)


def set_global_stop_signal(value: bool) -> None:
    """Set stop signal globally across all modules."""
    global stop_signal
    stop_signal = value
    set_downloader_stop_signal(value)
    set_generic_stop_signal(value)
    set_md_stop_signal(value)


def set_global_dev_mode(value: bool) -> None:
    """Set developer debug mode globally across modules."""
    global DEV_MODE
    DEV_MODE = value
    set_downloader_dev_mode(value)
    set_db_dev_mode(value)


def print_clean_summary(
    title: str, chapters: int, pages: int, cbz_path: str | None = None
) -> None:
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


async def _auto_update_from_db(
    workers: int,
    start_page: int,
    max_pages: int,
    cbz_flag: bool,
) -> None:
    """Process all tracked manga and fetch only new chapters."""
    tracked = get_tracked_manga()
    if not tracked:
        if not CLEAN_OUTPUT:
            console.print("[yellow]No tracked manga found in database.[/]")
        return

    if not CLEAN_OUTPUT:
        console.print(
            f"[bold cyan]DB auto-update: checking {len(tracked)} tracked manga[/]"
        )

    processed = 0
    updated = 0

    for item in tracked:
        if stop_signal:
            break

        manga_name = str(item["manga_name"])
        latest_local = float(item["latest_chapter_local"])
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

        await download_all_pages(
            urls_to_download, max_workers=workers, manga_name=pretty_name
        )
        updated += 1

        if cbz_flag and not stop_signal:
            if os.path.isdir(pretty_name) and any(
                f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
            ):
                cbz_created_path = create_cbz_for_all(pretty_name)
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
    config = load_config()
    args = parse_args()

    manga_name = args.manga or config.get("manga_name")
    start_chapter = args.start_chapter or config.get("start_chapter", 1)
    start_page = args.start_page or config.get("start_page", 1)
    max_pages = args.max_pages or config.get("max_pages", 50)
    workers = args.workers or config.get("workers", 10)
    cbz_flag = args.cbz or config.get("cbz", True)
    md_lang = args.md_lang or config.get("md_language", "en")
    update_flag = args.update or config.get("update", False)
    auto_update_db_flag = args.auto_update_db
    dev_flag = args.dev
    clean_flag = args.clean_output or config.get("clean_output", False)
    credits_flag = args.credits

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
        )
        return

    if not config.get("credits_shown", False):
        credits(show=True)
        config["credits_shown"] = True
        save_config(config)

    validate_manga_input(manga_name)

    # ---- MangaDex case ----
    if manga_name.lower().startswith("http") and "mangadex" in manga_name.lower():
        await download_md_chapters(
            manga_name, lang=md_lang, use_saver=False, create_cbz=cbz_flag
        )
        return

    # ---- WeebCentral explicit URL case ----
    if manga_name.lower().startswith("http") and "weebcentral" in manga_name.lower():
        if not CLEAN_OUTPUT:
            console.print(
                Panel.fit(
                    "[bold magenta] Entering WeebCentral Mode [/]",
                    border_style="magenta",
                )
            )
        img_urls, title = await fetch_weebcentral_images(manga_name)
        if not img_urls:
            console.print("[red]No images detected, exiting WeebCentral mode.[/]")
            sys.exit(1)

        slug, pretty_name = get_slug_and_pretty(title)
        if not CLEAN_OUTPUT:
            console.print(
                f"[yellow] Starting downloads for: [bold cyan]{pretty_name}[/bold cyan][/]"
            )

        # For WeebCentral, use gather_all_urls starting from chapter 1
        urls_to_download = await gather_all_urls(
            slug,
            start_chapter=1,
            start_page=start_page,
            max_pages=max_pages,
            max_decimals=10,
            workers=workers,
            folder_base=pretty_name,
        )
        if not urls_to_download:
            console.print(f"[yellow]No pages found for '{manga_name}'.[/]")

        await download_all_pages(
            urls_to_download, max_workers=workers, manga_name=pretty_name
        )

        cbz_created_path = None
        if cbz_flag and not stop_signal:
            if os.path.isdir(pretty_name) and any(
                f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
            ):
                cbz_created_path = create_cbz_for_all(pretty_name)
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
            total_pages = len(urls_to_download)
            total_chapters = len({folder for _, folder in urls_to_download})
            print_clean_summary(pretty_name, total_chapters, total_pages, cbz_created_path)
        return

    # ---- Regular direct image source case ----
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

    if not urls_to_download:
        if not CLEAN_OUTPUT:
            console.print(
                f"[yellow]No pages found for '{manga_name}' (slug: {slug}).[/]"
            )
        return

    await download_all_pages(
        urls_to_download, max_workers=workers, manga_name=pretty_name
    )

    # ---- CBZ packaging ----
    cbz_created_path = None
    if cbz_flag and not stop_signal:
        if os.path.isdir(pretty_name) and any(
            f for f in os.listdir(pretty_name) if not f.lower().endswith(".cbz")
        ):
            cbz_created_path = create_cbz_for_all(pretty_name)
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
        total_pages = len(urls_to_download)
        total_chapters = len({folder for _, folder in urls_to_download})
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

