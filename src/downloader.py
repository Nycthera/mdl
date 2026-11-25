"""Compatibility facade for the focused ``src.downloads`` package."""
# ruff: noqa: F401

from src.downloads import batch as _batch
from src.downloads import single as _single
from src.downloads.batch import (
    AdaptiveHostLimiter,
    DownloadResult,
    _build_connector,
    _download_failed,
    _get_trackable_chapter_folders,
    _persist_run_history,
)
from src.downloads.single import url_exists
from src.downloads.support import _history_status

stop_signal = False
CLEAN_OUTPUT = False
DEV_MODE = False


def set_clean_output(value: bool) -> None:
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value
    from src.downloads import batch

    batch.CLEAN_OUTPUT = value


def set_dev_mode(value: bool) -> None:
    global DEV_MODE
    DEV_MODE = value
    from src.downloads import batch

    batch.DEV_MODE = value


def set_stop_signal(value: bool) -> None:
    global stop_signal
    stop_signal = value
    from src.downloads import batch

    batch.stop_signal = value
    from src.downloads.single import set_stop_signal as set_single_stop_signal

    set_single_stop_signal(value)


def _is_stopped() -> bool:
    return stop_signal


async def download_image(*args, **kwargs):
    """Forward to the focused implementation using legacy module state."""
    _single.stop_signal = stop_signal
    return await _single.download_image(*args, **kwargs)


async def download_all_pages(*args, **kwargs):
    """Forward to the batch scheduler using legacy module state."""
    _batch.stop_signal = stop_signal
    _batch.CLEAN_OUTPUT = CLEAN_OUTPUT
    _batch.DEV_MODE = DEV_MODE
    _single.stop_signal = stop_signal
    return await _batch.download_all_pages(*args, **kwargs)
