#!/usr/bin/env python3
"""Recursively remove generated Python tool cache directories.

By default, the script cleans the project root. Pass another directory to
clean a different tree, or use ``--dry-run`` to preview what would be removed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_DIRECTORIES = {".git", ".hg", ".svn", ".tox", ".venv", "env", "venv"}


def find_cache_directories(root: Path) -> list[Path]:
    """Return project caches without traversing environments or VCS metadata."""
    if root.name in CACHE_DIRECTORY_NAMES and root.is_dir():
        return [root]

    matches: list[Path] = []
    for current, directories, _ in os.walk(root):
        current_path = Path(current)
        matches.extend(current_path / name for name in directories if name in CACHE_DIRECTORY_NAMES)
        directories[:] = [
            name
            for name in directories
            if name not in CACHE_DIRECTORY_NAMES and name not in EXCLUDED_DIRECTORIES
        ]
    return sorted(matches, key=lambda path: (len(path.parts), str(path)), reverse=True)


def clean_caches(root: Path, *, dry_run: bool = False) -> int:
    """Remove cache directories below *root* and return the number found."""
    directories = find_cache_directories(root)
    for directory in directories:
        relative_path = directory.relative_to(root) if directory != root else Path(".")
        prefix = "Would remove" if dry_run else "Removed"
        if not dry_run:
            shutil.rmtree(directory)
        print(f"{prefix}: {relative_path}")
    return len(directories)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT,
        help="directory to clean (default: project root)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show cache directories without deleting them",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        print(f"Error: not a directory: {root}", file=sys.stderr)
        return 2

    count = clean_caches(root, dry_run=args.dry_run)
    action = "found" if args.dry_run else "removed"
    noun = "directory" if count == 1 else "directories"
    print(f"{count} cache {noun} {action}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
