#!/usr/bin/env python3
"""Clean common generated artifacts and trailing whitespace in a codebase.

Usage:
        python clean_code.py [PATH]          # preview changes
        python clean_code.py [PATH] --apply  # apply changes
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
}

GENERATED_DIRECTORIES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "htmlcov",
}

GENERATED_FILES = {".coverage", ".DS_Store", "Thumbs.db"}

TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rst",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def iter_paths(root: Path):
    """Yield paths while preventing traversal into dependency directories."""
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if not any(part in SKIP_DIRECTORIES for part in relative_parts):
            yield path


def clean_codebase(root: Path, apply_changes: bool) -> tuple[int, int]:
    removed = fixed = 0
    paths = sorted(iter_paths(root), key=lambda path: len(path.parts), reverse=True)

    for path in paths:
        relative = path.relative_to(root)
        if path.is_dir() and path.name in GENERATED_DIRECTORIES:
            print(f"{'REMOVE' if apply_changes else 'WOULD REMOVE'} {relative}")
            if apply_changes:
                shutil.rmtree(path)
            removed += 1
            continue

        if path.is_file() and path.name in GENERATED_FILES:
            print(f"{'REMOVE' if apply_changes else 'WOULD REMOVE'} {relative}")
            if apply_changes:
                path.unlink()
            removed += 1
            continue

        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue

        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        cleaned = "\n".join(line.rstrip() for line in original.splitlines())
        if original.endswith(("\n", "\r")):
            cleaned += "\n"

        if cleaned != original:
            print(f"{'FIX' if apply_changes else 'WOULD FIX'} {relative}")
            if apply_changes:
                path.write_text(cleaned, encoding="utf-8")
            fixed += 1

    return removed, fixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="apply changes")
    args = parser.parse_args()

    root = args.path.resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    removed, fixed = clean_codebase(root, args.apply)
    action = "Cleaned" if args.apply else "Found"
    print(
        f"{action}: {removed} generated item(s), {fixed} file(s) with whitespace issues."
    )
    if not args.apply and (removed or fixed):
        print("Run with --apply to perform these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
