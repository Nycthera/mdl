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


def _download_options(parser, *, suppress_defaults=False):
    """Allow the same download settings before or after library subcommands."""

    def default(value=None):
        return argparse.SUPPRESS if suppress_defaults else value

    parser.add_argument(
        "--workers",
        type=_workers_type,
        default=default(),
        help="Concurrent downloads (1-100). Higher = faster but more likely to trip rate limits.",
    )
    parser.add_argument(
        "--max-retries",
        type=_positive_int,
        default=default(5),
        help="Max retry attempts per failed image (default: 5). Uses classified "
        "backoff: 429 backs off 3-12s, 5xx uses exponential, 4xx fails fast.",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        default=default(30),
        help="Per-request timeout in seconds (default: 30). "
        "Applies to connect + read; image downloads cap at this total.",
    )
    parser.add_argument(
        "--cbz", action=argparse.BooleanOptionalAction, default=default()
    )
    parser.add_argument(
        "--output-format",
        choices=("cbz", "epub", "pdf"),
        default=default(),
        help="Package downloaded pages as cbz (default), epub, or pdf.",
    )
    parser.add_argument(
        "--cbz-layout",
        choices=("series", "chapter"),
        default=default(),
        help="One combined book per series (default), or a separate CBZ per chapter.",
    )
    parser.add_argument(
        "--metadata-language",
        default=default(),
        metavar="CODE",
        help="Override the language stored in CBZ metadata (e.g. en, ja).",
    )
    parser.add_argument(
        "--reading-direction",
        choices=("auto", "rtl", "ltr"),
        default=default(),
        help="CBZ reading direction; auto uses ltr for Webtoons and rtl for manga.",
    )
    parser.add_argument(
        "--optimize-images",
        nargs="?",
        const="balanced",
        default=default("off"),
        choices=("off", "lossless", "balanced", "small"),
        metavar="MODE",
        help="Optimize pages as they download: lossless, balanced (default when set), "
        "small, or off. Runs alongside downloads before CBZ creation.",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        default=default(False),
        help="Minimal output: no banner, no progress bars",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        default=default(False),
        help="Enable developer debug logs",
    )


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or supported source URL")
    parser.add_argument("--start-chapter", type=_chapter_type)
    parser.add_argument("--start-page", type=_positive_int)
    parser.add_argument("--max-pages", type=_positive_int)
    _download_options(parser)
    parser.add_argument(
        "--md-lang", default=None, help="Language code for MangaDex download"
    )
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
        "--download-history",
        nargs="?",
        const="",
        metavar="TITLE",
        help="Show recent download runs, optionally filtered by manga title",
    )
    integrity = parser.add_mutually_exclusive_group()
    integrity.add_argument(
        "--verify",
        metavar="PATH",
        help="Check downloaded images and report missing or corrupt pages",
    )
    integrity.add_argument(
        "--repair",
        metavar="PATH",
        help="Verify and redownload damaged pages using stored page history",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    library = commands.add_parser(
        "library", help="List, inspect, or update tracked titles"
    )
    actions = library.add_subparsers(dest="library_action", required=True)
    listing = actions.add_parser(
        "list", help="List tracked titles and their last recorded run"
    )
    status = actions.add_parser(
        "status", help="Inspect a title's saved status and location"
    )
    update = actions.add_parser("update", help="Check and update one tracked title")
    _download_options(update, suppress_defaults=True)
    for command in (listing, status):
        command.add_argument(
            "--clean-output",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Hide the application banner",
        )
        command.add_argument(
            "--dev",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Enable developer debug logs",
        )
    for command in (status, update):
        command.add_argument(
            "selector", metavar="TITLE_OR_ID", help="Exact title or id:NUMBER"
        )
    args = parser.parse_args()
    if args.command == "library" and (
        args.manga
        or args.auto_update_db
        or args.update
        or args.download_history is not None
        or args.verify
        or args.repair
        or args.credits
    ):
        parser.error("library commands cannot be combined with another action")
    return args
