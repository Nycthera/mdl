from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import aiohttp

import main  # your main.py


# ---------- CONFIG TESTS ----------


def test_create_default_config(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(main, "CONFIG_FILE", cfg_path)

    main.create_default_config()
    assert cfg_path.exists()

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "manga_name" in cfg
    assert isinstance(cfg["workers"], int)


def test_load_config_creates_default(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(main, "CONFIG_FILE", cfg_path)

    cfg = main.load_config()
    assert cfg_path.exists()
    assert isinstance(cfg, dict)


# ---------- SANITIZATION ----------


def test_sanitize_folder_name_removes_illegal():
    name = 'Manga:Name<>?*/"'
    cleaned = main.sanitize_folder_name(name)

    illegal = '<>:"/\\|?*'
    assert all(c not in cleaned for c in illegal)
    assert cleaned.replace(" ", "") == "MangaName"


# ---------- URL HANDLING ----------


def test_extract_manga_name_from_url():
    url = "https://weebcentral.com/manga/one-piece/001.png"
    assert main.extract_manga_name_from_url(url) == "one piece"


def test_get_slug_and_pretty():
    slug, pretty = main.get_slug_and_pretty("My Hero Academia")
    assert slug == "My-Hero-Academia"
    assert pretty == "My Hero Academia"

    slug2, pretty2 = main.get_slug_and_pretty("https://site.com/manga/naruto/")
    assert "naruto" in slug2.lower()
    assert "naruto" in pretty2.lower()


def test_get_slug_and_pretty_collapses_spaces():
    slug, pretty = main.get_slug_and_pretty(" My   Hero   Academia ")
    assert slug == "My-Hero-Academia"
    assert pretty == "My Hero Academia"


# ---------- CBZ CREATION ----------


def test_create_cbz_for_all(tmp_path: Path):
    manga_folder = tmp_path / "One Piece"
    manga_folder.mkdir()

    (manga_folder / "page1.png").write_bytes(b"dummy")
    (manga_folder / "page2.png").write_bytes(b"dummy")

    main.create_cbz_for_all(manga_folder)

    cbz_path = manga_folder / "One Piece.cbz"
    assert cbz_path.exists()

    with zipfile.ZipFile(cbz_path) as z:
        files = z.namelist()
        assert "page1.png" in files
        assert "page2.png" in files


def test_create_cbz_skips_when_no_files(tmp_path: Path):
    empty = tmp_path / "Empty Manga"
    empty.mkdir()

    main.create_cbz_for_all(empty)
    assert not any(p.suffix == ".cbz" for p in empty.iterdir())


# ---------- SAFE DELETE ----------


def test_safe_delete_folder(tmp_path: Path):
    file = tmp_path / "dummy.txt"
    file.write_text("abc", encoding="utf-8")

    main.safe_delete_folder(tmp_path)

    assert not tmp_path.exists()


# ---------- MANGADEX ----------


def test_extract_manga_uuid_valid():
    url = "https://mangadex.org/title/123e4567-e89b-12d3-a456-426614174000/foobar"
    assert main.extract_manga_uuid(url) == "123e4567-e89b-12d3-a456-426614174000"


def test_extract_manga_uuid_invalid():
    url = "https://mangadex.org/chapter/abcdef"
    assert main.extract_manga_uuid(url) is None


@pytest.mark.asyncio
async def test_get_manga_name_from_md_fallback(monkeypatch):
    monkeypatch.setattr(main, "extract_manga_uuid", lambda _: None)

    url = "https://mangadex.org/title/some"
    result = await main.get_manga_name_from_md(url, lang="jp")

    assert result == main.extract_manga_name_from_url(url)


# ---------- DOWNLOAD ERROR HANDLING ----------


@pytest.mark.asyncio
async def test_download_image_http_error(monkeypatch, tmp_path: Path):
    class DummyResp:
        status = 400

        def raise_for_status(self):
            raise aiohttp.ClientResponseError(
                request_info=None,
                history=None,
                status=400,
                message="bad",
            )

        async def read(self):
            return b"dummy"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class DummySession:
        async def get(self, *args, **kwargs):
            return DummyResp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: DummySession())

    msg = await main.download_image(
        "http://example.com/x.png",
        tmp_path,
    )

    assert "Failed" in msg or "error" in msg.lower()
