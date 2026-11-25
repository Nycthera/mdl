"""SQLite connection, identity, and record-writing primitives."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from math import isfinite
from urllib.parse import urlsplit, urlunsplit

from rich.console import Console

from src.config import get_config_path


def _resolve_db_path(db_path: str) -> str:
    """Expand user and environment markers in database paths."""
    expanded = os.path.expandvars(os.path.expanduser(db_path))
    return os.path.abspath(expanded)


DEFAULT_DB_PATH = _resolve_db_path(
    os.environ.get(
        "MANGA_DB_PATH",
        os.path.join(os.path.dirname(get_config_path()), "manga_collection.db"),
    )
)
LEGACY_DB_PATH = _resolve_db_path(os.path.join(os.path.dirname(__file__), "manga_collection.db"))

SCHEMA_VERSION = 4
BUSY_TIMEOUT_MS = 10_000


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manga_data (
    id INTEGER PRIMARY KEY,
    manga_name TEXT NOT NULL COLLATE NOCASE,
    date_last_checked INTEGER NOT NULL CHECK (date_last_checked >= 0),
    latest_chapter_local REAL NOT NULL CHECK (latest_chapter_local >= 0),
    latest_chapter_from_mangadex REAL NOT NULL
        CHECK (latest_chapter_from_mangadex >= 0),
    source_type TEXT NOT NULL COLLATE NOCASE DEFAULT 'generic',
    source_key TEXT NOT NULL COLLATE NOCASE,
    source_url TEXT,
    source_id TEXT,
    language TEXT,
    output_path TEXT,
    cbz_hash TEXT,
    UNIQUE (source_type, source_key)
)
"""

HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS download_runs (
    id INTEGER PRIMARY KEY,
    manga_id INTEGER NOT NULL REFERENCES manga_data(id) ON DELETE CASCADE,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'partial', 'interrupted')),
    total_pages INTEGER NOT NULL CHECK (total_pages >= 0),
    successful_pages INTEGER NOT NULL DEFAULT 0 CHECK (successful_pages >= 0),
    failed_pages INTEGER NOT NULL DEFAULT 0 CHECK (failed_pages >= 0)
);

CREATE TABLE IF NOT EXISTS page_downloads (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES download_runs(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    folder TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('saved', 'existing', 'failed', 'interrupted')),
    message TEXT,
    recorded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_runs_manga_started
    ON download_runs(manga_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_downloads_file
    ON page_downloads(file_path, id DESC);
CREATE INDEX IF NOT EXISTS idx_page_downloads_run_status
    ON page_downloads(run_id, status);
"""


console = Console()


def set_clean_output(value: bool) -> None:
    """Set clean output mode for DB logging."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def set_dev_mode(value: bool) -> None:
    """Enable or disable developer debug logging."""
    global DEV_MODE
    DEV_MODE = value


CLEAN_OUTPUT = False
DEV_MODE = False


def _db_log(message: str) -> None:
    """Print database logs unless disabled."""
    env_override = os.environ.get("MANGA_DB_VERBOSE")
    force_verbose = env_override == "1"
    force_silent = env_override == "0"
    should_log = (DEV_MODE or force_verbose) and not force_silent
    if should_log and not CLEAN_OUTPUT:
        console.print(f"[bold blue][db][/bold blue] {message}")


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection configured for safe concurrent CLI operations."""
    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers continue while a download completion is being saved.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        connection.close()
        raise
    return connection


@contextmanager
def _database(db_path: str) -> Iterator[sqlite3.Connection]:
    """Yield a transactional connection and always close it afterwards."""
    connection = _connect(db_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _normalize_chapter(value: float, field_name: str) -> float:
    """Validate a chapter value before persisting it."""
    chapter = float(value)
    if not isfinite(chapter):
        raise ValueError(f"{field_name} must be a finite number")
    return max(0.0, chapter)


def _parse_chapter_number(value: str | int | float | None) -> float | None:
    """Extract a chapter number from mixed chapter labels."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    # Prioritize chapter labels like "chapter_0012.5" and avoid unrelated digits
    # from parent folder names such as manga titles (e.g. "86").
    base_name = os.path.basename(text).lower()
    chapter_match = re.search(r"chapter[_\-\s]*([0-9]+(?:\.[0-9]+)?)", base_name)
    if chapter_match:
        try:
            return float(chapter_match.group(1))
        except ValueError:
            return None

    match = re.search(r"(\d+(?:\.\d+)?)", base_name)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def _canonical_url(url: str | None) -> str | None:
    """Normalize a source URL for stable database identity."""
    if not url:
        return None
    text = url.strip()
    if not text:
        return None
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _make_source_key(
    manga_name: str,
    source_type: str,
    source_url: str | None,
    source_id: str | None,
) -> str:
    """Build a stable source-specific identity for a tracked title."""
    if source_id and source_id.strip():
        return source_id.strip()
    canonical_url = _canonical_url(source_url)
    if canonical_url:
        return canonical_url
    return manga_name.strip().casefold()


def _upsert_manga(
    cursor: sqlite3.Cursor,
    *,
    manga_name: str,
    checked_at: int,
    latest_local: float,
    latest_source: float,
    source_type: str,
    source_key: str,
    source_url: str | None,
    source_id: str | None,
    language: str | None,
    output_path: str | None,
    cbz_hash: str | None = None,
) -> int:
    """Insert/update a source-specific title and return its row id."""
    row = cursor.execute(
        """
        INSERT INTO manga_data (
            manga_name, date_last_checked, latest_chapter_local,
            latest_chapter_from_mangadex, source_type, source_key,
            source_url, source_id, language, output_path, cbz_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_type, source_key) DO UPDATE SET
            manga_name = excluded.manga_name,
            date_last_checked = MAX(manga_data.date_last_checked, excluded.date_last_checked),
            latest_chapter_local = MAX(manga_data.latest_chapter_local, excluded.latest_chapter_local),
            latest_chapter_from_mangadex = MAX(
                manga_data.latest_chapter_from_mangadex,
                excluded.latest_chapter_from_mangadex
            ),
            source_url = COALESCE(excluded.source_url, manga_data.source_url),
            source_id = COALESCE(excluded.source_id, manga_data.source_id),
            language = COALESCE(excluded.language, manga_data.language),
            output_path = COALESCE(excluded.output_path, manga_data.output_path),
            cbz_hash = COALESCE(excluded.cbz_hash, manga_data.cbz_hash)
        RETURNING id
        """,
        (
            manga_name,
            checked_at,
            latest_local,
            latest_source,
            source_type,
            source_key,
            source_url,
            source_id,
            language,
            output_path,
            cbz_hash,
        ),
    ).fetchone()
    return int(row[0])
