"""CBZ (Comic Book Archive) creation functionality."""

import os
import re
import shutil
import tempfile
import zipfile
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from rich.console import Console

from src.utils import sanitize_folder_name

console = Console()
CLEAN_OUTPUT = False
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _natural_key(value: str):
    return [
        Decimal(part) if index % 2 else part.casefold()
        for index, part in enumerate(re.split(r"(\d+(?:\.\d+)?)", value))
    ]


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
                    "ComicInfo.xml", _comic_info(metadata, page_count, previous_metadata)
                )
        with zipfile.ZipFile(pending) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise zipfile.BadZipFile(f"Corrupt CBZ entry: {bad_entry}")
        os.replace(pending, destination)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def set_clean_output(value: bool) -> None:
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def create_cbz_for_all(
    folder_path: str,
    *,
    series: str | None = None,
    language: str | None = None,
    reading_direction: str | None = None,
    source_url: str | None = None,
    chapter_metadata: dict[str, dict] | None = None,
) -> str | None:
    """Combine downloaded pages and chapter archives into one book with ComicInfo.

    Preserve existing chapters on updates. Source folders and chapter archives are
    removed only after the replacement book passes a CRC check.
    """
    base_folder = os.path.abspath(folder_path)
    if not os.path.isdir(base_folder) or os.path.islink(base_folder):
        return None
    if reading_direction not in (None, "rtl", "ltr"):
        raise ValueError("Reading direction must be rtl or ltr")
    cbz_name = os.path.join(
        base_folder, f"{sanitize_folder_name(os.path.basename(base_folder))}.cbz"
    )
    files_to_add = {}
    for root, dirs, files in os.walk(base_folder):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        for name in sorted(files):
            path = os.path.join(root, name)
            if (
                name.lower().endswith((".cbz", ".epub", ".pdf"))
                or name.startswith(".pending_")
                or os.path.islink(path)
            ):
                continue
            files_to_add[os.path.relpath(path, base_folder).replace(os.sep, "/")] = path

    archived_files, chapter_archives = _chapter_archive_files(
        Path(base_folder), Path(cbz_name), series=series
    )
    if not files_to_add and not archived_files:
        _remove_empty_chapter_folders(base_folder)
        return cbz_name if os.path.isfile(cbz_name) else None

    metadata = {
        "Title": series or os.path.basename(base_folder),
        "Series": series or os.path.basename(base_folder),
        "Web": source_url,
        "LanguageISO": language,
        "Manga": "YesAndRightToLeft" if reading_direction != "ltr" else "Yes",
    }
    update_cbz(cbz_name, files_to_add, metadata, archived_files=archived_files)
    if not CLEAN_OUTPUT:
        console.print(f"[magenta]Created {cbz_name}[/]")

    _remove_archived_image_folders(base_folder, set(files_to_add.values()))
    _remove_empty_chapter_folders(base_folder)
    for archive in chapter_archives:
        archive.unlink()
    return cbz_name


def _chapter_archive_files(
    base: Path, destination: Path, *, series: str | None = None
) -> tuple[dict[str, tuple[str, str]], list[Path]]:
    """Read MDL chapter archives without extracting or consuming unrelated outputs."""
    files = {}
    archives = []
    for path in sorted(base.glob("*.cbz"), key=lambda item: _natural_key(item.name)):
        if path == destination or path.is_symlink() or path.name.startswith("."):
            continue
        try:
            archive = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            if re.match(r"(?:chapter|episode)[_ -]*\d", path.stem, re.I):
                raise
            continue
        with archive:
            if "ComicInfo.xml" not in archive.namelist():
                continue
            info = ET.fromstring(archive.read("ComicInfo.xml"))
            if sanitize_folder_name(info.findtext("Series", "")) not in {
                sanitize_folder_name(base.name),
                sanitize_folder_name(series or base.name),
            }:
                continue
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not any(
                Path(entry.filename).suffix.lower() in IMAGE_EXTENSIONS for entry in entries
            ):
                continue
            for entry in entries:
                relative = PurePosixPath(entry.filename)
                if relative.is_absolute() or ".." in relative.parts or "\\" in entry.filename:
                    raise ValueError(f"Invalid entry in {path}: {entry.filename}")
                # Keep chapter metadata inside its chapter, alongside its pages.
                files[f"{path.stem}/{entry.filename}"] = (str(path), entry.filename)
            archives.append(path)
    return files, archives


