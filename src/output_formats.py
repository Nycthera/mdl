"""Export downloaded manga folders as CBZ, EPUB, or PDF files."""

from __future__ import annotations

import html
import os
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from src.cbz import _remove_archived_image_folders, create_cbz_for_all, create_cbz_per_chapter
from src.utils import sanitize_folder_name

OUTPUT_FORMATS = ("cbz", "epub", "pdf")
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _image_files(folder: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: path.relative_to(folder).as_posix().casefold(),
    )


def _output_path(folder: Path, extension: str) -> Path:
    return folder / f"{sanitize_folder_name(folder.name)}.{extension}"


def _atomic_replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _chapter_groups(folder: Path, images: list[Path]) -> list[tuple[str, list[Path]]]:
    groups: dict[str, list[Path]] = {}
    for image in images:
        relative = image.relative_to(folder)
        chapter = relative.parts[0] if len(relative.parts) > 1 else "Chapter 1"
        groups.setdefault(chapter, []).append(image)
    return sorted(groups.items(), key=lambda item: item[0].casefold())


def create_epub(folder_path: str) -> str | None:
    """Create an EPUB with one reflow-free XHTML document per chapter folder."""
    folder = Path(folder_path).resolve()
    images = _image_files(folder) if folder.is_dir() else []
    if not images:
        return None
    destination = _output_path(folder, "epub")
    fd, pending_name = tempfile.mkstemp(prefix=".pending_", suffix=".epub", dir=folder)
    os.close(fd)
    pending = Path(pending_name)
    pending.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            manifest: list[str] = []
            spine: list[str] = []
            for index, (chapter, chapter_images) in enumerate(_chapter_groups(folder, images), 1):
                page_id = f"page-{index}"
                page_name = f"page-{index}.xhtml"
                spine.append(f'<itemref idref="{page_id}"/>')
                body = []
                for image_index, image in enumerate(chapter_images, 1):
                    image_name = f"images/{index:04d}-{image_index:04d}{image.suffix.lower()}"
                    image_id = f"image-{index}-{image_index}"
                    manifest.append(
                        f'<item id="{image_id}" href="{image_name}" media-type="{_media_type(image)}"/>'
                    )
                    archive.write(image, f"OEBPS/{image_name}")
                    body.append(f'<img src="{html.escape(image_name)}" alt="Page {image_index}"/>')
                archive.writestr(
                    f"OEBPS/{page_name}",
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f"<title>{html.escape(chapter)}</title></head><body>"
                    + "".join(body)
                    + "</body></html>",
                )
                manifest.append(
                    f'<item id="{page_id}" href="{page_name}" media-type="application/xhtml+xml"/>'
                )
            title = html.escape(folder.name)
            archive.writestr(
                "OEBPS/content.opf",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
                'unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:identifier id="book-id">urn:uuid:mdl-'
                f"{html.escape(sanitize_folder_name(folder.name))}</dc:identifier>"
                f"<dc:title>{title}</dc:title><dc:language>und</dc:language></metadata>"
                '<manifest><item id="nav" href="nav.xhtml" properties="nav" '
                'media-type="application/xhtml+xml"/>'
                + "".join(manifest)
                + '</manifest><spine page-progression-direction="ltr">'
                + "".join(spine)
                + "</spine></package>",
            )
            archive.writestr(
                "OEBPS/nav.xhtml",
                '<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
                f'<nav epub:type="toc"><ol>{"".join(f'<li><a href="page-{i}.xhtml">{html.escape(chapter)}</a></li>' for i, (chapter, _) in enumerate(_chapter_groups(folder, images), 1))}</ol></nav>'
                "</body></html>",
            )
        _atomic_replace(pending, destination)
    finally:
        pending.unlink(missing_ok=True)
    _remove_archived_image_folders(str(folder), {str(path) for path in images})
    return str(destination)


def create_pdf(folder_path: str) -> str | None:
    """Create a PDF with one image per page, preserving download order."""
    folder = Path(folder_path).resolve()
    images = _image_files(folder) if folder.is_dir() else []
    if not images:
        return None
    pages: list[Image.Image] = []
    try:
        for path in images:
            with Image.open(path) as source:
                page = source.convert("RGB")
                pages.append(page.copy())
        destination = _output_path(folder, "pdf")
        fd, pending_name = tempfile.mkstemp(prefix=".pending_", suffix=".pdf", dir=folder)
        os.close(fd)
        pending = Path(pending_name)
        pending.unlink(missing_ok=True)
        try:
            pages[0].save(pending, "PDF", save_all=True, append_images=pages[1:], resolution=150)
            _atomic_replace(pending, destination)
        finally:
            pending.unlink(missing_ok=True)
        _remove_archived_image_folders(str(folder), {str(path) for path in images})
        return str(destination)
    finally:
        for page in pages:
            page.close()


def create_output_for_all(
    folder_path: str, output_format: str, *, cbz_layout: str = "series", **metadata
) -> str | None:
    """Create the selected output format for a downloaded manga folder."""
    if output_format == "cbz":
        if cbz_layout == "series":
            return create_cbz_for_all(folder_path, **metadata)
        if cbz_layout != "chapter":
            raise ValueError(f"Unsupported CBZ layout: {cbz_layout!r}")
        archives = create_cbz_per_chapter(folder_path, **metadata)
        return str(Path(folder_path).absolute()) if archives else None
    if output_format == "epub":
        return create_epub(folder_path)
    if output_format == "pdf":
        return create_pdf(folder_path)
    raise ValueError(f"Unsupported output format: {output_format!r}")


def create_selected_output(folder_path: str, output_format: str, **options) -> str | None:
    """Create output while retaining the established CBZ extension point."""
    return create_output_for_all(folder_path, output_format, **options)


def _media_type(path: Path) -> str:
    return {
        ".avif": "image/avif",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }[path.suffix.lower()]
