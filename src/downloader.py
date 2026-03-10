"""Image downloading functionality."""

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
    TimeRemainingColumn,
)

from src.utils import Colors, _loop_time, _cancel_pending_tasks

console = Console()

# Global state for interruption handling
stop_signal = False
CLEAN_OUTPUT = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def set_stop_signal(value: bool) -> None:
    """Set the stop signal globally."""
    global stop_signal
    stop_signal = value


async def url_exists(session: aiohttp.ClientSession, url: str) -> bool:
    """Check if a URL exists with a HEAD request."""
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as response:
            return response.status == 200
    except Exception:
        return False


async def download_image(
    url: str,
    folder: str,
    session: aiohttp.ClientSession,
    max_retries: int = 5,
    backoff_factor: float = 1.0,
) -> str:
    """Download a single image with retry logic."""
    if stop_signal:
        return f"{Colors.RED}Download interrupted{Colors.RESET}"
    
    os.makedirs(folder, exist_ok=True)
    filename = os.path.basename(url)
    filepath = os.path.join(folder, filename)
    
    if os.path.exists(filepath):
        return f"{Colors.YELLOW}Already downloaded: {filename}{Colors.RESET}"

    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                r.raise_for_status()
                content = await r.read()
                with open(filepath, "wb") as f:
                    f.write(content)
            return f"{Colors.GREEN}Saved as {filepath}{Colors.RESET}"
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == max_retries:
                return f"{Colors.RED}Failed to download {filename} after {max_retries} attempts: {e}{Colors.RESET}"
            await asyncio.sleep(backoff_factor * attempt)
        except Exception as e:
            return f"{Colors.RED}Unexpected error for {filename}: {e}{Colors.RESET}"


async def download_all_pages(
    urls_to_download: List[Tuple[str, str]],
    max_workers: int = 10,
    manga_name: str = "manga",
) -> None:
    """Download all pages with progress tracking."""
    total_pages = len(urls_to_download)
    if total_pages == 0:
        return

    for _, folder in urls_to_download:
        os.makedirs(folder, exist_ok=True)

    connector = aiohttp.TCPConnector(
        limit=max_workers * 2, limit_per_host=max_workers
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(max(1, max_workers))

        async def download_worker(args: Tuple[str, str]) -> str:
            async with sem:
                url, folder = args
                return await download_image(url, folder, session=session)

        tasks = [
            asyncio.create_task(download_worker(item)) for item in urls_to_download
        ]

        if not CLEAN_OUTPUT:
            with Progress(
                SpinnerColumn(style="green"),
                TextColumn("[bold green]Downloading[/]"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                TextColumn("{task.fields[pages_per_sec]} pages/sec"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task(
                    "Downloading", total=total_pages, pages_per_sec="0.0"
                )

                start_time = _loop_time()
                completed = 0
                for future in asyncio.as_completed(tasks):
                    result = await future
                    completed += 1
                    if stop_signal:
                        await _cancel_pending_tasks(tasks)
                        break
                    elapsed = max(_loop_time() - start_time, 0.001)
                    pps = completed / elapsed
                    progress.update(task, advance=1, pages_per_sec=f"{pps:.2f}")
                    if "Failed" in result or "HTTP" in result:
                        console.print(result)
        else:
            for future in asyncio.as_completed(tasks):
                await future
                if stop_signal:
                    await _cancel_pending_tasks(tasks)
                    break