def create_cbz_per_chapter(
    folder_path: str,
    *,
    series: str | None = None,
    language: str | None = None,
    reading_direction: str | None = None,
    source_url: str | None = None,
    chapter_metadata: dict[str, dict] | None = None,
) -> list[str]:
    """Create ``Series/chapter.cbz`` with images and ComicInfo.xml for each chapter.

    Existing series archives are retained. Empty or fully archived chapter folders
    are removed; pending files, sidecars and symlinks keep their folders intact.
    """
    base = Path(folder_path).absolute()
    if not base.is_dir() or base.is_symlink():
        return []
    if reading_direction not in (None, "rtl", "ltr"):
        raise ValueError("Reading direction must be rtl or ltr")
    archives = []
    for chapter in sorted(base.iterdir(), key=lambda path: _natural_key(path.name)):
        if not chapter.is_dir() or chapter.is_symlink():
            continue
        files = {}
        for root, dirs, filenames in os.walk(chapter):
            dirs[:] = sorted(d for d in dirs if not Path(root, d).is_symlink())
            for filename in filenames:
                path = Path(root, filename)
                if (
                    path.suffix.lower() in IMAGE_EXTENSIONS
                    and not path.name.startswith(".")
                    and not path.is_symlink()
                ):
                    files[path.relative_to(chapter).as_posix()] = str(path)
        if not files:
            continue
        destination = base / f"{chapter.name}.cbz"
        if destination.name == f"{sanitize_folder_name(base.name)}.cbz":
            raise ValueError(f"Chapter name conflicts with the series archive: {chapter.name}")
        match = re.match(r"(?:chapter|episode)[_ -]*(\d+(?:\.\d+)?)", chapter.name, re.I)
        # Reading direction and language can be overridden per source or chapter.
        metadata = {
            "Title": chapter.name.replace("_", " "),
            "Series": series or base.name,
            "Number": str(Decimal(match.group(1))) if match else None,
            "Web": source_url,
            "LanguageISO": language,
            "Manga": "YesAndRightToLeft" if reading_direction != "ltr" else "Yes",
            **(chapter_metadata or {}).get(chapter.name, {}),
        }
        update_cbz(str(destination), files, metadata)
        _remove_archived_image_folders(str(base), set(files.values()), folders=[chapter.name])
        archives.append(str(destination))
        if not CLEAN_OUTPUT:
            console.print(f"[magenta]Created {destination}[/]")
    _remove_empty_chapter_folders(str(base))
    return archives


def _remove_empty_chapter_folders(base_folder: str) -> None:
    """Prune empty chapter trees with rmdir, which never deletes file contents."""
    base = Path(base_folder)
    for chapter in base.iterdir():
        if not chapter.is_dir() or chapter.is_symlink() or chapter.name.startswith("."):
            continue
        if not (
            re.match(r"(?:chapter|episode)[_ -]*\d", chapter.name, re.I)
            or (base / f"{chapter.name}.cbz").is_file()
        ):
            continue
        for root, _, _ in os.walk(chapter, topdown=False, followlinks=False):
            try:
                os.rmdir(root)
            except OSError:
                # Files, pending downloads, or symlinks keep the directory intact.
                pass


def index_cbz_pages(
    root: str,
    *,
    folders: set[str] | None = None,
    errors: list[tuple[str, str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Map original page paths to chapter or legacy series CBZ entries without extracting."""
    base = Path(root).resolve()
    legacy = base / f"{sanitize_folder_name(base.name)}.cbz"
    candidates = [legacy]
    if folders is None:
        candidates += sorted(path for path in base.glob("*.cbz") if path != legacy)
    else:
        candidates += sorted({Path(str(Path(folder).resolve()) + ".cbz") for folder in folders})
    result = {}
    for path in dict.fromkeys(candidates):
        if not path.is_file() or path.is_symlink() or path.parent != base:
            continue
        prefix = base if path == legacy else base / path.stem
        try:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    relative = PurePosixPath(entry.filename)
                    if (
                        entry.is_dir()
                        or relative.is_absolute()
                        or ".." in relative.parts
                        or "\\" in entry.filename
                        or relative.suffix.lower() not in IMAGE_EXTENSIONS
                        or any(part.startswith(".") for part in relative.parts)
                    ):
                        continue
                    original = prefix.joinpath(*relative.parts).resolve()
                    if original.is_relative_to(base):
                        result[str(original)] = (str(path), entry.filename)
        except (OSError, zipfile.BadZipFile) as exc:
            if errors is not None:
                errors.append((str(path), str(exc)))
    return result


def _remove_archived_image_folders(
    base_folder: str, archived_files: set[str], *, folders: list[str] | None = None
) -> None:
    """Remove source folders only when every file was included in an output."""
    for name in sorted(os.listdir(base_folder) if folders is None else folders):
        folder = os.path.join(base_folder, name)
        if not os.path.isdir(folder) or os.path.islink(folder):
            continue
        files_in_folder = []
        safe_to_remove = True
        for root, dirs, files in os.walk(folder):
            if any(os.path.islink(os.path.join(root, entry)) for entry in dirs + files):
                safe_to_remove = False
                break
            files_in_folder.extend(os.path.join(root, entry) for entry in files)
        if not safe_to_remove or not files_in_folder:
            continue
        if not all(path in archived_files for path in files_in_folder):
            continue
        if not any(
            os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in files_in_folder
        ):
            continue
        try:
            shutil.rmtree(folder)
            if not CLEAN_OUTPUT:
                console.print(f"[green]Removed archived image folder {folder}[/]")
        except OSError as exc:
            console.print(f"[yellow]Could not remove archived image folder {folder}: {exc}[/]")
