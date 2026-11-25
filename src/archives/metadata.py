"""ComicInfo metadata generation and atomic archive updates."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from xml.etree import ElementTree as ET

from rich.console import Console

from src.archives.ordering import _natural_key

console = Console()
CLEAN_OUTPUT = False
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _comic_info(metadata: dict, page_count: int, previous: bytes | None = None) -> bytes:
    try:
        root = ET.fromstring(previous) if previous else ET.Element("ComicInfo")
    except ET.ParseError as exc:
        raise ValueError(f"Existing ComicInfo.xml is invalid: {exc}") from exc
    for name, value in {**metadata, "PageCount": page_count}.items():
        if value is None or value == "":
            continue
        node = root.find(name)
        if node is None:
            node = ET.SubElement(root, name)
        node.text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def update_cbz(
    archive_path: str,
    files: dict[str, str],
    metadata: dict | None = None,
    *,
    archived_files: dict[str, tuple[str, str]] | None = None,
) -> None:
    """Merge pages atomically, preserving prior pages and ComicInfo fields on repair."""
    destination = Path(archive_path)
    if destination.is_symlink():
        raise ValueError(f"Cannot update a symlink archive: {destination}")
    fd, pending = tempfile.mkstemp(prefix=".pending_", suffix=".cbz", dir=destination.parent)
    os.close(fd)
    try:
        previous_metadata = None
        with ExitStack() as stack:
            entries = {}
            if destination.exists():
                previous = stack.enter_context(zipfile.ZipFile(destination))
                for entry in previous.infolist():
                    if entry.filename == "ComicInfo.xml" and metadata is not None:
                        previous_metadata = previous.read(entry)
                        continue
                    entries[entry.filename] = (previous, entry)
            sources = {}
            for name, (path, member) in (archived_files or {}).items():
                if path not in sources:
                    sources[path] = stack.enter_context(zipfile.ZipFile(path))
                entries[name] = (sources[path], sources[path].getinfo(member))
            names = set(entries) | set(files)
            target = stack.enter_context(
                zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6)
            )
            for name in sorted(names, key=_natural_key):
                if name in files:
                    target.write(files[name], arcname=name)
                else:
                    archive, entry = entries[name]
                    with archive.open(entry) as source, target.open(name, "w") as dest:
                        shutil.copyfileobj(source, dest)
            if metadata is not None:
                page_count = sum(Path(name).suffix.lower() in IMAGE_EXTENSIONS for name in names)
                target.writestr(
                    "ComicInfo.xml",
                    _comic_info(metadata, page_count, previous_metadata),
                )
        with zipfile.ZipFile(pending) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise zipfile.BadZipFile(f"Corrupt CBZ entry: {bad_entry}")
        os.replace(pending, destination)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
