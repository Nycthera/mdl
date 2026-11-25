"""Download run history and library query operations."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable

from src.database.core import (
    DEFAULT_DB_PATH,
    _canonical_url,
    _database,
    _make_source_key,
    _resolve_db_path,
    _upsert_manga,
)
from src.database.schema import _ensure_schema_connection


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
        (
            run_id,
            url,
            folder,
            os.path.abspath(file_path),
            status,
            message,
            int(time.time()),
        )
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
