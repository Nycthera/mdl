"""Database schema creation, migration, and legacy database import."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing

from src.database.core import (
    DEFAULT_DB_PATH,
    HISTORY_SCHEMA_SQL,
    LEGACY_DB_PATH,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    _database,
    _db_log,
    _resolve_db_path,
)


def _has_unique_index(
    cursor: sqlite3.Cursor, table_name: str, column_names: tuple[str, ...]
) -> bool:
    """Return whether a table has a unique index for the given columns."""
    cursor.execute(f"PRAGMA index_list({table_name})")
    for _, index_name, is_unique, *_ in cursor.fetchall():
        if not is_unique:
            continue
        cursor.execute(f"PRAGMA index_info({index_name})")
        indexed_columns = [row[2] for row in cursor.fetchall()]
        if indexed_columns == list(column_names):
            return True
    return False


def _schema_needs_migration(cursor: sqlite3.Cursor) -> bool:
    """Return whether the manga_data table needs to be rebuilt."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga_data'")
    if cursor.fetchone() is None:
        return False

    cursor.execute("PRAGMA user_version")
    if cursor.fetchone()[0] < SCHEMA_VERSION:
        return True

    cursor.execute("PRAGMA table_info(manga_data)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {
        "id",
        "manga_name",
        "date_last_checked",
        "latest_chapter_local",
        "latest_chapter_from_mangadex",
        "source_type",
        "source_key",
        "source_url",
        "source_id",
        "language",
        "output_path",
        "cbz_hash",
    }
    return not required.issubset(columns) or not _has_unique_index(
        cursor, "manga_data", ("source_type", "source_key")
    )


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """Rebuild the manga_data table with the current schema and dedupe rows."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA table_info(manga_data)")
    columns = {row[1] for row in cursor.fetchall()}
    date_column = "date_last_checked"
    if "date_last_checked" not in columns:
        date_column = "date_last_chcked"
    source_type = (
        "COALESCE(NULLIF(TRIM(source_type), ''), 'generic')"
        if "source_type" in columns
        else "'generic'"
    )
    source_url = "source_url" if "source_url" in columns else "NULL"
    source_id = "source_id" if "source_id" in columns else "NULL"
    language = "language" if "language" in columns else "NULL"
    output_path = "output_path" if "output_path" in columns else "NULL"
    cbz_hash = "cbz_hash" if "cbz_hash" in columns else "NULL"
    source_key = (
        "COALESCE(NULLIF(TRIM(source_key), ''), LOWER(TRIM(manga_name)))"
        if "source_key" in columns
        else "LOWER(TRIM(manga_name))"
    )

    cursor.execute("ALTER TABLE manga_data RENAME TO manga_data_old")
    cursor.execute(SCHEMA_SQL)
    cursor.execute(f"""
        INSERT INTO manga_data (
            manga_name,
            date_last_checked,
            latest_chapter_local,
            latest_chapter_from_mangadex,
            source_type,
            source_key,
            source_url,
            source_id,
            language,
            output_path,
            cbz_hash
        )
        SELECT
            MIN(TRIM(manga_name)),
            MAX(CASE WHEN COALESCE({date_column}, 0) >= 0 THEN {date_column} ELSE 0 END),
            MAX(
                CASE WHEN COALESCE(latest_chapter_local, 0) >= 0
                THEN latest_chapter_local ELSE 0 END
            ),
            MAX(
                CASE WHEN COALESCE(latest_chapter_from_mangadex, 0) >= 0
                THEN latest_chapter_from_mangadex ELSE 0 END
            ),
            {source_type},
            {source_key},
            MAX({source_url}),
            MAX({source_id}),
            MAX({language}),
            MAX({output_path}),
            MAX({cbz_hash})
        FROM manga_data_old
        WHERE manga_name IS NOT NULL AND TRIM(manga_name) != ''
        GROUP BY {source_type} COLLATE NOCASE, {source_key} COLLATE NOCASE
        """)
    cursor.execute("DROP TABLE manga_data_old")


def _ensure_history_schema(cursor: sqlite3.Cursor) -> None:
    """Create download-run and page-history tables and indexes."""
    for statement in HISTORY_SCHEMA_SQL.split(";"):
        if statement.strip():
            cursor.execute(statement)


def _ensure_schema_connection(connection: sqlite3.Connection) -> None:
    """Create or migrate the schema using an existing connection."""
    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga_data'")
    if cursor.fetchone() is None:
        cursor.execute(SCHEMA_SQL)
    elif _schema_needs_migration(cursor):
        _db_log("Migrating manga_data schema")
        _migrate_schema(connection)
    _ensure_history_schema(cursor)
    cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _backup_database(source_path: str, destination_path: str) -> None:
    """Copy a SQLite database consistently, including any committed WAL data."""
    with (
        closing(sqlite3.connect(source_path)) as source,
        closing(sqlite3.connect(destination_path)) as destination,
    ):
        source.backup(destination)


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
            with closing(sqlite3.connect(LEGACY_DB_PATH)) as _check_conn:
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
                _backup_database(LEGACY_DB_PATH, db_path)
                _db_log(f"Migrated legacy database from: {LEGACY_DB_PATH}")
        except sqlite3.Error as exc:
            _db_log(f"Failed to check legacy database, starting fresh: {exc}")

    _db_log(f"Ensuring schema at: {db_path}")

    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
    _db_log("Schema check complete")
