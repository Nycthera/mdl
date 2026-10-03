"""SQLite tracking for downloaded manga metadata."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
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

SCHEMA_VERSION = 3
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
    }
    return not required.issubset(columns) or not _has_unique_index(
        cursor, "manga_data", ("source_type", "source_key")
    )


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
    source_key = (
        "COALESCE(NULLIF(TRIM(source_key), ''), LOWER(TRIM(manga_name)))"
        if "source_key" in columns
        else "LOWER(TRIM(manga_name))"
    )

    cursor.execute("ALTER TABLE manga_data RENAME TO manga_data_old")
    cursor.execute(SCHEMA_SQL)
    cursor.execute(
        f"""
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
            output_path
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
            MAX({output_path})
        FROM manga_data_old
        WHERE manga_name IS NOT NULL AND TRIM(manga_name) != ''
        GROUP BY {source_type} COLLATE NOCASE, {source_key} COLLATE NOCASE
        """
    )
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
) -> int:
    """Insert/update a source-specific title and return its row id."""
    row = cursor.execute(
        """
        INSERT INTO manga_data (
            manga_name, date_last_checked, latest_chapter_local,
            latest_chapter_from_mangadex, source_type, source_key,
            source_url, source_id, language, output_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            output_path = COALESCE(excluded.output_path, manga_data.output_path)
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
        ),
    ).fetchone()
    return int(row[0])


def record_download(
    manga_name: str,
    latest_chapter_local: float,
    latest_chapter_from_mangadex: float,
    db_path: str = DEFAULT_DB_PATH,
    *,
    source_type: str = "generic",
    source_url: str | None = None,
    source_id: str | None = None,
    language: str | None = None,
    output_path: str | None = None,
) -> None:
    """Insert or update a manga entry after a successful download."""
    db_path = _resolve_db_path(db_path)
    manga_name = manga_name.strip()
    if not manga_name:
        raise ValueError("manga_name must not be empty")
    source_type = source_type.strip().lower() or "generic"
    source_url = _canonical_url(source_url)
    source_id = source_id.strip() if source_id else None
    source_key = _make_source_key(manga_name, source_type, source_url, source_id)
    output_path = os.path.abspath(output_path) if output_path else None
    latest_chapter_local = _normalize_chapter(latest_chapter_local, "latest_chapter_local")
    latest_chapter_from_mangadex = _normalize_chapter(
        latest_chapter_from_mangadex, "latest_chapter_from_mangadex"
    )
    _db_log(
        "Starting save "
        f"(name='{manga_name}', local={latest_chapter_local}, source={latest_chapter_from_mangadex})"
    )
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    checked_at = int(time.time())

    with _database(db_path) as connection:
        _db_log("Connected to database")
        _ensure_schema_connection(connection)
        cursor = connection.cursor()
        _upsert_manga(
            cursor,
            manga_name=manga_name,
            checked_at=checked_at,
            latest_local=latest_chapter_local,
            latest_source=latest_chapter_from_mangadex,
            source_type=source_type,
            source_key=source_key,
            source_url=source_url,
            source_id=source_id,
            language=language,
            output_path=output_path,
        )
    _db_log("Commit complete")


def record_download_from_folders(
    manga_name: str,
    chapter_folders: Iterable[str],
    latest_chapter_from_mangadex: float | None = None,
    db_path: str = DEFAULT_DB_PATH,
    *,
    source_type: str = "generic",
    source_url: str | None = None,
    source_id: str | None = None,
    language: str | None = None,
    output_path: str | None = None,
) -> None:
    """Record manga download using inferred latest chapter from chapter folders."""
    _db_log(f"Inferring latest chapter from folders for '{manga_name}'")
    latest_local = infer_latest_chapter_from_folders(chapter_folders)
    _db_log(f"Inferred latest local chapter={latest_local}")
    latest_source = (
        latest_local if latest_chapter_from_mangadex is None else latest_chapter_from_mangadex
    )
    record_download(
        manga_name=manga_name,
        latest_chapter_local=latest_local,
        latest_chapter_from_mangadex=latest_source,
        db_path=db_path,
        source_type=source_type,
        source_url=source_url,
        source_id=source_id,
        language=language,
        output_path=output_path,
    )


