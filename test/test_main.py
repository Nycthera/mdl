import os
import json
import zipfile
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock

import main  # assuming your main script is named main.py


# ---------- FIXTURES ----------
@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


# ---------- CONFIG TESTS ----------
def test_create_default_config(temp_dir, monkeypatch):
    cfg_path = os.path.join(temp_dir, "config.json")
    monkeypatch.setattr(main, "CONFIG_FILE", cfg_path)

    main.create_default_config()
    assert os.path.exists(cfg_path)

    with open(cfg_path) as f:
        cfg = json.load(f)
    assert "manga_name" in cfg
    assert isinstance(cfg["workers"], int)


def test_load_config_creates_default(temp_dir, monkeypatch):
    cfg_path = os.path.join(temp_dir, "config.json")
    monkeypatch.setattr(main, "CONFIG_FILE", cfg_path)
    cfg = main.load_config()
    assert os.path.exists(cfg_path)
    assert isinstance(cfg, dict)


# ---------- SANITIZATION ----------
def test_sanitize_folder_name_removes_illegal():
    name = 'Manga:Name<>?*/"'
    cleaned = main.sanitize_folder_name(name)
    assert all(c not in cleaned for c in '<>:"/\\|?*')
    assert " " in cleaned or cleaned == "MangaName"


# ---------- URL HANDLING ----------
def test_extract_manga_name_from_url():
    url = "https://weebcentral.com/manga/one-piece/001.png"
    result = main.extract_manga_name_from_url(url)
    assert result == "one piece"


def test_get_slug_and_pretty():
    slug, pretty = main.get_slug_and_pretty("My Hero Academia")
    assert slug == "My-Hero-Academia"
    assert pretty == "My Hero Academia"

    slug2, pretty2 = main.get_slug_and_pretty("https://site.com/manga/naruto/")
    assert "naruto" in slug2
    assert "Naruto" in pretty2 or "naruto" in pretty2.lower()


# ---------- URL EXISTS ----------
@patch("main.session.head")
def test_url_exists_true(mock_head):
    mock_head.return_value.status_code = 200
    assert main.url_exists("https://example.com")


@patch("main.session.head")
def test_url_exists_false(mock_head):
    mock_head.return_value.status_code = 404
    assert main.url_exists("https://example.com") is False


# ---------- CBZ CREATION ----------
def test_create_cbz_for_all(temp_dir):
    # Prepare some dummy files
    manga_folder = os.path.join(temp_dir, "One Piece")
    os.makedirs(manga_folder)
    with open(os.path.join(manga_folder, "page1.png"), "wb") as f:
        f.write(b"dummy")
    with open(os.path.join(manga_folder, "page2.png"), "wb") as f:
        f.write(b"dummy")

    main.create_cbz_for_all(manga_folder)

    cbz_path = os.path.join(manga_folder, "One Piece.cbz")
    assert os.path.exists(cbz_path)

    # ensure pages are inside the archive
    with zipfile.ZipFile(cbz_path, "r") as z:
        files = z.namelist()
        assert "page1.png" in files
        assert "page2.png" in files


# ---------- SAFE DELETE ----------
@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)
def test_safe_delete_folder(temp_dir):
    f = os.path.join(temp_dir, "dummy.txt")
    with open(f, "w") as file:
        file.write("abc")
    main.safe_delete_folder(temp_dir)
    assert not os.path.exists(f)
    assert not os.path.exists(temp_dir)
