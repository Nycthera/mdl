"""SQLite tracking for downloaded manga metadata."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from typing import Iterable

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
LEGACY_DB_PATH = _resolve_db_path(
    os.path.join(os.path.dirname(__file__), "manga_collection.db")
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS manga_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manga_name TEXT NOT NULL UNIQUE,
    date_last_checked NUMERIC NOT NULL,
    latest_chapter_local NUMERIC NOT NULL,
    latest_chapter_from_mangadex NUMERIC NOT NULL
)
"""

console = Console()
CLEAN_OUTPUT = False
DEV_MODE = False


def set_clean_output(value: bool) -> None:
    """Set clean output mode for DB logging."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def set_dev_mode(value: bool) -> None:
    """Enable or disable developer debug logging."""
    global DEV_MODE
    DEV_MODE = value


def _db_log(message: str) -> None:
    """Print database logs unless disabled."""
    env_override = os.environ.get("MANGA_DB_VERBOSE")
    force_verbose = env_override == "1"
    force_silent = env_override == "0"
    should_log = (DEV_MODE or force_verbose) and not force_silent
    if should_log and not CLEAN_OUTPUT:
        console.print(f"[bold blue][db][/bold blue] {message}")


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


def infer_latest_chapter_from_folders(folders: Iterable[str]) -> float:
    """Infer latest chapter number from downloaded chapter folder paths."""
    latest = 0.0
    for folder in folders:
        chapter_val = _parse_chapter_number(folder)
        if chapter_val is not None and chapter_val > latest:
            latest = chapter_val
    return latest


def has_new_mangadex_release(
    latest_chapter_local: str | int | float | None,
    latest_chapter_from_mangadex: str | int | float | None,
) -> bool:
    """Return True when MangaDex reports a chapter newer than local data."""
    local_value = _parse_chapter_number(latest_chapter_local)
    source_value = _parse_chapter_number(latest_chapter_from_mangadex)

    if source_value is None:
        return False
    if local_value is None:
        local_value = 0.0
    return source_value > local_value


def _has_unique_index(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    """Return whether a table has a unique index for the given column."""
    cursor.execute(f"PRAGMA index_list({table_name})")
    for _, index_name, is_unique, *_ in cursor.fetchall():
        if not is_unique:
            continue
        cursor.execute(f"PRAGMA index_info({index_name})")
        indexed_columns = [row[2] for row in cursor.fetchall()]
        if indexed_columns == [column_name]:
            return True
    return False


def _schema_needs_migration(cursor: sqlite3.Cursor) -> bool:
    """Return whether the manga_data table needs to be rebuilt."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga_data'")
    if cursor.fetchone() is None:
        return False

    cursor.execute("PRAGMA table_info(manga_data)")
    columns = {row[1] for row in cursor.fetchall()}
    if "date_last_checked" not in columns:
        return True
    return not _has_unique_index(cursor, "manga_data", "manga_name")


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """Rebuild the manga_data table with the current schema and dedupe rows."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA table_info(manga_data)")
    columns = {row[1] for row in cursor.fetchall()}
    date_column = "date_last_checked"
    if "date_last_checked" not in columns:
        date_column = "date_last_chcked"

    cursor.execute("ALTER TABLE manga_data RENAME TO manga_data_old")
    cursor.execute(SCHEMA_SQL)
    cursor.execute(
        f"""
        INSERT INTO manga_data (
            manga_name,
            date_last_checked,
            latest_chapter_local,
            latest_chapter_from_mangadex
        )
        SELECT
            manga_name,
            MAX(COALESCE({date_column}, 0)),
            MAX(COALESCE(latest_chapter_local, 0)),
            MAX(COALESCE(latest_chapter_from_mangadex, 0))
        FROM manga_data_old
        GROUP BY manga_name
        """
    )
    cursor.execute("DROP TABLE manga_data_old")
    connection.commit()


def ensure_schema(db_path: str = DEFAULT_DB_PATH) -> None:
    """Ensure the manga tracking table exists."""
    db_path = _resolve_db_path(db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # One-time migration for users who previously stored their DB at the legacy
    # in-repo location.  Only migrate if the source DB actually contains rows
    # (skip empty/placeholder files shipped with the repo).
    if (
        db_path == DEFAULT_DB_PATH
        and not os.path.exists(db_path)
        and os.path.exists(LEGACY_DB_PATH)
        and os.path.abspath(LEGACY_DB_PATH) != os.path.abspath(db_path)
    ):
        # Only copy if the legacy DB has user data (non-empty table)
        try:
            with sqlite3.connect(LEGACY_DB_PATH) as _check_conn:
                check_cur = _check_conn.cursor()
                check_cur.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='manga_data'"
                )
                has_table = check_cur.fetchone()[0] > 0
                row_count = 0
                if has_table:
                    check_cur.execute("SELECT COUNT(*) FROM manga_data")
                    row_count = check_cur.fetchone()[0]
            if row_count > 0:
                shutil.copy2(LEGACY_DB_PATH, db_path)
                _db_log(f"Migrated legacy database from: {LEGACY_DB_PATH}")
        except sqlite3.Error as exc:
            _db_log(f"Failed to check legacy database, starting fresh: {exc}")

    _db_log(f"Ensuring schema at: {db_path}")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga_data'")
        if cursor.fetchone() is None:
            cursor.execute(SCHEMA_SQL)
            connection.commit()
        elif _schema_needs_migration(cursor):
            _db_log("Migrating manga_data schema")
            _migrate_schema(connection)
        connection.commit()
    _db_log("Schema check complete")


def record_download(
    manga_name: str,
    latest_chapter_local: float,
    latest_chapter_from_mangadex: float,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Insert or update a manga entry after a successful download."""
    db_path = _resolve_db_path(db_path)
    _db_log(
        "Starting save "
        f"(name='{manga_name}', local={latest_chapter_local}, source={latest_chapter_from_mangadex})"
    )
    ensure_schema(db_path)
    checked_at = int(time.time())

    with sqlite3.connect(db_path) as connection:
        _db_log("Connected to database")
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO manga_data (
                manga_name,
                date_last_checked,
                latest_chapter_local,
                latest_chapter_from_mangadex
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(manga_name) DO UPDATE SET
                date_last_checked = excluded.date_last_checked,
                latest_chapter_local = excluded.latest_chapter_local,
                latest_chapter_from_mangadex = excluded.latest_chapter_from_mangadex
            """,
            (
                manga_name,
                checked_at,
                latest_chapter_local,
                latest_chapter_from_mangadex,
            ),
        )
        connection.commit()
    _db_log("Commit complete")


def record_download_from_folders(
    manga_name: str,
    chapter_folders: Iterable[str],
    latest_chapter_from_mangadex: float | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Record manga download using inferred latest chapter from chapter folders."""
    _db_log(f"Inferring latest chapter from folders for '{manga_name}'")
    latest_local = infer_latest_chapter_from_folders(chapter_folders)
    _db_log(f"Inferred latest local chapter={latest_local}")
    latest_source = (
        latest_local
        if latest_chapter_from_mangadex is None
        else latest_chapter_from_mangadex
    )
    record_download(
        manga_name=manga_name,
        latest_chapter_local=latest_local,
        latest_chapter_from_mangadex=latest_source,
        db_path=db_path,
    )


def get_tracked_manga(db_path: str = DEFAULT_DB_PATH) -> list[dict[str, float | str]]:
    """Return tracked manga records from the database."""
    db_path = _resolve_db_path(db_path)
    ensure_schema(db_path)
    _db_log("Loading tracked manga list")
    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT manga_name, latest_chapter_local, latest_chapter_from_mangadex
            FROM manga_data
            ORDER BY manga_name COLLATE NOCASE ASC
            """
        )
        rows = cursor.fetchall()

    result: list[dict[str, float | str]] = []
    for manga_name, latest_local, latest_source in rows:
        result.append(
            {
                "manga_name": str(manga_name),
                "latest_chapter_local": float(latest_local),
                "latest_chapter_from_mangadex": float(latest_source),
            }
        )
    _db_log(f"Loaded {len(result)} tracked manga entries")
    return result
