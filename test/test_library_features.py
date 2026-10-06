"""Library commands exercise real SQLite history and source-specific update paths."""

import io
import zipfile
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree import ElementTree as ET

import pytest
from rich.console import Console

import main
from src import downloader, library
from src.cli import parse_args
from src.database import manga_db as db
from src.scrapers import mangadex


@pytest.fixture
def library_db(tmp_path, monkeypatch):
    path = str(tmp_path / "library.db")
    db.ensure_schema(path)
    for module, names in (
        (main, ("get_library_entry", "get_tracked_manga", "mark_library_checked")),
        (library, ("get_library_entries", "get_library_entry")),
        (
            downloader,
            (
                "begin_download_run",
                "record_page_results",
                "finish_download_run",
                "record_download_from_folders",
            ),
        ),
        (mangadex, ("record_download",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, partial(getattr(db, name), db_path=path))
    monkeypatch.setattr(main, "load_config", lambda: {"credits_shown": True})
    monkeypatch.setattr(main, "stop_signal", False)
    monkeypatch.setattr(downloader, "stop_signal", False)
    monkeypatch.setattr(downloader, "CLEAN_OUTPUT", True)
    return path


def test_library_status_selects_latest_run_for_each_source(library_db):
    db.record_download("Same Title", 4.5, 5, library_db, source_type="mangadex", source_id="md")
    first = db.begin_download_run(
        "Same Title", 4, library_db, source_type="mangadex", source_id="md"
    )
    db.finish_download_run(first, successful_pages=4, failed_pages=0, db_path=library_db)
    last = db.begin_download_run(
        "Same Title", 6, library_db, source_type="mangadex", source_id="md"
    )
    db.finish_download_run(last, successful_pages=5, failed_pages=1, db_path=library_db)
    db.record_download("Same Title", 2, 2, library_db, source_type="mangapill", source_id="pill")
    rows = db.get_library_entries(library_db)
    assert len(rows) == 2
    dex, pill = rows
    assert dex["run_status"] == "partial"
    assert dex["failed_pages"] == 1
    assert dex["latest_chapter_local"] == 4.5
    assert pill["run_status"] is None
    with pytest.raises(ValueError, match="Multiple sources"):
        db.get_library_entry("same title", library_db)
    assert db.get_library_entry(f"id:{pill['id']}", library_db)["source_type"] == "mangapill"
    with pytest.raises(ValueError, match="No tracked title"):
        db.get_library_entry("missing", library_db)


def test_library_views_show_saved_status_and_paths(library_db, tmp_path):
    stream = io.StringIO()
    console = Console(file=stream, width=180, color_system=None)
    library.print_library(console)
    assert "No tracked titles" in stream.getvalue()
    db.record_download("Title [One]", 10.5, 10.5, library_db, output_path=str(tmp_path / "missing"))
    library.print_library(console)
    library.print_library_status(console, "title [one]")
    output = stream.getvalue()
    assert "Title [One]" in output
    assert "10.5" in output
    assert "unrecorded" in output
    assert "False" in output
    assert str(tmp_path / "missing") in output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--workers", "3", "--clean-output", "library", "update", "id:4"],
        ["library", "update", "id:4", "--workers", "3", "--clean-output"],
    ],
)
def test_library_cli_preserves_options_before_and_after_command(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["mdl", *arguments])
    args = parse_args()
    assert args.workers == 3
    assert args.clean_output
    assert args.max_retries == 5
    assert args.selector == "id:4"


