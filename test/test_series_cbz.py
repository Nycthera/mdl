"""Combined books retain all pages and clean up chapter artifacts safely."""

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree import ElementTree as ET

import pytest

import main
from src import cbz, config, downloader
from src.output_formats import create_output_for_all


def page(root, chapter, name="001.jpg", data=b"page"):
    path = root / chapter / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_default_book_merges_chapter_archives_and_new_pages_in_order(tmp_path):
    root = tmp_path / "Saved Title"
    for chapter in ("chapter_0004.5", "chapter_0004", "chapter_0010"):
        page(root, chapter, data=chapter.encode())
    cbz.create_cbz_per_chapter(str(root), series="Display Title", language="ja")
    page(root, "chapter_0004", "002.jpg", b"new page")

    result = create_output_for_all(str(root), "cbz", series="Display Title", language="ja")

    assert result == str(root / "Saved Title.cbz")
    assert list(root.iterdir()) == [Path(result)]
    with zipfile.ZipFile(result) as archive:
        images = [name for name in archive.namelist() if name.endswith(".jpg")]
        assert images == [
            "chapter_0004/001.jpg",
            "chapter_0004/002.jpg",
            "chapter_0004.5/001.jpg",
            "chapter_0010/001.jpg",
        ]
        assert archive.read(images[0]) == b"chapter_0004"
        assert archive.read(images[1]) == b"new page"
        assert archive.testzip() is None
        info = ET.fromstring(archive.read("ComicInfo.xml"))
        assert info.findtext("Series") == "Display Title"
        assert info.findtext("PageCount") == "4"
        assert info.findtext("LanguageISO") == "ja"
        assert "chapter_0004/ComicInfo.xml" in archive.namelist()
    indexed = cbz.index_cbz_pages(str(root))
    assert str(root / "chapter_0004" / "001.jpg") in indexed

    # Updates may fill earlier gaps; archive order must still follow chapter/page order.
    page(root, "chapter_0001")
    create_output_for_all(str(root), "cbz")
    with zipfile.ZipFile(result) as archive:
        assert archive.namelist()[0] == "chapter_0001/001.jpg"
        assert ET.fromstring(archive.read("ComicInfo.xml")).findtext("PageCount") == "5"


def test_failed_book_merge_preserves_chapter_archives_and_previous_book(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    page(root, "chapter_1")
    result = create_output_for_all(str(root), "cbz")
    original = Path(result).read_bytes()
    page(root, "chapter_2")
    cbz.create_cbz_per_chapter(str(root))
    chapter = root / "chapter_2.cbz"
    chapter_bytes = chapter.read_bytes()
    loose = page(root, "chapter_3")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cbz.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        create_output_for_all(str(root), "cbz")
    assert Path(result).read_bytes() == original
    assert chapter.read_bytes() == chapter_bytes
    assert loose.read_bytes() == b"page"
    assert not list(root.glob(".pending_*"))


@pytest.mark.parametrize("layout", ["series", "chapter"])
def test_repeated_packaging_removes_empty_chapters_but_keeps_pending_files(tmp_path, layout):
    root = tmp_path / "Title"
    page(root, "chapter_1")
    create_output_for_all(str(root), "cbz", cbz_layout=layout)
    archives = {path: path.read_bytes() for path in root.glob("*.cbz")}
    (root / "chapter_1" / "empty").mkdir(parents=True)
    (root / "chapter_2").mkdir()
    pending = page(root, "chapter_3", ".pending_page", b"partial download")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "chapter_4").symlink_to(outside, target_is_directory=True)

    create_output_for_all(str(root), "cbz", cbz_layout=layout)

    assert not (root / "chapter_1").exists()
    assert not (root / "chapter_2").exists()
    assert pending.read_bytes() == b"partial download"
    assert (root / "chapter_4").is_symlink()
    assert outside.exists()
    assert all(path.read_bytes() == data for path, data in archives.items())


@pytest.mark.parametrize(
    "saved_layout,arguments,expected",
    [
        (None, [], "series"),
        ("chapter", [], "chapter"),
        ("chapter", ["--cbz-layout", "series"], "series"),
        ("series", ["--cbz-layout", "chapter"], "chapter"),
    ],
)
async def test_cli_uses_config_layout_with_explicit_override(
    tmp_path, monkeypatch, saved_layout, arguments, expected
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.json"
    settings = {"credits_shown": True}
    if saved_layout is not None:
        settings["cbz_layout"] = saved_layout
    path.write_text(json.dumps(settings))
    monkeypatch.setattr(config, "CONFIG_FILE", str(path))
    monkeypatch.setattr("sys.argv", ["mdl", "-M", "Title", "--clean-output", *arguments])
    page(tmp_path / "Title", "chapter_1")
    monkeypatch.setattr(
        main,
        "gather_all_urls",
        AsyncMock(return_value=[("https://example.test/001.jpg", "Title/chapter_1")]),
    )
    monkeypatch.setattr(
        main,
        "download_all_pages",
        AsyncMock(return_value=downloader.DownloadResult(1, 1, ["Title/chapter_1"])),
    )
    await main.main()
    archive = "Title.cbz" if expected == "series" else "chapter_1.cbz"
    assert [p.name for p in (tmp_path / "Title").iterdir()] == [archive]
    assert json.loads(path.read_text())["cbz_layout"] == (saved_layout or "series")
