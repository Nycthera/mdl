"""Chapter archives preserve data through packaging, updates, and history-backed repair."""

import zipfile
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree import ElementTree as ET

import pytest

from src import cbz, downloader, verification
from src.output_formats import create_output_for_all

JPEG = b"\xff\xd8image\xff\xd9"


def page(root, chapter, name="001.jpg", data=JPEG):
    folder = root / chapter
    folder.mkdir(parents=True, exist_ok=True)
    result = folder / name
    result.write_bytes(data)
    return result


def metadata(path):
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("ComicInfo.xml"))


def test_chapter_archives_include_metadata_and_preserve_other_outputs(tmp_path):
    root = tmp_path / "A & B"
    first = page(root, "chapter_0001")
    page(root, "chapter_0001", "002.jpg")
    second = page(root, "chapter_0010.5")
    (root / "existing.pdf").write_bytes(b"existing PDF")
    (root / "existing.epub").write_bytes(b"existing EPUB")
    create_output_for_all(
        str(root),
        "cbz",
        cbz_layout="chapter",
        language="ja",
        reading_direction="rtl",
        source_url="https://example.test/title?a=1&b=2",
    )

    assert not first.parent.exists()
    assert not second.parent.exists()
    assert sorted(path.name for path in root.glob("*.cbz")) == [
        "chapter_0001.cbz",
        "chapter_0010.5.cbz",
    ]
    info = metadata(root / "chapter_0001.cbz")
    assert info.findtext("Series") == "A & B"
    assert info.findtext("Number") == "1"
    assert info.findtext("PageCount") == "2"
    assert info.findtext("LanguageISO") == "ja"
    assert info.findtext("Manga") == "YesAndRightToLeft"
    assert info.findtext("Web") == "https://example.test/title?a=1&b=2"
    assert metadata(root / "chapter_0010.5.cbz").findtext("Number") == "10.5"
    assert (root / "existing.pdf").read_bytes() == b"existing PDF"
    with zipfile.ZipFile(root / "chapter_0001.cbz") as archive:
        assert set(archive.namelist()) == {"001.jpg", "002.jpg", "ComicInfo.xml"}


def test_chapter_update_merges_pages_without_rewriting_other_chapters(tmp_path):
    root = tmp_path / "Title"
    page(root, "chapter_1")
    page(root, "chapter_2")
    cbz.create_cbz_per_chapter(str(root))
    untouched = (root / "chapter_1.cbz").read_bytes()
    page(root, "chapter_2", "002.jpg")
    cbz.create_cbz_per_chapter(str(root))
    assert (root / "chapter_1.cbz").read_bytes() == untouched
    with zipfile.ZipFile(root / "chapter_2.cbz") as archive:
        assert archive.read("001.jpg") == JPEG
        assert archive.read("002.jpg") == JPEG
    assert metadata(root / "chapter_2.cbz").findtext("PageCount") == "2"


def test_chapter_update_failure_preserves_archive_and_source(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    page(root, "chapter_1")
    cbz.create_cbz_per_chapter(str(root))
    original = (root / "chapter_1.cbz").read_bytes()
    replacement = page(root, "chapter_1", data=b"replacement")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        cbz.create_cbz_per_chapter(str(root))
    assert (root / "chapter_1.cbz").read_bytes() == original
    assert replacement.read_bytes() == b"replacement"
    assert not list(root.glob(".pending_*"))


@pytest.mark.parametrize("excluded", [".pending_002.jpg", "notes.txt", "other.cbz"])
def test_chapter_cleanup_keeps_unarchived_files(tmp_path, excluded):
    root = tmp_path / "Title"
    original = page(root, "chapter_1")
    (original.parent / excluded).write_bytes(b"keep")
    cbz.create_cbz_per_chapter(str(root))
    assert original.exists()
    assert (original.parent / excluded).read_bytes() == b"keep"
    with zipfile.ZipFile(root / "chapter_1.cbz") as archive:
        assert excluded not in archive.namelist()


def test_chapter_cleanup_does_not_follow_symlinks(tmp_path):
    root = tmp_path / "Title"
    original = page(root, "chapter_1")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(JPEG)
    (original.parent / "linked.jpg").symlink_to(outside)
    cbz.create_cbz_per_chapter(str(root))
    assert original.parent.exists()
    assert outside.read_bytes() == JPEG
    with zipfile.ZipFile(root / "chapter_1.cbz") as archive:
        assert "linked.jpg" not in archive.namelist()


def test_verification_accepts_legacy_and_chapter_archives_without_history(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    page(root, "chapter_1")
    cbz.create_cbz_for_all(str(root))
    legacy = (root / "Title.cbz").read_bytes()
    page(root, "chapter_2")
    cbz.create_cbz_per_chapter(str(root))
    monkeypatch.setattr(verification, "get_latest_page_records", lambda _: [])
    report = verification.verify_library(str(root))
    assert report.valid
    assert report.checked == 2
    assert (root / "Title.cbz").read_bytes() == legacy


async def test_repair_chapter_cbz_preserves_metadata_and_other_archives(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    broken = page(root, "chapter_0.5", data=b"broken")
    missing = broken.parent / "002.jpg"
    page(root, "chapter_2")
    cbz.create_cbz_per_chapter(str(root), language="ko", reading_direction="ltr")
    untouched = (root / "chapter_2.cbz").read_bytes()
    monkeypatch.setattr(
        verification,
        "get_latest_page_records",
        lambda _: [
            {
                "file_path": str(path),
                "url": f"https://cdn.test/{path.name}",
                "folder": str(path.parent),
            }
            for path in (broken, missing)
        ],
    )

    async def save(urls, **kwargs):
        for url, folder in urls:
            Path(folder).mkdir(parents=True, exist_ok=True)
            Path(folder, url.rsplit("/", 1)[-1]).write_bytes(JPEG)

    monkeypatch.setattr(downloader, "download_all_pages", AsyncMock(side_effect=save))
    before, after = await verification.repair_library(str(root))
    assert len(before.issues) == 2
    assert after.valid
    assert not broken.parent.exists()
    assert (root / "chapter_2.cbz").read_bytes() == untouched
    info = metadata(root / "chapter_0.5.cbz")
    assert info.findtext("Number") == "0.5"
    assert info.findtext("LanguageISO") == "ko"
    assert info.findtext("Manga") == "Yes"
    assert info.findtext("PageCount") == "2"


async def test_archived_pages_are_only_reused_when_requested(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    original = page(root, "chapter_1.5")
    cbz.create_cbz_per_chapter(str(root))
    monkeypatch.setattr(downloader, "stop_signal", False)
    monkeypatch.setattr(downloader, "CLEAN_OUTPUT", True)
    download = AsyncMock(return_value="Saved as page")
    monkeypatch.setattr(downloader, "download_image", download)
    urls = [("https://cdn.test/001.jpg", str(original.parent))]
    result = await downloader.download_all_pages(
        urls, track_to_db=False, skip_archived=True, output_path=str(root)
    )
    assert result.complete
    download.assert_not_awaited()
    assert not original.parent.exists()
    await downloader.download_all_pages(
        urls, track_to_db=False, skip_archived=False, output_path=str(root)
    )
    download.assert_awaited_once()
