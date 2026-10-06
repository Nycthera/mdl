"""Image optimization and download pipeline coverage."""

import asyncio
import threading
import zipfile

import pytest
from PIL import Image

from src import downloader, image_optimizer
from src.cbz import create_cbz_for_all
from src.cli import parse_args


@pytest.mark.parametrize(
    ("arguments", "mode"),
    [
        ([], "off"),
        (["--optimize-images"], "balanced"),
        (["--optimize-images", "lossless"], "lossless"),
        (["--optimize-images", "small"], "small"),
    ],
)
def test_cli_optimization_modes(monkeypatch, arguments, mode):
    monkeypatch.setattr("sys.argv", ["mdl", *arguments])
    assert parse_args().optimize_images == mode


def test_lossless_png_keeps_pixels_and_only_replaces_when_smaller(tmp_path):
    page = tmp_path / "001.png"
    Image.new("RGBA", (100, 100), (20, 40, 60, 120)).save(page, compress_level=0)
    original_size = page.stat().st_size

    assert image_optimizer.optimize_image(str(page), "lossless")
    assert page.stat().st_size < original_size
    with Image.open(page) as result:
        assert result.getpixel((0, 0)) == (20, 40, 60, 120)
    assert not image_optimizer.optimize_image(str(page), "lossless")


def test_small_mode_keeps_jpeg_name_and_can_be_archived(tmp_path):
    root = tmp_path / "Title"
    chapter = root / "Chapter 1"
    chapter.mkdir(parents=True)
    page = chapter / "001.jpg"
    image = Image.new("RGB", (160, 160))
    image.putdata([(i % 160, i // 160, (i * 19) % 256) for i in range(160 * 160)])
    image.save(page, quality=95)
    original_size = page.stat().st_size

    assert image_optimizer.optimize_image(str(page), "small")
    assert page.stat().st_size < original_size
    archive = create_cbz_for_all(str(root))
    with zipfile.ZipFile(archive) as cbz:
        assert cbz.namelist() == ["Chapter 1/001.jpg", "ComicInfo.xml"]
        assert cbz.getinfo("Chapter 1/001.jpg").compress_type == zipfile.ZIP_DEFLATED
        assert cbz.read("Chapter 1/001.jpg").startswith(b"\xff\xd8")


async def test_downloads_continue_during_optimization(tmp_path, monkeypatch):
    optimizer_started = threading.Event()
    second_download_started = threading.Event()

    async def fake_download(url, folder, **kwargs):
        filename = url.rsplit("/", 1)[-1]
        if filename == "002.png":
            assert await asyncio.to_thread(optimizer_started.wait, 2)
            second_download_started.set()
        (tmp_path / filename).write_bytes(b"page")
        return f"Saved as {folder}/{filename}"

    def slow_optimize(path, mode):
        if path.endswith("001.png"):
            optimizer_started.set()
            assert second_download_started.wait(2), "download slots were held by optimization"
        return False

    monkeypatch.setattr(downloader, "download_image", fake_download)
    monkeypatch.setattr(image_optimizer, "optimize_image", slow_optimize)
    monkeypatch.setattr(downloader, "CLEAN_OUTPUT", True)

    result = await asyncio.wait_for(
        downloader.download_all_pages(
            [
                ("https://example.test/001.png", str(tmp_path)),
                ("https://example.test/002.png", str(tmp_path)),
            ],
            max_workers=1,
            track_to_db=False,
            optimize_mode="balanced",
        ),
        5,
    )
    assert optimizer_started.is_set()
    assert result.complete


@pytest.mark.parametrize("mode", ["lossless", "balanced", "small"])
def test_optimizer_keeps_bad_image_untouched(tmp_path, mode):
    page = tmp_path / "001.png"
    page.write_bytes(b"not an image")
    assert not image_optimizer.optimize_image(str(page), mode)
    assert page.read_bytes() == b"not an image"
