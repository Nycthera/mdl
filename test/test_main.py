# tests/test_main.py
import pytest
from main import (
    extract_manga_name_from_url,
    validate_manga_input,
    url_exists,
    download_image,
    sanitize_folder_name,
    extract_manga_uuid,
    get_images_md,
    download_all_pages,
    create_cbz_for_all
)
from unittest.mock import patch, MagicMock
import os
import tempfile
import shutil

# ------------------ EXTRACT MANGA NAME ------------------
def test_extract_manga_name_url():
    url = "https://scans.lastation.us/manga/one-piece/"
    assert extract_manga_name_from_url(url) == "one-piece"

def test_extract_manga_name_text():
    assert extract_manga_name_from_url("naruto") == "naruto"

# ------------------ VALIDATE MANGA INPUT ------------------
def test_validate_manga_input(monkeypatch):
    # should not raise
    validate_manga_input("naruto")
    
    # test sys.exit for empty input
    with pytest.raises(SystemExit):
        validate_manga_input("")

# ------------------ URL EXISTS ------------------
def test_url_exists_true():
    with patch("main.session.head") as mock_head:
        mock_head.return_value.status_code = 200
        assert url_exists("https://fake.url") is True

def test_url_exists_false():
    with patch("main.session.head") as mock_head:
        mock_head.return_value.status_code = 404
        assert url_exists("https://fake.url") is False

def test_url_exists_exception():
    with patch("main.session.head", side_effect=Exception):
        assert url_exists("https://fake.url") is False

# ------------------ DOWNLOAD IMAGE ------------------
def test_download_image_success(tmp_path, monkeypatch):
    folder = tmp_path / "images"
    url = "https://fake.url/image.png"
    
    # mock session.get
    class MockResponse:
        content = b"fake image"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("main.session.get", lambda *a, **k: MockResponse())
    
    msg = download_image(url, folder)
    assert "Saved as" in msg
    saved_file = folder / "image.png"
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"fake image"

# ------------------ SANITIZE FOLDER NAME ------------------
def test_sanitize_folder_name():
    name = "Chapter: 1/2*?"
    sanitized = sanitize_folder_name(name)
    assert sanitized == "Chapter_ 1_2__"

# ------------------ EXTRACT MANGA UUID ------------------
def test_extract_manga_uuid_valid():
    url = "https://mangadex.org/title/ed996855-70de-449f-bba2-e8e24224c14d/onii-chan"
    assert extract_manga_uuid(url) == "ed996855-70de-449f-bba2-e8e24224c14d"

def test_extract_manga_uuid_invalid():
    url = "https://mangadex.org/some/other/url"
    assert extract_manga_uuid(url) is None

# ------------------ GET IMAGES MANGADEX ------------------
@patch("main.requests.get")
def test_get_images_md_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "baseUrl": "https://fake.mangadex.org",
        "chapter": {"hash": "abc123", "data": ["1.png", "2.png"]}
    }
    mock_get.return_value = mock_resp
    urls = get_images_md("fake-chap")
    assert urls == ["https://fake.mangadex.org/data/abc123/1.png",
                    "https://fake.mangadex.org/data/abc123/2.png"]

@patch("main.requests.get")
def test_get_images_md_no_pages(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"baseUrl": None, "chapter": {}}
    mock_get.return_value = mock_resp
    urls = get_images_md("fake-chap")
    assert urls == []

# ------------------ DOWNLOAD ALL PAGES ------------------
def test_download_all_pages(tmp_path, monkeypatch):
    folder = tmp_path / "chapter_1"
    urls_to_download = [(f"https://fake.url/{i}.png", folder) for i in range(3)]
    
    class MockResponse:
        content = b"data"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("main.session.get", lambda *a, **k: MockResponse())
    
    download_all_pages(urls_to_download, max_workers=2, manga_name="test-manga")
    for i in range(3):
<<<<<<< HEAD
        assert (folder / f"{i}.png").exists()
=======
        assert (folder / f"{i}.png").exists()
>>>>>>> ef4d9e0 (idk what to do here bruh)
