#!/usr/bin/env python3
"""Manga Downloader - A Python-based manga downloader supporting multiple sources."""

import asyncio
import os
import signal
import sqlite3
import sys
import zipfile
from urllib.parse import parse_qs, urlparse

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
    get_download_history,
    get_library_entry,
    get_tracked_manga,
    mark_library_checked,
)
from src.database.manga_db import (
    set_clean_output as set_db_clean_output,
)
from src.database.manga_db import (
    set_dev_mode as set_db_dev_mode,
)
from src.downloader import (
    DownloadResult,
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
from src.library import print_library, print_library_status
from src.output_formats import create_output_for_all
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
from src.scrapers.manganato import (
    fetch_manganato_images,
    is_manganato_url,
)
from src.scrapers.manganato import (
    set_clean_output as set_manganato_clean_output,
)
from src.scrapers.manganato import (
    set_stop_signal as set_manganato_stop_signal,
)
from src.scrapers.mangapill import (
    fetch_mangapill_images,
    is_mangapill_url,
)
from src.scrapers.mangapill import (
    set_clean_output as set_mangapill_clean_output,
)
from src.scrapers.mangapill import (
    set_stop_signal as set_mangapill_stop_signal,
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
from src.utils import get_slug_and_pretty, sanitize_folder_name, validate_manga_input
from src.verification import repair_library, verify_library

console = Console()


def _create_selected_output(
    folder_path: str, output_format: str, **options
) -> str | None:
    """Create an output file while preserving the CBZ test and extension hook."""
    if output_format == "cbz" and options.get("cbz_layout", "series") == "series":
        return create_cbz_for_all(
            folder_path,
            **{key: value for key, value in options.items() if key != "cbz_layout"},
        )
    return create_output_for_all(folder_path, output_format, **options)


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
    set_mangapill_clean_output(value)
    set_manganato_clean_output(value)
    set_db_clean_output(value)


def set_global_stop_signal(value: bool) -> None:
    """Set stop signal globally across all modules."""
    global stop_signal
    stop_signal = value
    set_downloader_stop_signal(value)
    set_generic_stop_signal(value)
    set_md_stop_signal(value)
    set_webtoons_stop_signal(value)
    set_mangapill_stop_signal(value)
    set_manganato_stop_signal(value)


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
        table.add_row("Output", cbz_path)

    console.print(
        Panel(
            Align.center(table),
            border_style="cyan",
            title="[white on cyan] Summary [/]",
        )
    )


def _print_verification(report) -> bool:
    """Print an integrity report."""
    if report.valid:
        console.print(
            f"[green]Verified {report.checked} files under '{report.root}'.[/]"
        )
        return True
    console.print(
        f"[yellow]Checked {report.checked} files; found {len(report.issues)} issue(s).[/]"
    )
    for issue in report.issues:
        console.print(f"[red]{issue.reason}:[/] {issue.path}")
    return False


def _print_download_history(title: str | None) -> None:
    """Print recent durable download-run summaries."""
    rows = get_download_history(title or None)
    if not rows:
        console.print("[yellow]No download history found.[/]")
        return
    table = Table(show_header=True, header_style="bold cyan")
    for heading in ("Title", "Source", "Status", "Pages", "Failed", "Started"):
        table.add_column(heading)
    for row in rows:
        table.add_row(
            str(row["manga_name"]),
            str(row["source_type"]),
            str(row["status"]),
            f"{row['successful_pages']}/{row['total_pages']}",
            str(row["failed_pages"]),
            str(row["started_at"]),
        )
    console.print(table)


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

    Return the supported scraper name, or None for a direct-host input.
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
    normalized = "https://" + text if text.lower().startswith("www.") else text
    if is_mangapill_url(normalized):
        return "mangapill"
    if is_manganato_url(normalized):
        return "manganato"
    return None


def _cbz_options(source, title, source_url, language, cbz_layout, reading_direction):
    direction = reading_direction
    if direction == "auto":
        direction = "ltr" if source == "webtoons" else "rtl"
    return {
        "cbz_layout": cbz_layout,
        "series": title,
        "source_url": source_url,
        "language": language,
        "reading_direction": direction,
    }


async def _download_url_source(
    source,
    url,
    *,
    workers,
    max_retries,
    start_chapter=0,
    output_format=None,
    cbz_layout="series",
    reading_direction="auto",
    metadata_language=None,
    optimize_mode="off",
    output_path=None,
    manga_name=None,
    source_id=None,
):
    """Download a routed HTML/browser source using the same path for library updates."""
    language = metadata_language
    if source == "weebcentral":
        images, title = await fetch_weebcentral_images(url)
        chapter_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        pages = [
            (image, sanitize_folder_name(chapter_id)) for image in dict.fromkeys(images)
        ]
        source_id = source_id or chapter_id
        _, title = get_slug_and_pretty(title)
        referer = url
    elif source == "webtoons":
        pages, title = await fetch_webtoons_images(url)
        source_id = (
            source_id or parse_qs(urlparse(url).query).get("title_no", [None])[0]
        )
        referer = WEBTOONS_REFERER
        if not language:
            language = urlparse(url).path.strip("/").split("/")[0] or None
    else:
        fetcher = (
            fetch_mangapill_images if source == "mangapill" else fetch_manganato_images
        )
        pages, title = await fetcher(
            url, workers=workers, start_chapter=start_chapter, max_retries=max_retries
        )
        referer = url
    title = manga_name or title
    destination = output_path or sanitize_folder_name(title)
    if not pages:
        if stop_signal:
            return DownloadResult(0, 0, [])
        if source in ("webtoons", "weebcentral"):
            raise RuntimeError(f"No images found at {url}")
        console.print(f"No chapters at or after {start_chapter} for {title}.")
        return DownloadResult(0, 0, [])
    urls = [(image, os.path.join(destination, folder)) for image, folder in pages]
    result = await download_all_pages(
        urls,
        max_workers=workers,
        manga_name=title,
        max_retries=max_retries,
        referer=referer,
        source_type=source,
        source_url=url,
        source_id=source_id,
        language=language,
        output_path=destination,
        optimize_mode=optimize_mode,
        skip_archived=output_format == "cbz",
    )
    output = None
    if output_format and result.complete and not stop_signal:
        output = await asyncio.to_thread(
            _create_selected_output,
            destination,
            output_format,
            **_cbz_options(source, title, url, language, cbz_layout, reading_direction),
        )
    if CLEAN_OUTPUT:
        print_clean_summary(
            title, len(result.completed_folders), result.successful_pages, output
        )
    return result


async def _update_tracked_title(
    item,
    *,
    workers,
    start_page,
    max_pages,
    max_retries,
    output_format,
    cbz_layout,
    reading_direction,
    metadata_language,
    optimize_mode,
):
    title = str(item["manga_name"])
    source = str(item.get("source_type") or "generic")
    source_url = item.get("source_url")
    destination = item.get("output_path")
    start_chapter = _calculate_resume_chapter(float(item["latest_chapter_local"]))
    if source != "generic":
        start_chapter = max(0, int(float(item["latest_chapter_local"])))
    if not CLEAN_OUTPUT:
        console.print(f"Checking '{title}' via {source} from chapter {start_chapter}")
    if source == "mangadex" and source_url:
        options = {
            "lang": str(item.get("language") or "en"),
            "create_cbz": bool(output_format),
            "max_workers": workers,
            "max_retries": max_retries,
            "start_chapter": start_chapter,
            "optimize_mode": optimize_mode,
            "output_path": destination,
            "cbz_layout": cbz_layout,
            "reading_direction": reading_direction,
            "metadata_language": metadata_language,
        }
        if output_format is not None:
            options["output_format"] = output_format
        return await download_md_chapters(str(source_url), **options)
    if source in ("weebcentral", "webtoons", "mangapill", "manganato") and source_url:
        return await _download_url_source(
            source,
            str(source_url),
            workers=workers,
            max_retries=max_retries,
            start_chapter=start_chapter,
            output_format=output_format,
            cbz_layout=cbz_layout,
            reading_direction=reading_direction,
            metadata_language=metadata_language or item.get("language"),
            optimize_mode=optimize_mode,
            output_path=destination,
            manga_name=title,
            source_id=item.get("source_id"),
        )
    if source != "generic":
        raise ValueError(
            f"Cannot update {title!r}: missing URL or unsupported source {source!r}."
        )
    slug, inferred_name = get_slug_and_pretty(title)
    destination = str(destination or inferred_name)
    urls = await gather_all_urls(
        slug,
        start_chapter=start_chapter,
        start_page=start_page,
        max_pages=max_pages,
        max_decimals=10,
        workers=workers,
        folder_base=destination,
    )
    if not urls:
        if not CLEAN_OUTPUT:
            console.print(f"No new pages for '{title}'.")
        return DownloadResult(0, 0, [])
    options = {"skip_archived": True} if output_format == "cbz" else {}
    result = await download_all_pages(
        urls,
        max_workers=workers,
        manga_name=title,
        max_retries=max_retries,
        source_type="generic",
        source_url=str(source_url) if source_url else None,
        source_id=str(item["source_id"]) if item.get("source_id") else None,
        output_path=destination,
        optimize_mode=optimize_mode,
        **options,
    )
    if output_format and result.complete and not stop_signal:
        await asyncio.to_thread(
            _create_selected_output,
            destination,
            output_format,
            **_cbz_options(
                source,
                title,
                source_url,
                metadata_language,
                cbz_layout,
                reading_direction,
            ),
        )
    return result


async def _auto_update_from_db(
    workers: int,
    start_page: int,
    max_pages: int,
    cbz_flag: bool,
    max_retries: int = 5,
    optimize_mode: str = "off",
    output_format: str | None = None,
    *,
    tracked: list[dict] | None = None,
    cbz_layout: str = "series",
    reading_direction: str = "auto",
    metadata_language: str | None = None,
) -> bool:
    """Check the entire library or an explicitly selected title; report partial failures."""
    tracked = get_tracked_manga() if tracked is None else tracked
    if not tracked:
        console.print("No tracked manga found in database.")
        return True
    if output_format is None and cbz_flag:
        output_format = "cbz"
    checked = failed = 0
    for item in tracked:
        if stop_signal:
            break
        checked += 1
        try:
            result = await _update_tracked_title(
                item,
                workers=workers,
                start_page=start_page,
                max_pages=max_pages,
                max_retries=max_retries,
                output_format=output_format,
                cbz_layout=cbz_layout,
                reading_direction=reading_direction,
                metadata_language=metadata_language,
                optimize_mode=optimize_mode,
            )
            if result is not None and not result.complete:
                failed += 1
                console.print(f"Incomplete download for '{item['manga_name']}'.")
            if item.get("id") is not None and not stop_signal:
                await asyncio.to_thread(mark_library_checked, item["id"])
        except (
            OSError,
            RuntimeError,
            ValueError,
            sqlite3.Error,
            zipfile.BadZipFile,
        ) as exc:
            failed += 1
            console.print(f"Could not update '{item['manga_name']}': {exc}")
    console.print(f"Library update: checked={checked}, failed={failed}")
    return failed == 0 and not stop_signal


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
        args.start_chapter
        if args.start_chapter is not None
        else config.get("start_chapter", 1)
    )
    start_page = args.start_page or config.get("start_page", 1)
    max_pages = args.max_pages or config.get("max_pages", 50)
    workers = args.workers or config.get("workers", 10)
    cbz_flag = args.cbz if args.cbz is not None else config.get("cbz", True)
    output_format = args.output_format or (
        config.get("output_format", "cbz") if cbz_flag else None
    )
    if args.output_format is None and args.cbz is not None:
        output_format = "cbz" if args.cbz else None
    cbz_layout = args.cbz_layout or config.get("cbz_layout", "series")
    reading_direction = args.reading_direction or config.get(
        "reading_direction", "auto"
    )
    metadata_language = args.metadata_language or config.get("metadata_language")
    md_lang = args.md_lang or config.get("md_language", "en")
    update_flag = args.update or (
        config.get("update", False) if args.command is None else False
    )
    auto_update_db_flag = args.auto_update_db
    dev_flag = args.dev
    clean_flag = args.clean_output or config.get("clean_output", False)
    credits_flag = args.credits
    max_retries = getattr(args, "max_retries", 5) or 5
    optimize_mode = getattr(args, "optimize_images", "off") or "off"
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

    update_options = {
        "workers": workers,
        "start_page": start_page,
        "max_pages": max_pages,
        "cbz_flag": bool(output_format),
        "max_retries": max_retries,
        "optimize_mode": optimize_mode,
        "output_format": output_format,
        "cbz_layout": cbz_layout,
        "reading_direction": reading_direction,
        "metadata_language": metadata_language,
    }
    if args.command == "library":
        try:
            if args.library_action == "list":
                await asyncio.to_thread(print_library, console)
            elif args.library_action == "status":
                await asyncio.to_thread(print_library_status, console, args.selector)
            else:
                entry = await asyncio.to_thread(get_library_entry, args.selector)
                if not await _auto_update_from_db(tracked=[entry], **update_options):
                    raise SystemExit(1)
        except ValueError as exc:
            console.print(str(exc))
            raise SystemExit(1) from exc
        return

    if args.download_history is not None:
        _print_download_history(args.download_history)
        return

    if args.verify:
        if not _print_verification(
            await asyncio.to_thread(verify_library, args.verify)
        ):
            raise SystemExit(1)
        return

    if args.repair:
        before, after = await repair_library(
            args.repair,
            workers=workers,
            max_retries=max_retries,
        )
        console.print(f"[cyan]Repair attempted for {len(before.issues)} issue(s).[/]")
        if not _print_verification(after):
            raise SystemExit(1)
        return

    if auto_update_db_flag:
        if not await _auto_update_from_db(**update_options):
            raise SystemExit(1)
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
            create_cbz=bool(output_format),
            output_format=output_format or "cbz",
            max_workers=workers,
            max_retries=max_retries,
            start_chapter=args.start_chapter if args.start_chapter is not None else 0,
            optimize_mode=optimize_mode,
            cbz_layout=cbz_layout,
            reading_direction=reading_direction,
            metadata_language=metadata_language,
        )
        return

    if source in ("weebcentral", "webtoons", "mangapill", "manganato"):
        try:
            await _download_url_source(
                source,
                str(manga_name),
                workers=workers,
                max_retries=max_retries,
                start_chapter=(
                    args.start_chapter if args.start_chapter is not None else 0
                ),
                output_format=output_format,
                cbz_layout=cbz_layout,
                reading_direction=reading_direction,
                metadata_language=metadata_language,
                optimize_mode=optimize_mode,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            console.print(f"Download failed: {exc}")
            raise SystemExit(1) from exc
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
            console.print(
                f"[yellow]No pages found for '{manga_name}' (slug: {slug}).[/]"
            )
        return

    download_result = await download_all_pages(
        urls_to_download,
        max_workers=workers,
        manga_name=pretty_name,
        max_retries=max_retries,
        source_type="generic",
        source_url=str(manga_name) if str(manga_name).startswith("http") else None,
        output_path=pretty_name,
        optimize_mode=optimize_mode,
        skip_archived=output_format == "cbz",
    )

    # ---- CBZ packaging ----
    cbz_created_path = None
    if output_format and not stop_signal and download_result.complete:
        if os.path.isdir(pretty_name):
            # Archive file operations are synchronous — run in a thread
            # so the event loop is not blocked during CBZ packaging.
            cbz_created_path = await asyncio.to_thread(
                _create_selected_output,
                pretty_name,
                output_format,
                **_cbz_options(
                    "generic",
                    pretty_name,
                    str(manga_name) if str(manga_name).startswith("http") else None,
                    metadata_language,
                    cbz_layout,
                    reading_direction,
                ),
            )
            if cbz_created_path and not CLEAN_OUTPUT:
                console.print(
                    f"[bold green]{output_format.upper()} created successfully:[/] "
                    f"[cyan]{cbz_created_path}[/]"
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
