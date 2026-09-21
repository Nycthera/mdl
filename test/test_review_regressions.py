"""Regression coverage for data integrity and source routing."""

import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest

import main
from src import cbz, downloader, http
from src.database.manga_db import get_tracked_manga, record_download
from src.scrapers import _collect_chapter_urls_for_download, mangadex
from src.utils import sanitize_folder_name


def test_archive_update_preserves_previous_chapters(tmp_path):
    root = tmp_path / "Title"
    chapter = root / "chapter_0001"
    chapter.mkdir(parents=True)
    (chapter / "001.png").write_bytes(b"first")
    archive = cbz.create_cbz_for_all(str(root))
    chapter2 = root / "chapter_0002"
    chapter2.mkdir()
    (chapter2 / "001.png").write_bytes(b"second")
    cbz.create_cbz_for_all(str(root))
    with zipfile.ZipFile(archive) as stream:
        assert stream.read("chapter_0001/001.png") == b"first"
        assert stream.read("chapter_0002/001.png") == b"second"


def test_failed_archive_update_preserves_archive_and_sources(tmp_path, monkeypatch):
    root = tmp_path / "Title"
    root.mkdir()
    page = root / "001.png"
    page.write_bytes(b"first")
    archive = cbz.create_cbz_for_all(str(root))
    original = (root / "Title.cbz").read_bytes()
    page.write_bytes(b"replacement")
    monkeypatch.setattr(zipfile.ZipFile, "write", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        cbz.create_cbz_for_all(str(root))
    assert open(archive, "rb").read() == original
    assert page.read_bytes() == b"replacement"


@pytest.mark.parametrize("name", ["..", ".", "///", "\x00", "CON"])
def test_folder_names_are_safe_components(name):
    result = sanitize_folder_name(name)
    assert result not in ("", ".", "..", "CON")
    assert "\x00" not in result


@pytest.mark.parametrize(
    "url",
    [
        "https://mangadex.org.evil.test/title/id",
        "https://weebcentral.evil.test/",
        "https://webtoons.com@evil.test/",
    ],
)
def test_source_detection_rejects_lookalike_hosts(url):
    assert main._detect_source_from_input(url) is None


async def test_shared_http_session_can_be_constructed():
    async with http.build_session() as session:
        assert not session.closed


async def test_mirrors_choose_one_url_per_page(tmp_path, monkeypatch):
    import src.scrapers as scrapers

    urls = ["https://a/manga/0001-001.png", "https://b/manga/0001-001.png"]
    monkeypatch.setattr(scrapers, "_collect_existing_urls", AsyncMock(return_value=urls[::-1]))
    result, _ = await _collect_chapter_urls_for_download(
        "manga", "0001", 1, 1, str(tmp_path), 2, None, ["https://a/", "https://b/"]
    )
    assert result == urls[:1]


def test_db_progress_never_regresses(tmp_path):
    path = str(tmp_path / "tracking.db")
    record_download("Title", 10, 12, path)
    record_download("Title", 3, 3, path)
    row = get_tracked_manga(path)[0]
    assert row["latest_chapter_local"] == 10
    assert row["latest_chapter_from_mangadex"] == 12


async def test_download_failure_is_returned_to_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "CLEAN_OUTPUT", True)
    monkeypatch.setattr(downloader, "download_image", AsyncMock(return_value="Failed to download"))
    result = await downloader.download_all_pages(
        [("https://example.com/001.png", str(tmp_path))], track_to_db=False
    )
    assert result is not None
    assert result.successful_pages == 0
    assert not result.complete


async def test_mangadex_saver_uses_saver_endpoint(monkeypatch):
    response = MagicMock(status=200)
    response.json = AsyncMock(
        return_value={
            "baseUrl": "https://images.test",
            "chapter": {"hash": "abc", "dataSaver": ["001.jpg"]},
        }
    )
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    monkeypatch.setattr(mangadex.rate_limiter_athome, "acquire", AsyncMock())
    assert await mangadex.get_images_md("chapter", use_saver=True, session=session) == [
        "https://images.test/data-saver/abc/001.jpg"
    ]


