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


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or MangaDex URL")
    parser.add_argument("--start-chapter", type=int)
    parser.add_argument("--start-page", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument(
        "--workers",
        type=_workers_type,
        help="Concurrent downloads (1-100). Higher = faster but more likely to trip rate limits.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Max retry attempts per failed image (default: 5). Uses classified "
        "backoff: 429 backs off 3-12s, 5xx uses exponential, 4xx fails fast.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds (default: 30). "
        "Applies to connect + read; image downloads cap at this total.",
    )
    parser.add_argument("--cbz", action="store_true")
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Minimal output: no banner, no progress bars",
    )
    parser.add_argument(
        "--md-lang", default=None, help="Language code for MangaDex download"
    )
    parser.add_argument(
        "--credits",
        action="store_true",
        help="Show credits and exit",
    )
    parser.add_argument("--update", action="store_true", help="Update the application")
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
