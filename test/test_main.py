from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
import aiohttp


import src.config as config_mod
import src.utils as utils_mod
from src.cbz import create_cbz_for_all
from src.database.manga_db import (
    infer_latest_chapter_from_folders,
    get_tracked_manga,
    record_download,
    record_download_from_folders,
)
import main as app_main
import src.scrapers.mangadex as mangadex_mod
from src.downloader import download_image


# ---------- CONFIG TESTS ----------


def test_create_default_config(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))

    config_mod.create_default_config()
    assert cfg_path.exists()

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "manga_name" in cfg
    assert isinstance(cfg["workers"], int)


def test_load_config_creates_default(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))

    cfg = config_mod.load_config()
    assert cfg_path.exists()
    assert isinstance(cfg, dict)


# ---------- SANITIZATION ----------


def test_sanitize_folder_name_removes_illegal():
    name = 'Manga:Name<>?*/"'
    cleaned = utils_mod.sanitize_folder_name(name)

    illegal = '<>:"/\\|?*'
    assert all(c not in cleaned for c in illegal)
    assert cleaned.replace(" ", "") == "MangaName"


# ---------- URL HANDLING ----------


def test_extract_manga_name_from_url():
    url = "https://weebcentral.com/manga/one-piece/001.png"
    assert utils_mod.extract_manga_name_from_url(url) == "one piece"


def test_get_slug_and_pretty():
    slug, pretty = utils_mod.get_slug_and_pretty("My Hero Academia")
    assert slug == "My-Hero-Academia"
    assert pretty == "My Hero Academia"

    slug2, pretty2 = utils_mod.get_slug_and_pretty("https://site.com/manga/naruto/")
    assert "naruto" in slug2.lower()
    assert "naruto" in pretty2.lower()


def test_get_slug_and_pretty_collapses_spaces():
    slug, pretty = utils_mod.get_slug_and_pretty(" My   Hero   Academia ")
    assert slug == "My-Hero-Academia"
    assert pretty == "My Hero Academia"


# ---------- CBZ CREATION ----------


def test_create_cbz_for_all(tmp_path: Path):
    manga_folder = tmp_path / "One Piece"
    manga_folder.mkdir()

    (manga_folder / "page1.png").write_bytes(b"dummy")
    (manga_folder / "page2.png").write_bytes(b"dummy")

    create_cbz_for_all(str(manga_folder))

    cbz_path = manga_folder / "One Piece.cbz"
    assert cbz_path.exists()

    with zipfile.ZipFile(cbz_path) as z:
        files = z.namelist()
        assert "page1.png" in files
        assert "page2.png" in files


def test_create_cbz_skips_when_no_files(tmp_path: Path):
    empty = tmp_path / "Empty Manga"
    empty.mkdir()

    create_cbz_for_all(str(empty))
    assert not any(p.suffix == ".cbz" for p in empty.iterdir())


# ---------- SAFE DELETE ----------


def test_safe_delete_folder(tmp_path: Path):
    file = tmp_path / "dummy.txt"
    file.write_text("abc", encoding="utf-8")

    utils_mod.safe_delete_folder(str(tmp_path))

    assert not tmp_path.exists()


# ---------- MANGADEX ----------


def test_extract_manga_uuid_valid():
    url = "https://mangadex.org/title/123e4567-e89b-12d3-a456-426614174000/foobar"
    assert mangadex_mod.extract_manga_uuid(url) == "123e4567-e89b-12d3-a456-426614174000"


def test_extract_manga_uuid_invalid():
    url = "https://mangadex.org/chapter/abcdef"
    assert mangadex_mod.extract_manga_uuid(url) is None


@pytest.mark.asyncio
async def test_get_manga_name_from_md_fallback(monkeypatch):
    monkeypatch.setattr(mangadex_mod, "extract_manga_uuid", lambda _: None)

    url = "https://mangadex.org/title/some"
    result = await mangadex_mod.get_manga_name_from_md(url, lang="jp")

    assert result == utils_mod.extract_manga_name_from_url(url)


# ---------- DOWNLOAD ERROR HANDLING ----------


@pytest.mark.asyncio
async def test_download_image_http_error(tmp_path: Path):
    class DummyResp:
        status = 400

        def raise_for_status(self):
            raise aiohttp.ClientError("bad")

        async def read(self):
            return b"dummy"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class DummySession:
        def get(self, *args, **kwargs):
            return DummyResp()

    msg = await download_image(
        "http://example.com/x.png",
        str(tmp_path),
        session=DummySession(),
    )

    assert "Failed" in msg or "error" in msg.lower()


# ---------- SQLITE TRACKING ----------


def test_record_download_insert_and_update(tmp_path: Path):
    db_path = tmp_path / "manga_collection.db"

    record_download(
        manga_name="Solo Leveling",
        latest_chapter_local=12.0,
        latest_chapter_from_mangadex=12.5,
        db_path=str(db_path),
    )

    with sqlite3.connect(str(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT id, manga_name, latest_chapter_local, latest_chapter_from_mangadex FROM manga_data"
        )
        rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == 1
    assert rows[0][1] == "Solo Leveling"
    assert rows[0][2] == 12
    assert rows[0][3] == 12.5

    record_download(
        manga_name="Solo Leveling",
        latest_chapter_local=13.0,
        latest_chapter_from_mangadex=13.0,
        db_path=str(db_path),
    )

    with sqlite3.connect(str(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT id, manga_name, latest_chapter_local, latest_chapter_from_mangadex FROM manga_data"
        )
        rows_after = cursor.fetchall()

    assert len(rows_after) == 1
    assert rows_after[0][0] == 1
    assert rows_after[0][2] == 13
    assert rows_after[0][3] == 13


def test_infer_latest_chapter_from_folders():
    folders = [
        "My Manga/Chapter_0001",
        "My Manga/Chapter_0012.5",
        "My Manga/Chapter_0008",
    ]
    assert infer_latest_chapter_from_folders(folders) == 12.5


def test_infer_latest_chapter_ignores_manga_title_digits():
    folders = [
        "86/chapter_0001",
        "86/chapter_0010",
        "86/chapter_0002.5",
    ]
    assert infer_latest_chapter_from_folders(folders) == 10.0


def test_record_download_from_folders(tmp_path: Path):
    db_path = tmp_path / "manga_collection.db"
    record_download_from_folders(
        manga_name="86",
        chapter_folders=["86/chapter_0001", "86/chapter_0007.5"],
        db_path=str(db_path),
    )

    with sqlite3.connect(str(db_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT manga_name, latest_chapter_local, latest_chapter_from_mangadex FROM manga_data"
        )
        row = cursor.fetchone()

    assert row is not None
    assert row[0] == "86"
    assert row[1] == 7.5
    assert row[2] == 7.5


def test_get_tracked_manga(tmp_path: Path):
    db_path = tmp_path / "manga_collection.db"
    record_download("A", 2.0, 2.0, db_path=str(db_path))
    record_download("B", 5.5, 5.5, db_path=str(db_path))

    tracked = get_tracked_manga(db_path=str(db_path))
    assert len(tracked) == 2
    assert tracked[0]["manga_name"] == "A"
    assert tracked[1]["manga_name"] == "B"


def test_calculate_resume_chapter():
    assert app_main._calculate_resume_chapter(0.0) == 1
    assert app_main._calculate_resume_chapter(7.0) == 7
    assert app_main._calculate_resume_chapter(7.5) == 7