@pytest.mark.parametrize(
    "flag", ["--workers", "--max-pages", "--start-page", "--max-retries", "--timeout"]
)
def test_cli_rejects_nonpositive_limits(monkeypatch, flag):
    from src.cli import parse_args

    monkeypatch.setattr("sys.argv", ["mdl", flag, "0"])
    with pytest.raises(SystemExit) as exc:
        parse_args()
    assert exc.value.code == 2


def test_cli_can_disable_default_archive(monkeypatch):
    from src.cli import parse_args

    monkeypatch.setattr("sys.argv", ["mdl", "--no-cbz"])
    assert parse_args().cbz is False


async def test_auto_update_checks_even_when_cached_numbers_match(monkeypatch):
    monkeypatch.setattr(main, "stop_signal", False)
    monkeypatch.setattr(main, "CLEAN_OUTPUT", True)
    monkeypatch.setattr(
        main,
        "get_tracked_manga",
        lambda: [
            {"manga_name": "Title", "latest_chapter_local": 10, "latest_chapter_from_mangadex": 10}
        ],
    )
    gather = AsyncMock(return_value=[])
    monkeypatch.setattr(main, "gather_all_urls", gather)
    await main._auto_update_from_db(2, 1, 50, False)
    gather.assert_awaited_once()


@pytest.mark.parametrize("source", ["webtoons", "weebcentral", "direct"])
async def test_main_routes_downloads_and_propagates_failures(source, tmp_path, monkeypatch):
    from src.cli import parse_args

    monkeypatch.chdir(tmp_path)
    url = {
        "webtoons": "https://www.webtoons.com/en/test/title/ep/viewer?episode_no=1",
        "weebcentral": "https://weebcentral.com/chapters/chapter-id",
        "direct": "Title",
    }[source]
    monkeypatch.setattr("sys.argv", ["mdl", "-M", url, "--max-retries", "2", "--cbz"])
    args = parse_args()
    monkeypatch.setattr(main, "parse_args", lambda: args)
    monkeypatch.setattr(main, "load_config", lambda: {"credits_shown": True})
    monkeypatch.setattr(
        main,
        "fetch_webtoons_images",
        AsyncMock(return_value=([("https://cdn.test/001.png", "episode_0001")], "Title")),
    )
    monkeypatch.setattr(
        main,
        "fetch_weebcentral_images",
        AsyncMock(return_value=(["https://cdn.test/001.png"], "Title")),
    )
    gather = AsyncMock(return_value=[("https://cdn.test/001.png", "Title/chapter_0001")])
    monkeypatch.setattr(main, "gather_all_urls", gather)
    download = AsyncMock(return_value=downloader.DownloadResult(0, 1, []))
    monkeypatch.setattr(main, "download_all_pages", download)
    archive = MagicMock()
    monkeypatch.setattr(main, "create_cbz_for_all", archive)
    (tmp_path / "Title").mkdir()
    (tmp_path / "Title" / "page.png").write_bytes(b"old")
    await main.main()
    download.assert_awaited_once()
    assert download.call_args.kwargs["max_retries"] == 2
    paths = download.call_args.args[0]
    assert all(folder.startswith("Title/") for _, folder in paths)
    archive.assert_not_called()
    if source != "direct":
        gather.assert_not_awaited()


