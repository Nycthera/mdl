"""CLI argument parsing and setup."""

import argparse

from src import __version__


def _workers_type(value: str) -> int:
    """Validate --workers as an int in [1, 100]."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"must be an integer, got {value!r}")
    if v < 1 or v > 100:
        raise argparse.ArgumentTypeError(f"must be between 1 and 100, got {v}")
    return v


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _chapter_type(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return number


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or MangaDex URL")
    parser.add_argument("--start-chapter", type=_chapter_type)
    parser.add_argument("--start-page", type=_positive_int)
    parser.add_argument("--max-pages", type=_positive_int)
    parser.add_argument(
        "--workers",
        type=_workers_type,
        help="Concurrent downloads (1-100). Higher = faster but more likely to trip rate limits.",
    )
    parser.add_argument(
        "--max-retries",
        type=_positive_int,
        default=5,
        help="Max retry attempts per failed image (default: 5). Uses classified "
        "backoff: 429 backs off 3-12s, 5xx uses exponential, 4xx fails fast.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        default=30,
        help="Per-request timeout in seconds (default: 30). "
        "Applies to connect + read; image downloads cap at this total.",
    )
    parser.add_argument("--cbz", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Minimal output: no banner, no progress bars",
    )
    parser.add_argument("--md-lang", default=None, help="Language code for MangaDex download")
    parser.add_argument(
        "--credits",
        action="store_true",
        help="Show credits and exit",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Synchronize the locked project dependencies with uv",
    )
    parser.add_argument(
        "--auto-update-db",
        action="store_true",
        help="Check all tracked manga in the database and download new chapters",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable developer debug logs",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()
