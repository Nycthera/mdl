"""Shared request and chapter-discovery helpers for the HTML sources."""

import asyncio
import re

import aiohttp

from src.http import (
    classify_failure,
    compute_backoff,
    get_default_timeout,
    redirect_target,
)
from src.utils import _cancel_pending_tasks


async def fetch_html(session, url: str, *, max_retries: int = 5) -> str:
    for attempt in range(1, max_retries + 1):
        try:
            current_url = url
            for _ in range(5):
                async with session.get(
                    current_url, timeout=get_default_timeout(), allow_redirects=False
                ) as response:
                    if response.status not in {301, 302, 303, 307, 308}:
                        break
                    current_url = redirect_target(
                        current_url, response.headers.get("Location")
                    )
            else:
                raise RuntimeError(f"Too many redirects fetching {url}")
            if response.status >= 400:
                body = (
                    await response.content.read(4096)
                    if response.status in (403, 503)
                    else b""
                )
                failure = classify_failure(response.status, body_snippet=body)
                if failure == "permanent" or attempt == max_retries:
                    raise RuntimeError(f"HTTP {response.status} fetching {current_url}")
                await asyncio.sleep(compute_backoff(failure, attempt))
                continue
            return await response.text()
        except ValueError as exc:
            raise RuntimeError(f"Unsafe URL fetching {url}: {exc}") from exc
        except (TimeoutError, aiohttp.ClientError) as exc:
            failure = classify_failure(None, exc=exc)
            if failure == "permanent" or attempt == max_retries:
                raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc
            await asyncio.sleep(compute_backoff(failure, attempt))
    raise RuntimeError(f"Failed to fetch {url}")


async def collect_chapters(
    chapters, *, workers, read_images, folder_name, stopped, start_chapter=0
):
    """Preserve chapter order and fail discovery rather than silently skipping gaps."""
    semaphore = asyncio.Semaphore(max(1, workers))

    async def fetch_one(index, url, label):
        async with semaphore:
            if stopped():
                return []
            images = await read_images(url)
            if not images:
                raise RuntimeError(f"No images found for chapter {label!r} ({url})")
            folder = folder_name(label, url, index)
            return [(image, folder) for image in images]

    tasks = []
    for index, (url, label) in enumerate(chapters, 1):
        match = re.search(r"chapter[\s_-]*(\d+(?:\.\d+)?)", f"{label} {url}", re.I)
        number = float(match.group(1)) if match else None
        if number is not None and number < start_chapter:
            continue
        tasks.append(asyncio.create_task(fetch_one(index, url, label)))
    try:
        pages = await asyncio.gather(*tasks)
        return [] if stopped() else [page for chapter in pages for page in chapter]
    finally:
        await _cancel_pending_tasks(tasks)
