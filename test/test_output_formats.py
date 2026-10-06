import zipfile
from pathlib import Path

from PIL import Image

from src.output_formats import create_epub, create_output_for_all, create_pdf


def _library(tmp_path: Path) -> Path:
    root = tmp_path / "Sample Manga"
    chapter_one = root / "Chapter 1"
    chapter_two = root / "Chapter 2"
    chapter_one.mkdir(parents=True)
    chapter_two.mkdir()
    for path, color in (
        (chapter_one / "001.png", "red"),
        (chapter_one / "002.png", "green"),
        (chapter_two / "001.png", "blue"),
    ):
        Image.new("RGB", (12, 18), color).save(path)
    return root


def test_create_epub_groups_pages_by_chapter(tmp_path):
    root = _library(tmp_path)

    result = create_epub(str(root))

    assert result == str(root / "Sample Manga.epub")
    with zipfile.ZipFile(result) as archive:
        assert archive.read("mimetype") == b"application/epub+zip"
        names = set(archive.namelist())
        assert "OEBPS/page-1.xhtml" in names
        assert "OEBPS/page-2.xhtml" in names
        assert "OEBPS/images/0001-0001.png" in names
        assert "OEBPS/images/0002-0001.png" in names
        assert b"Chapter 1" in archive.read("OEBPS/page-1.xhtml")
    assert not (root / "Chapter 1").exists()
    assert not (root / "Chapter 2").exists()


def test_create_pdf_contains_all_pages(tmp_path):
    root = _library(tmp_path)

    result = create_pdf(str(root))

    assert result == str(root / "Sample Manga.pdf")
    result_path = Path(result)
    assert result_path.read_bytes().startswith(b"%PDF")
    assert b"/Count 3" in result_path.read_bytes()
    assert not (root / "Chapter 1").exists()
    assert not (root / "Chapter 2").exists()


def test_output_cleanup_keeps_folders_with_excluded_files(tmp_path):
    root = _library(tmp_path)
    (root / "Chapter 2" / ".pending_page").write_bytes(b"pending")

    result = create_epub(str(root))

    assert result == str(root / "Sample Manga.epub")
    assert not (root / "Chapter 1").exists()
    assert (root / "Chapter 2").exists()
    assert (root / "Chapter 2" / ".pending_page").exists()


def test_output_dispatcher_rejects_unknown_formats(tmp_path):
    root = _library(tmp_path)

    assert create_output_for_all(str(root), "epub") == str(root / "Sample Manga.epub")
    try:
        create_output_for_all(str(root), "mobi")
    except ValueError as exc:
        assert "Unsupported output format" in str(exc)
    else:
        raise AssertionError("unknown output format was accepted")
