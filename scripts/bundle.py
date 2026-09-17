#!/usr/bin/env python3
"""Bundle the mdl project into a single self-contained .py file.

Reads every source module in topological dependency order, strips internal
`from src.* import ...` lines (the names are already in scope because every
module's top-level names are now in the same module namespace), and writes
the result to `mdl_single.py`.

Usage:
    python3 scripts/bundle.py [--output PATH] [--source-dir PATH]

Defaults:
    --source-dir   .                 (the repo root)
    --output       ./mdl_single.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Source files in topological dependency order.
#
# A file must appear BEFORE any file that imports from it. External deps
# (aiohttp, rich, playwright, etc.) are NOT bundled — they're expected to be
# installed from the project's locked uv environment.
# ---------------------------------------------------------------------------
SOURCE_FILES: list[str] = [
    # Foundation — no internal deps
    "src/__init__.py",  # __version__, __author__, __license__
    "src/utils.py",  # Colors, cprint, sanitize_folder_name, ...
    # Depends on utils
    "src/config.py",  # load_config, save_config, get_config_path
    "src/rate_limiter.py",  # RateLimiter, rate_limiter, rate_limiter_athome
    # Depends on utils (standalone HTTP infra)
    "src/http.py",  # build_session, classify_failure, HostConcurrencyCap, ...
    # Depends on config
    "src/database/manga_db.py",  # record_download, record_download_from_folders, ...
    # Depends on utils
    "src/cbz.py",  # create_cbz_for_all, set_clean_output
    # Depends on database.manga_db, http, utils
    "src/downloader.py",  # download_image, download_all_pages, url_exists
    # Depends on downloader
    "src/scrapers/__init__.py",  # _collect_existing_urls, _build_chapter_urls, ...
    # Depends on scrapers, utils, downloader
    "src/scrapers/generic.py",  # gather_all_urls, BASE_URLS
    # Depends on downloader, cbz, database, http, rate_limiter, utils
    "src/scrapers/mangadex.py",  # download_md_chapters, fetch_all_chapters_md, ...
    # No internal deps (uses Playwright + rich)
    "src/scrapers/weebcentral.py",
    "src/scrapers/webtoons.py",
    # Depends on rich (fallback to plain)
    "src/system_utils.py",  # update, credits
    # Depends on cli (which depends on src.__init__)
    "src/cli.py",  # parse_args
    # Main entry point — depends on everything
    "main.py",
]


# Regex: matches `from src... import ...` (single-line form).
# We also detect the multi-line `from src... import (\n ...\n)` form separately.
_INTERNAL_IMPORT_RE = re.compile(
    r"""^\s*from\s+src(\.[\w_]+)*\s+import\s+""",
    re.MULTILINE,
)

# Regex: matches `import src...` (rare, but handle it).
_INTERNAL_IMPORT_BARE_RE = re.compile(
    r"""^\s*import\s+src(\.[\w_]+)*\s*$""",
    re.MULTILINE,
)

# Regex: matches `from __future__ import ...` — these MUST appear before any
# other code in a Python file, so we hoist them to the top of the bundle.
_FUTURE_IMPORT_RE = re.compile(
    r"""^\s*from\s+__future__\s+import\s+(.+?)\s*$""",
    re.MULTILINE,
)


def strip_internal_imports(source: str) -> tuple[str, list[str]]:
    """Remove `from src.* import ...` and `import src.*` lines.

    Returns (cleaned_source, future_imports) where future_imports is the list
    of `from __future__ import X` statements found (to be hoisted to the top
    of the bundle — Python requires __future__ imports to come first).
    """
    # Extract __future__ imports first (they must be hoisted).
    future_imports: list[str] = []
    for m in _FUTURE_IMPORT_RE.finditer(source):
        future_imports.append(m.group(0).strip())
    source = _FUTURE_IMPORT_RE.sub("", source)

    lines = source.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Single-line: `from src.X import Y` or `from src.X import Y as Z`
        if _INTERNAL_IMPORT_RE.match(line) and "(" not in line:
            i += 1
            continue
        # Multi-line: `from src.X import (\n  Y,\n  Z,\n)`
        if _INTERNAL_IMPORT_RE.match(line) and "(" in line:
            # Skip until the closing `)`.
            while i < len(lines) and ")" not in lines[i]:
                i += 1
            i += 1  # skip the closing `)` line
            continue
        # Bare: `import src` or `import src.X`
        if _INTERNAL_IMPORT_BARE_RE.match(line):
            i += 1
            continue
        out.append(line)
        i += 1
    return "".join(out), future_imports


def extract_main_block(source: str) -> tuple[str, str]:
    """Split main.py into (body, main_block).

    The main_block is the `if __name__ == "__main__":` tail — we pull it out
    so we can append it at the very end of the bundled file (after all module
    code has been defined, so all the names it references exist).
    """
    # Match the `if __name__ == "__main__":` block at column 0.
    m = re.search(r'\nif __name__ == "__main__":', source)
    if not m:
        return source, ""
    body = source[: m.start()] + "\n"
    main_block = source[m.start() :]
    return body, main_block


def read_source_file(path: Path) -> str:
    """Read a source file, skipping its module docstring to avoid duplicate triple-quotes."""
    text = path.read_text(encoding="utf-8")
    # Strip a leading module docstring (the """...""" at the very start of the file).
    # We keep `# -*- coding ... -*-` and shebangs if present (none in this codebase).
    m = re.match(r'^\s*"""[^"]*"""\s*\n', text)
    if m:
        text = text[m.end() :]
    return text


def bundle(source_dir: Path, output: Path) -> None:
    """Produce the single-file bundle at `output`."""
    parts: list[str] = []
    future_imports: list[str] = []

    # Shebang + header.
    parts.append("#!/usr/bin/env python3\n")
    parts.append(
        '"""mdl — single-file bundle.\n\n'
        "Auto-generated by scripts/bundle.py. Do not edit by hand.\n"
        "All source modules have been concatenated in topological order;\n"
        "internal `from src.* import ...` lines have been stripped because\n"
        "every top-level name is now in the same module namespace.\n\n"
        "External dependencies (install with `uv sync --locked`):\n"
        "    aiohttp, rich, playwright, playwright-stealth\n"
        '"""\n\n'
    )

    main_block = ""

    for rel in SOURCE_FILES:
        path = source_dir / rel
        if not path.exists():
            print(f"WARNING: {path} not found, skipping.", file=sys.stderr)
            continue
        text = read_source_file(path)
        text, futures = strip_internal_imports(text)
        future_imports.extend(futures)

        if rel == "main.py":
            text, main_block = extract_main_block(text)

        parts.append(f"# {'=' * 70}\n")
        parts.append(f"# BEGIN {rel}\n")
        parts.append(f"# {'=' * 70}\n")
        parts.append(text)
        parts.append("\n")

    # Build the final file: shebang + docstring + __future__ imports + body + main block.
    header = parts[:2]  # shebang + docstring

    # Deduplicate __future__ imports while preserving order.
    seen_futures: set[str] = set()
    unique_futures: list[str] = []
    for f in future_imports:
        if f not in seen_futures:
            seen_futures.add(f)
            unique_futures.append(f)

    body_parts = parts[2:]  # everything after the header

    final: list[str] = []
    final.extend(header)
    if unique_futures:
        final.append("\n".join(unique_futures) + "\n\n")
    final.extend(body_parts)

    # Append the `if __name__ == "__main__":` block at the very end so all
    # top-level names (main, parse_args, console, etc.) are defined first.
    if main_block:
        final.append("# " + "=" * 70 + "\n")
        final.append("# ENTRY POINT (from main.py)\n")
        final.append("# " + "=" * 70 + "\n")
        final.append(main_block)
        final.append("\n")

    output.write_text("".join(final), encoding="utf-8")
    output.chmod(0o755)
    print(f"Bundle written: {output} ({output.stat().st_size:,} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bundle mdl into a single .py file.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to the mdl repo root (default: parent of this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: <source-dir>/mdl_single.py).",
    )
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    if not (source_dir / "main.py").exists():
        print(f"ERROR: {source_dir} does not look like the mdl repo (no main.py).", file=sys.stderr)
        return 1

    output = args.output or (source_dir / "mdl_single.py")
    bundle(source_dir, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