@pytest.mark.parametrize(
    "source,source_url",
    [
        ("mangapill", "https://mangapill.com/manga/1/title"),
        ("manganato", "https://manganato.com/manga-ab123"),
    ],
)
async def test_library_updates_only_selected_source_in_saved_folder(
    library_db, tmp_path, monkeypatch, source, source_url
):
    destination = tmp_path / "saved" / "My Title"
    db.record_download(
        "My Title",
        1,
        1,
        library_db,
        source_type=source,
        source_url=source_url,
        output_path=str(destination),
    )
    db.record_download(
        "My Title", 2, 2, library_db, source_type="generic", output_path=str(tmp_path / "other")
    )
    selected = next(
        row for row in db.get_library_entries(library_db) if row["source_type"] == source
    )
    fetch = AsyncMock(return_value=([("https://cdn.test/001.jpg", "chapter_2")], "My Title"))
    monkeypatch.setattr(main, f"fetch_{source}_images", fetch)
    generic = AsyncMock(side_effect=AssertionError("wrong source"))
    monkeypatch.setattr(main, "gather_all_urls", generic)

    async def save_image(url, folder, **kwargs):
        assert kwargs["referer"] == source_url
        Path(folder, "001.jpg").write_bytes(b"\xff\xd8page\xff\xd9")
        return "Saved as page"

    save = AsyncMock(side_effect=save_image)
    monkeypatch.setattr(downloader, "download_image", save)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["mdl", "library", "update", f"id:{selected['id']}", "--clean-output"]
    )
    await main.main()
    assert (destination / "My Title.cbz").exists()
    assert not (destination / "chapter_2").exists()
    assert not (tmp_path / "My Title").exists()
    assert not (tmp_path / "other").exists()
    assert db.get_library_entry(f"id:{selected['id']}", library_db)["latest_chapter_local"] == 2
    assert len(db.get_library_entries(library_db)) == 2

    # A second update still discovers the source, but reuses pages inside its CBZ.
    await main.main()
    save.assert_awaited_once()
    generic.assert_not_awaited()
    assert fetch.await_count == 2
    assert not (destination / "chapter_2").exists()
    assert db.get_library_entry(f"id:{selected['id']}", library_db)["run_status"] == "complete"


async def test_ambiguous_library_update_does_not_start_downloads(library_db, monkeypatch):
    for source in ("mangapill", "manganato"):
        db.record_download("Duplicate", 1, 1, library_db, source_type=source)
    update = AsyncMock()
    monkeypatch.setattr(main, "_auto_update_from_db", update)
    monkeypatch.setattr("sys.argv", ["mdl", "library", "update", "Duplicate"])
    with pytest.raises(SystemExit) as exc:
        await main.main()
    assert exc.value.code == 1
    update.assert_not_awaited()


async def test_library_update_returns_failure_for_partial_download(
    library_db, tmp_path, monkeypatch
):
    destination = tmp_path / "Title"
    db.record_download(
        "Title",
        1,
        1,
        library_db,
        source_type="mangapill",
        source_url="https://mangapill.com/manga/1/title",
        output_path=str(destination),
    )
    monkeypatch.setattr(
        main,
        "fetch_mangapill_images",
        AsyncMock(return_value=([("https://cdn.test/001.jpg", "chapter_2")], "Title")),
    )
    monkeypatch.setattr(
        downloader, "download_image", AsyncMock(return_value="Failed to download page")
    )
    monkeypatch.setattr("sys.argv", ["mdl", "library", "update", "Title", "--clean-output"])
    with pytest.raises(SystemExit) as exc:
        await main.main()
    assert exc.value.code == 1
    assert not list(destination.glob("*.cbz"))
    row = db.get_library_entry("Title", library_db)
    assert row["latest_chapter_local"] == 1
    assert row["run_status"] == "partial"


@pytest.mark.parametrize(
    "source,url",
    [
        ("mangapill", "https://www.mangapill.com:443/manga/1/title"),
        ("manganato", "https://chapmanganato.to/manga-aa123"),
        (None, "https://mangapill.com.evil.test/manga/1/title"),
        (None, "https://manganato.com@evil.test/manga-aa123"),
    ],
)
def test_new_source_routing_matches_hostnames(source, url):
    assert main._detect_source_from_input(url) == source


