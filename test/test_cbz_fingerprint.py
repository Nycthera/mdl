"""Tests for fast CBZ fingerprints and their database storage."""

import sqlite3

import xxhash

from src.database.manga_db import (
    ensure_schema,
    hash_generator,
    record_download,
    write_hash_to_database,
)


def test_hash_generator_returns_xxh3_128_for_complete_file(tmp_path):
    archive = tmp_path / "series.cbz"
    contents = b"first page" * 20_000
    archive.write_bytes(contents)

    expected = xxhash.xxh3_128(contents).hexdigest()

    assert hash_generator(str(archive)) == expected


def test_hash_generator_changes_when_file_changes(tmp_path):
    archive = tmp_path / "series.cbz"
    archive.write_bytes(b"original")
    first = hash_generator(str(archive))

    archive.write_bytes(b"modified")

    assert hash_generator(str(archive)) != first


def test_cbz_hash_is_stored_on_manga_record(tmp_path):
    db_path = str(tmp_path / "manga.db")
    archive = tmp_path / "series.cbz"
    archive.write_bytes(b"complete archive contents")
    fingerprint = hash_generator(str(archive))

    ensure_schema(db_path)
    record_download(
        "Series",
        12,
        12,
        db_path,
        source_type="generic",
        output_path=str(tmp_path),
    )
    write_hash_to_database(fingerprint, str(archive), "Series", db_path)

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT cbz_hash, output_path FROM manga_data WHERE manga_name = ?",
            ("Series",),
        ).fetchone()

    assert row == (fingerprint, str(archive.resolve()))
