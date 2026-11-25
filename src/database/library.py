"""Tracked manga records and library metadata operations."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterable

from src.database.core import (
    DEFAULT_DB_PATH,
    _canonical_url,
    _database,
    _db_log,
    _make_source_key,
    _normalize_chapter,
    _resolve_db_path,
    _upsert_manga,
)
from src.database.history import infer_latest_chapter_from_folders
from src.database.schema import _ensure_schema_connection


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
    cbz_hash: str | None = None,
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
            cbz_hash=cbz_hash,
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
        cursor.execute("""
            SELECT id, date_last_checked, manga_name, latest_chapter_local, latest_chapter_from_mangadex,
                   source_type, source_url, source_id, language, output_path
            FROM manga_data
            ORDER BY manga_name COLLATE NOCASE ASC
            """)
        rows = cursor.fetchall()

    result: list[dict[str, float | str | None]] = []
    for row in rows:
        (
            manga_id,
            checked_at,
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
                "id": int(manga_id),
                "date_last_checked": int(checked_at),
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


def write_hash_to_database(
    hash_string: str, file_path: str, manga_name: str, db_path: str = DEFAULT_DB_PATH
) -> None:
    """Store a CBZ fingerprint on its tracked manga record."""
    db_path = _resolve_db_path(db_path)
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        connection.execute(
            "UPDATE manga_data SET cbz_hash = ?, output_path = ? "
            "WHERE manga_name = ? COLLATE NOCASE",
            (hash_string, os.path.abspath(file_path), manga_name),
        )


def get_library_entries(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return each tracked source with its latest recorded run, including idle titles."""
    db_path = _resolve_db_path(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with _database(db_path) as connection:
        _ensure_schema_connection(connection)
        connection.row_factory = sqlite3.Row
        rows = connection.execute("""
            SELECT m.*, r.status AS run_status, r.started_at, r.finished_at,
                   r.total_pages, r.successful_pages, r.failed_pages
            FROM manga_data AS m
            LEFT JOIN download_runs AS r ON r.id = (
                SELECT recent.id FROM download_runs AS recent
                WHERE recent.manga_id = m.id
                ORDER BY recent.started_at DESC, recent.id DESC LIMIT 1
            )
            ORDER BY m.manga_name COLLATE NOCASE, m.source_type, m.id
            """).fetchall()
    return [dict(row) for row in rows]


def get_library_entry(selector: str, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Resolve an exact title or explicit ``id:123`` without guessing between sources."""
    selector = selector.strip()
    entries = get_library_entries(db_path)
    if selector.lower().startswith("id:"):
        try:
            manga_id = int(selector[3:])
        except ValueError:
            raise ValueError("Use id:NUMBER, for example id:3, or an exact title.") from None
        matches = [entry for entry in entries if entry["id"] == manga_id]
    else:
        matches = [
            entry for entry in entries if entry["manga_name"].casefold() == selector.casefold()
        ]
    if not matches:
        raise ValueError(
            f"No tracked title matches {selector!r}. Use 'library list' to see titles."
        )
    if len(matches) > 1:
        choices = ", ".join(f"id:{entry['id']} ({entry['source_type']})" for entry in matches)
        raise ValueError(f"Multiple sources match {selector!r}; select one with {choices}.")
    return matches[0]


def mark_library_checked(manga_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Record a completed source check even when it found no new pages."""
    with _database(_resolve_db_path(db_path)) as connection:
        connection.execute(
            "UPDATE manga_data SET date_last_checked = ? WHERE id = ?",
            (int(time.time()), manga_id),
        )