async def test_mangadex_failed_chapter_does_not_advance_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mangadex, "stop_signal", False)
    monkeypatch.setattr(mangadex, "get_manga_name_from_md", AsyncMock(return_value="Title"))
    monkeypatch.setattr(
        mangadex,
        "fetch_all_chapters_md",
        AsyncMock(
            return_value=[
                {"id": "one", "attributes": {"chapter": "1"}},
                {"id": "two", "attributes": {"chapter": "2"}},
            ]
        ),
    )
    monkeypatch.setattr(
        mangadex, "get_images_md", AsyncMock(return_value=["https://cdn.test/page.jpg"])
    )
    monkeypatch.setattr(
        mangadex,
        "download_all_pages",
        AsyncMock(
            side_effect=[
                downloader.DownloadResult(0, 1, []),
                downloader.DownloadResult(1, 1, ["chapter2"]),
            ]
        ),
    )
    record = MagicMock()
    archive = MagicMock()
    monkeypatch.setattr(mangadex, "record_download", record)
    monkeypatch.setattr(mangadex, "create_cbz_for_all", archive)
    await mangadex.download_md_chapters(
        "https://mangadex.org/title/12345678-1234-1234-1234-123456789abc"
    )
    record.assert_not_called()
    archive.assert_not_called()


def test_query_strings_are_not_saved_in_filenames():
    from src.utils import image_filename

    assert image_filename("https://cdn.test/page.jpg?type=q90#fragment") == "page.jpg"


def test_archive_excludes_pending_and_other_archives(tmp_path):
    root = tmp_path / "Title"
    root.mkdir()
    (root / "001.png").write_bytes(b"page")
    (root / ".pending_002.png").write_bytes(b"partial")
    (root / "other.cbz").write_bytes(b"archive")
    with zipfile.ZipFile(cbz.create_cbz_for_all(str(root))) as stream:
        assert stream.namelist() == ["001.png"]
    assert (root / ".pending_002.png").exists()


def test_archive_preserves_legacy_archive_only_entries(tmp_path):
    root = tmp_path / "Title"
    root.mkdir()
    with zipfile.ZipFile(root / "Title.cbz", "w") as archive:
        archive.writestr("chapter_0001/001.png", b"old")
    (root / "002.png").write_bytes(b"new")
    with zipfile.ZipFile(cbz.create_cbz_for_all(str(root))) as stream:
        assert stream.read("chapter_0001/001.png") == b"old"


@pytest.mark.parametrize("value", [[], {"workers": 0}, {"workers": "ten"}, {"cbz": "false"}])
def test_invalid_config_fails_without_rewriting(tmp_path, monkeypatch, value):
    import json

    from src import config

    path = tmp_path / "config.json"
    original = json.dumps(value)
    path.write_text(original)
    monkeypatch.setattr(config, "CONFIG_FILE", str(path))
    with pytest.raises(ValueError):
        config.load_config()
    assert path.read_text() == original


def test_config_path_lookup_does_not_create_directories(monkeypatch):
    from src import config

    mkdir = MagicMock()
    monkeypatch.setattr(config.os, "makedirs", mkdir)
    config.get_config_path()
    mkdir.assert_not_called()


def test_config_failed_save_preserves_existing_data(tmp_path, monkeypatch):
    from src import config

    path = tmp_path / "config.json"
    path.write_text('{"workers": 2}')
    monkeypatch.setattr(config, "CONFIG_FILE", str(path))
    monkeypatch.setattr(config.os, "replace", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        config.save_config({"workers": 3})
    assert path.read_text() == '{"workers": 2}'
    assert list(tmp_path.iterdir()) == [path]


def test_legacy_bundle_script_preserves_namespaces(tmp_path):
    import runpy
    from pathlib import Path

    from scripts.bundle import bundle

    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "mdl.py"
    bundle(root, output)
    data = runpy.run_path(str(output))
    assert "src.downloader" in data["_SOURCES"]
    assert "src.scrapers.mangadex" in data["_SOURCES"]


async def test_cancelling_batch_cancels_download_workers(tmp_path, monkeypatch):
    import asyncio

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def slow_download(*args, **kwargs):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    monkeypatch.setattr(downloader, "download_image", slow_download)
    monkeypatch.setattr(downloader, "CLEAN_OUTPUT", True)
    task = asyncio.create_task(
        downloader.download_all_pages([("https://test/001.png", str(tmp_path))], track_to_db=False)
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
