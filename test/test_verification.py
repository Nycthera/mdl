from pathlib import Path
from unittest.mock import AsyncMock

from src import cbz, downloader, verification


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8" + (b"image" * 10) + b"\xff\xd9"


def test_verify_library_reports_corrupt_and_missing_pages(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    chapter = root / "chapter_1"
    chapter.mkdir(parents=True)
    good = chapter / "001.jpg"
    bad = chapter / "002.png"
    missing = chapter / "003.jpg"
    good.write_bytes(_jpeg_bytes())
    bad.write_bytes(b"not a png")

    monkeypatch.setattr(
        verification,
        "get_latest_page_records",
        lambda _: [
            {"file_path": str(good), "url": "https://cdn/001.jpg", "folder": str(chapter)},
            {"file_path": str(bad), "url": "https://cdn/002.png", "folder": str(chapter)},
            {
                "file_path": str(missing),
                "url": "https://cdn/003.jpg",
                "folder": str(chapter),
            },
        ],
    )

    report = verification.verify_library(str(root))
    assert report.checked == 3
    assert {(Path(issue.path).name, issue.reason) for issue in report.issues} == {
        ("002.png", "invalid PNG markers"),
        ("003.jpg", "missing file"),
    }


def test_verify_library_rejects_missing_root(tmp_path, monkeypatch):
    monkeypatch.setattr(verification, "get_latest_page_records", lambda _: [])
    report = verification.verify_library(str(tmp_path / "missing"))
    assert not report.valid
    assert report.issues[0].reason == "path does not exist"


def test_verify_library_accepts_pages_in_cbz(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    chapter = root / "chapter_1"
    chapter.mkdir(parents=True)
    page = chapter / "001.jpg"
    page.write_bytes(_jpeg_bytes())
    monkeypatch.setattr(
        verification,
        "get_latest_page_records",
        lambda _: [{"file_path": str(page), "url": "https://cdn/001.jpg", "folder": str(chapter)}],
    )

    cbz.create_cbz_for_all(str(root))

    assert not chapter.exists()
    report = verification.verify_library(str(root))
    assert report.valid
    assert report.checked == 1


async def test_repair_library_replaces_corrupt_cbz_page(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    chapter = root / "chapter_1"
    chapter.mkdir(parents=True)
    page = chapter / "001.jpg"
    page.write_bytes(b"broken")
    monkeypatch.setattr(
        verification,
        "get_latest_page_records",
        lambda _: [{"file_path": str(page), "url": "https://cdn/001.jpg", "folder": str(chapter)}],
    )
    cbz.create_cbz_for_all(str(root))

    async def fake_download(urls, **kwargs):
        for url, folder in urls:
            Path(folder).mkdir(parents=True, exist_ok=True)
            Path(folder, url.rsplit("/", 1)[-1]).write_bytes(_jpeg_bytes())
        return downloader.DownloadResult(len(urls), len(urls), [str(chapter)])

    monkeypatch.setattr(downloader, "download_all_pages", AsyncMock(side_effect=fake_download))
    before, after = await verification.repair_library(str(root))

    assert len(before.issues) == 1
    assert after.valid
    assert not chapter.exists()


async def test_repair_library_redownloads_from_history(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    chapter = root / "chapter_1"
    chapter.mkdir(parents=True)
    corrupt = chapter / "001.jpg"
    missing = chapter / "002.jpg"
    corrupt.write_bytes(b"broken")
    records = [
        {"file_path": str(corrupt), "url": "https://cdn/001.jpg", "folder": str(chapter)},
        {"file_path": str(missing), "url": "https://cdn/002.jpg", "folder": str(chapter)},
    ]
    monkeypatch.setattr(verification, "get_latest_page_records", lambda _: records)

    async def fake_download(urls, **kwargs):
        for url, folder in urls:
            Path(folder, url.rsplit("/", 1)[-1]).write_bytes(_jpeg_bytes())
        return downloader.DownloadResult(len(urls), len(urls), [str(chapter)])

    monkeypatch.setattr(downloader, "download_all_pages", AsyncMock(side_effect=fake_download))
    before, after = await verification.repair_library(str(root), workers=2)

    assert len(before.issues) == 2
    assert after.valid
    assert not list(chapter.glob(".corrupt_*"))
