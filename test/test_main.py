# tests/test_main.py
import pytest
from main import extract_manga_name, validate_manga_input
import sys

def test_extract_manga_name_url():
    url = "https://scans.lastation.us/manga/one-piece/"
    assert extract_manga_name(url) == "one-piece"

def test_extract_manga_name_text():
    assert extract_manga_name("naruto") == "naruto"

def test_validate_manga_input(monkeypatch):
    # should not raise
    validate_manga_input("naruto")
    
    # test sys.exit
    with pytest.raises(SystemExit):
        validate_manga_input("")
        
from main import url_exists
from unittest.mock import patch

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


from main import download_image
import os

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
    # file exists
    saved_file = folder / "image.png"
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"fake image"


from main import console, create_cbz_for_all
import os
from pathlib import Path
import zipfile

def test_create_cbz(tmp_path):
    # Setup folder
    manga_name = "test_manga"
    manga_folder = tmp_path / manga_name
    manga_folder.mkdir()
    file_path = manga_folder / "page1.png"
    file_path.write_bytes(b"test")

    # Monkeypatch console to avoid printing
    class DummyConsole:
        def print(self, *args, **kwargs): pass
    import main
    main.console = DummyConsole()

    # Temporarily change directory to tmp_path
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Pass only the manga name string (not full path)
        create_cbz_for_all(manga_name)
    finally:
        os.chdir(old_cwd)

    # CBZ path: inside manga_folder, named after manga_name
    cbz_file = manga_folder / f"{manga_name}.cbz"
    print("Expecting CBZ at:", cbz_file)
    print("Contents of manga_folder:", list(manga_folder.iterdir()))

    # Assert CBZ exists
    assert cbz_file.exists(), "CBZ file was not created"

    # Check contents
    with zipfile.ZipFile(cbz_file, 'r') as zipf:
        assert "page1.png" in zipf.namelist()
