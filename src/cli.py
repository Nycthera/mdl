"""CLI argument parsing and setup."""

import argparse

from src import __version__


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or MangaDex URL")
    parser.add_argument("--start-chapter", type=int)
    parser.add_argument("--start-page", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--workers", type=int)
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
