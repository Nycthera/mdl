"""Utility functions and helpers for the manga downloader."""

import asyncio
import pathlib
import re
import shutil
import sys
from urllib.parse import urlparse
from typing import Optional, Tuple
from rich.console import Console

console = Console()

# Legacy color support
class Colors:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"


def cprint(msg: str, color: str = Colors.RESET) -> None:
    """Print colored text (legacy support)."""
    print(color + msg + Colors.RESET)


def validate_manga_input(manga_name: Optional[str]) -> None:
    """Validate that a manga name or URL is provided."""
    if not manga_name:
        cprint(
            "Error: No manga name or URL specified. Use -M/--manga or set a default in config.",
            Colors.RED,
        )
        sys.exit(1)


def extract_manga_name_from_url(manga_input: str) -> str:
    """Extract manga name from a URL or return the input as-is."""
    if manga_input.startswith("http"):
        path = urlparse(manga_input).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            name = parts[1]
            return name.replace("-", " ")
        elif parts:
            name = parts[-1]
            return name.replace("-", " ")
        else:
            return manga_input
    return manga_input


def sanitize_folder_name(name: str) -> str:
    """Remove illegal characters from folder/file names."""
    # Replace illegal filesystem characters with underscore, but keep spaces
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    # Replace underscores/hyphens that were used as separators with spaces
    cleaned = cleaned.replace("_", " ")
    cleaned = cleaned.replace("-", " ")
    # Collapse multiple spaces into one and trim
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def get_slug_and_pretty(manga_input: str) -> Tuple[str, str]:
    """Return (slug_for_urls, pretty_folder_name).

    - slug_for_urls: hyphen-separated string suitable for building URLs
    - pretty_folder_name: sanitized name with spaces for folders/CBZ
    """
    if manga_input.startswith("http"):
        path = urlparse(manga_input).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            slug = parts[1]
        elif parts:
            slug = parts[-1]
        else:
            slug = manga_input
    else:
        slug = manga_input

    # Normalize slug: replace whitespace with single hyphen and collapse multiples
    slug = re.sub(r"\s+", "-", slug).strip("-")
    # Create a pretty folder name (spaces instead of hyphens)
    pretty = sanitize_folder_name(slug.replace("-", " "))
    return slug, pretty


def _loop_time() -> float:
    """Return the current event-loop time for consistent async timing."""
    return asyncio.get_running_loop().time()


async def _cancel_pending_tasks(tasks: list) -> None:
    """Cancel pending tasks and swallow cancellation exceptions."""
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def safe_delete_folder(folder_path: str) -> None:
    """Safely delete a folder and all its contents."""
    try:
        folder = pathlib.Path(folder_path)
        for item in folder.rglob("*"):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                console.print(f"[yellow]Warning: could not delete {item}: {e}[/]")
        # Try removing the root folder at the end
        if folder.exists():
            folder.rmdir()
        console.print(f"[green]Deleted folder {folder_path} after CBZ creation[/]")
    except Exception as e:
        console.print(f"[red]Failed to delete {folder_path}: {e}[/]")