def get_tracked_manga(
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, float | str | None]]:
    """Return tracked manga records from the database."""
    db_path = _resolve_db_path(db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    _db_log("Loading tracked manga list")
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT manga_name, latest_chapter_local, latest_chapter_from_mangadex,
                   source_type, source_url, source_id, language, output_path
            FROM manga_data
            ORDER BY manga_name COLLATE NOCASE ASC
            """
        )
        rows = cursor.fetchall()

    result: list[dict[str, float | str | None]] = []
    for row in rows:
        (
            manga_name,
            latest_local,
            latest_source,
            source_type,
            source_url,
            source_id,
            language,
            output_path,
        ) = row
        result.append(
            {
                "manga_name": str(manga_name),
                "latest_chapter_local": float(latest_local),
                "latest_chapter_from_mangadex": float(latest_source),
                "source_type": str(source_type),
                "source_url": str(source_url) if source_url else None,
                "source_id": str(source_id) if source_id else None,
                "language": str(language) if language else None,
                "output_path": str(output_path) if output_path else None,
            }
        )
    _db_log(f"Loaded {len(result)} tracked manga entries")
    return result


def begin_download_run(
    manga_name: str,
    total_pages: int,
    db_path: str = DEFAULT_DB_PATH,
    *,
    source_type: str = "generic",
    source_url: str | None = None,
    source_id: str | None = None,
    language: str | None = None,
    output_path: str | None = None,
) -> int:
    """Start a durable download run and return its identifier."""
    db_path = _resolve_db_path(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    manga_name = manga_name.strip()
    if not manga_name:
        raise ValueError("manga_name must not be empty")
    source_type = source_type.strip().lower() or "generic"
    source_url = _canonical_url(source_url)
    source_id = source_id.strip() if source_id else None
    source_key = _make_source_key(manga_name, source_type, source_url, source_id)
    output_path = os.path.abspath(output_path) if output_path else None
    now = int(time.time())

    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        cursor = connection.cursor()
        manga_id = _upsert_manga(
            cursor,
            manga_name=manga_name,
            checked_at=now,
            latest_local=0.0,
            latest_source=0.0,
            source_type=source_type,
            source_key=source_key,
            source_url=source_url,
            source_id=source_id,
            language=language,
            output_path=output_path,
        )
        row = cursor.execute(
            """
            INSERT INTO download_runs (manga_id, started_at, status, total_pages)
            VALUES (?, ?, 'running', ?)
            RETURNING id
            """,
            (manga_id, now, max(0, int(total_pages))),
        ).fetchone()
        return int(row[0])


def record_page_results(
    run_id: int,
    results: Iterable[tuple[str, str, str, str, str]],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Persist page outcomes as (url, folder, file_path, status, message)."""
    rows = [
        (run_id, url, folder, os.path.abspath(file_path), status, message, int(time.time()))
        for url, folder, file_path, status, message in results
    ]
    if not rows:
        return
    db_path = _resolve_db_path(db_path)
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        connection.executemany(
            """
            INSERT INTO page_downloads (
                run_id, url, folder, file_path, status, message, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def finish_download_run(
    run_id: int,
    *,
    successful_pages: int,
    failed_pages: int,
    interrupted: bool = False,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Finalize a download run after page results have been recorded."""
    if interrupted:
        status = "interrupted"
    elif failed_pages:
        status = "partial"
    else:
        status = "complete"
    db_path = _resolve_db_path(db_path)
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        connection.execute(
            """
            UPDATE download_runs
            SET finished_at = ?, status = ?, successful_pages = ?, failed_pages = ?
            WHERE id = ?
            """,
            (
                int(time.time()),
                status,
                max(0, int(successful_pages)),
                max(0, int(failed_pages)),
                run_id,
            ),
        )


def get_latest_page_records(
    output_path: str,
    db_path: str = DEFAULT_DB_PATH,
) -> list[dict[str, str]]:
    """Return the newest known record for each expected file in a library folder."""
    root = os.path.abspath(output_path)
    db_path = _resolve_db_path(db_path)
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        rows = connection.execute(
            """
            SELECT p.url, p.folder, p.file_path, p.status, COALESCE(p.message, '')
            FROM page_downloads AS p
            JOIN download_runs AS r ON r.id = p.run_id
            JOIN manga_data AS m ON m.id = r.manga_id
            WHERE m.output_path = ?
              AND p.id = (
                  SELECT MAX(newest.id)
                  FROM page_downloads AS newest
                  JOIN download_runs AS newest_run ON newest_run.id = newest.run_id
                  WHERE newest.file_path = p.file_path
                    AND newest_run.manga_id = r.manga_id
              )
            ORDER BY p.file_path
            """,
            (root,),
        ).fetchall()
    return [
        {
            "url": str(url),
            "folder": str(folder),
            "file_path": str(file_path),
            "status": str(status),
            "message": str(message),
        }
        for url, folder, file_path, status, message in rows
    ]


def get_download_history(
    manga_name: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
    limit: int = 50,
) -> list[dict[str, int | str | None]]:
    """Return recent run summaries, optionally filtered by title."""
    db_path = _resolve_db_path(db_path)
    params: list[object] = []
    where = ""
    if manga_name:
        where = "WHERE m.manga_name = ? COLLATE NOCASE"
        params.append(manga_name.strip())
    params.append(max(1, int(limit)))
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        rows = connection.execute(
            f"""
            SELECT r.id, m.manga_name, m.source_type, r.started_at, r.finished_at,
                   r.status, r.total_pages, r.successful_pages, r.failed_pages
            FROM download_runs AS r
            JOIN manga_data AS m ON m.id = r.manga_id
            {where}
            ORDER BY r.started_at DESC, r.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    keys = (
        "id",
        "manga_name",
        "source_type",
        "started_at",
        "finished_at",
        "status",
        "total_pages",
        "successful_pages",
        "failed_pages",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]
