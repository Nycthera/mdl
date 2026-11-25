"""Download result types, scheduling helpers, and durable run history."""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aiohttp

from src.database.history import finish_download_run, record_page_results
from src.network.retry import get_host_cap
from src.network.urls import PublicAddressResolver
from src.utils import image_filename


def _download_failed(result: str) -> bool:
    """Return whether a download result represents a failed page."""
    lowered = result.lower()
    return (
        "failed to download" in lowered
        or "unexpected error" in lowered
        or "download interrupted" in lowered
        or "unsafe url" in lowered
        or "unsafe redirect" in lowered
    )


def _get_trackable_chapter_folders(
    urls_to_download: list[tuple[str, str]],
    page_results: dict[tuple[str, str], str],
) -> list[str]:
    """Return the fully completed contiguous chapter folders from the queue start."""
    expected_pages: dict[str, int] = defaultdict(int)
    successful_pages: dict[str, int] = defaultdict(int)
    folder_order: list[str] = []

    for item in urls_to_download:
        _, folder = item
        if folder not in expected_pages:
            folder_order.append(folder)
        expected_pages[folder] += 1
        result = page_results.get(item)
        if result is not None and not _download_failed(result):
            successful_pages[folder] += 1

    completed_folders: list[str] = []
    for folder in folder_order:
        if successful_pages[folder] != expected_pages[folder]:
            break
        completed_folders.append(folder)
    return completed_folders


def _build_connector(max_workers: int) -> aiohttp.TCPConnector:
    """Construct a tuned TCPConnector sized for the requested worker count.

    - limit = max_workers * 2 (ceiling 64 to avoid socket exhaustion)
    - limit_per_host = max_workers (so one host can't starve others)
    - keepalive enabled for 30s with a 5-minute DNS cache
    """
    limit = max(8, min(64, max_workers * 2))
    limit_per_host = max(1, min(limit, max_workers))
    return aiohttp.TCPConnector(
        limit=limit,
        limit_per_host=limit_per_host,
        keepalive_timeout=30,
        ttl_dns_cache=300,
        force_close=False,
        resolver=PublicAddressResolver(),
    )


@dataclass
class DownloadResult:
    successful_pages: int
    total_pages: int
    completed_folders: list[str]
    discovery_complete: bool = True

    @property
    def complete(self) -> bool:
        return self.discovery_complete and self.successful_pages == self.total_pages


class AdaptiveHostLimiter:
    """Async gate that enforces the live per-host AIMD concurrency cap."""

    def __init__(self, base_limit: int):
        self._base_limit = max(1, int(base_limit))
        self._active: dict[str, int] = defaultdict(int)
        self._condition = asyncio.Condition()
        self._caps = get_host_cap()

    @asynccontextmanager
    async def slot(self, url: str):
        host = self._caps.host_of(url)
        async with self._condition:
            while self._active[host] >= self._caps.effective(url, self._base_limit):
                await self._condition.wait()
            self._active[host] += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active[host] -= 1
                self._condition.notify_all()


def _history_status(result: str) -> str:
    lowered = result.lower()
    if "already downloaded" in lowered:
        return "existing"
    if "interrupted" in lowered:
        return "interrupted"
    if _download_failed(result):
        return "failed"
    return "saved"


async def _persist_run_history(
    run_id: int,
    page_results: dict[tuple[str, str], str],
    total_pages: int,
    *,
    interrupted: bool,
) -> None:
    """Persist collected page outcomes and close a durable run."""
    successful_pages = sum(
        not _download_failed(value) for value in page_results.values()
    )
    history_rows = [
        (
            url,
            folder,
            os.path.join(folder, image_filename(url)),
            _history_status(result),
            result,
        )
        for (url, folder), result in page_results.items()
    ]
    await asyncio.to_thread(record_page_results, run_id, history_rows)
    await asyncio.to_thread(
        finish_download_run,
        run_id,
        successful_pages=successful_pages,
        failed_pages=total_pages - successful_pages,
        interrupted=interrupted,
    )
