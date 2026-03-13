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


DEFAULT_DB_PATH = os.environ.get(
    "MANGA_DB_PATH",
    os.path.join(os.path.dirname(get_config_path()), "manga_collection.db"),
)
LEGACY_DB_PATH = os.path.join(os.path.dirname(__file__), "manga_collection.db")

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


def ensure_schema(db_path: str = DEFAULT_DB_PATH) -> None:
    """Ensure the manga tracking table exists."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # One-time migration for users moving from the legacy in-repo DB path.
    if (
        db_path == DEFAULT_DB_PATH
        and not os.path.exists(db_path)
        and os.path.exists(LEGACY_DB_PATH)
        and os.path.abspath(LEGACY_DB_PATH) != os.path.abspath(db_path)
    ):
        shutil.copy2(LEGACY_DB_PATH, db_path)
        _db_log(f"Migrated legacy database from: {LEGACY_DB_PATH}")

    _db_log(f"Ensuring schema at: {db_path}")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS manga_data (
                id INTEGER NOT NULL,
                manga_name TEXT NOT NULL,
                date_last_checked NUMERIC NOT NULL,
                latest_chapter_local NUMERIC NOT NULL,
                latest_chapter_from_mangadex NUMERIC NOT NULL
            )
            """
        )
        connection.commit()
    _db_log("Schema check complete")


def record_download(
    manga_name: str,
    latest_chapter_local: float,
    latest_chapter_from_mangadex: float,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Insert or update a manga entry after a successful download."""
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
            "SELECT id FROM manga_data WHERE manga_name = ? ORDER BY id ASC LIMIT 1",
            (manga_name,),
        )
        existing = cursor.fetchone()

        if existing:
            _db_log(f"Existing row found (id={existing[0]}), updating")
            cursor.execute(
                """
                UPDATE manga_data
                SET date_last_chcked = ?,
                    latest_chapter_local = ?,
                    latest_chapter_from_mangadex = ?
                WHERE id = ?
                """,
                (
                    checked_at,
                    latest_chapter_local,
                    latest_chapter_from_mangadex,
                    existing[0],
                ),
            )
        else:
            _db_log("No existing row found, inserting")
            cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM manga_data")
            next_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO manga_data (
                    id,
                    manga_name,
                    date_last_chcked,
                    latest_chapter_local,
                    latest_chapter_from_mangadex
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    next_id,
                    manga_name,
                    checked_at,
                    latest_chapter_local,
                    latest_chapter_from_mangadex,
                ),
            )
            _db_log(f"Inserted new row id={next_id}")
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