@pytest.mark.parametrize(
    "source,url",
    [
        ("mangapill", "https://mangapill.com/manga/1/title"),
        ("manganato", "https://manganato.com/manga-ab123"),
    ],
)
async def test_direct_html_download_records_source_and_metadata(
    library_db, tmp_path, monkeypatch, source, url
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        main,
        f"fetch_{source}_images",
        AsyncMock(return_value=([("https://cdn.test/001.jpg", "chapter_12.5")], "New Title")),
    )

    async def save_image(image_url, folder, **kwargs):
        Path(folder, "001.jpg").write_bytes(b"\xff\xd8page\xff\xd9")
        return "Saved as page"

    monkeypatch.setattr(downloader, "download_image", save_image)
    monkeypatch.setattr(
        "sys.argv",
        [
            "mdl",
            "-M",
            url,
            "--clean-output",
            "--metadata-language",
            "ko",
            "--reading-direction",
            "ltr",
            "--cbz-layout",
            "chapter",
        ],
    )
    await main.main()
    row = db.get_library_entry("New Title", library_db)
    assert row["source_type"] == source
    assert row["source_url"] == url
    assert row["language"] == "ko"
    with zipfile.ZipFile(tmp_path / "New Title" / "chapter_12.5.cbz") as archive:
        info = ET.fromstring(archive.read("ComicInfo.xml"))
    assert info.findtext("Series") == "New Title"
    assert info.findtext("Number") == "12.5"
    assert info.findtext("LanguageISO") == "ko"
    assert info.findtext("Manga") == "Yes"


async def test_mangadex_library_update_uses_saved_folder_and_chapter_metadata(
    library_db, tmp_path, monkeypatch
):
    source_url = "https://mangadex.org/title/12345678-1234-1234-1234-123456789abc"
    destination = tmp_path / "books" / "Saved Title"
    db.record_download(
        "A & B",
        0,
        0,
        library_db,
        source_type="mangadex",
        source_url=source_url,
        source_id="12345678-1234-1234-1234-123456789abc",
        language="ja",
        output_path=str(destination),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mangadex, "get_manga_name_from_md", AsyncMock(return_value="A & B"))
    monkeypatch.setattr(
        mangadex,
        "fetch_all_chapters_md",
        AsyncMock(
            return_value=[
                {
                    "id": "chapter-zero",
                    "attributes": {"chapter": "0", "title": "Arrival & Departure"},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        mangadex, "get_images_md", AsyncMock(return_value=["https://cdn.test/001.jpg"])
    )

    async def save_image(url, folder, **kwargs):
        Path(folder, "001.jpg").write_bytes(b"\xff\xd8page\xff\xd9")
        return "Saved as page"

    monkeypatch.setattr(downloader, "download_image", save_image)
    monkeypatch.setattr(
        "sys.argv",
        ["mdl", "library", "update", "A & B", "--clean-output", "--cbz-layout", "chapter"],
    )
    await main.main()
    archives = list(destination.glob("*.cbz"))
    assert len(archives) == 1
    assert not (tmp_path / "A & B").exists()
    with zipfile.ZipFile(archives[0]) as archive:
        info = ET.fromstring(archive.read("ComicInfo.xml"))
    assert info.findtext("Series") == "A & B"
    assert info.findtext("Title") == "Arrival & Departure"
    assert info.findtext("Number") == "0"
    assert info.findtext("LanguageISO") == "ja"
    assert info.findtext("Web") == "https://mangadex.org/chapter/chapter-zero"
    assert len(db.get_library_entries(library_db)) == 1


async def test_library_list_ignores_saved_dependency_update_action(library_db, monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: {"update": True})
    update = AsyncMock()
    monkeypatch.setattr(main, "update", update)
    monkeypatch.setattr("sys.argv", ["mdl", "library", "list", "--clean-output"])
    await main.main()
    update.assert_not_called()
