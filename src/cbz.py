"""CBZ (Comic Book Archive) creation functionality."""

import os
import shutil
import tempfile
import zipfile

from rich.console import Console

from src.utils import sanitize_folder_name

console = Console()
CLEAN_OUTPUT = False
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def set_clean_output(value: bool) -> None:
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def create_cbz_for_all(folder_path: str) -> str | None:
    """Atomically merge downloaded files and remove archived image folders.

    Preserve chapters already in an existing archive when adding new ones. Source
    folders are removed only after the replacement archive passes a CRC check.
    """
    base_folder = os.path.abspath(folder_path)
    if not os.path.isdir(base_folder):
        return None
    cbz_name = os.path.join(
        base_folder, f"{sanitize_folder_name(os.path.basename(base_folder))}.cbz"
    )
    files_to_add = {}
    for root, dirs, files in os.walk(base_folder):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        for name in sorted(files):
            path = os.path.join(root, name)
            if (
                name.lower().endswith(".cbz")
                or name.startswith(".pending_")
                or os.path.islink(path)
            ):
                continue
            files_to_add[os.path.relpath(path, base_folder).replace(os.sep, "/")] = path
    if not files_to_add:
        return None

    fd, pending = tempfile.mkstemp(prefix=".pending_", suffix=".cbz", dir=base_folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(
            pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as target:
            if os.path.exists(cbz_name):
                with zipfile.ZipFile(cbz_name) as previous:
                    for entry in previous.infolist():
                        if entry.filename not in files_to_add:
                            with previous.open(entry) as source, target.open(entry, "w") as dest:
                                shutil.copyfileobj(source, dest)
            for name, path in sorted(files_to_add.items()):
                target.write(path, arcname=name)
        with zipfile.ZipFile(pending) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                raise zipfile.BadZipFile(f"Corrupt CBZ entry: {bad_entry}")
        os.replace(pending, cbz_name)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    if not CLEAN_OUTPUT:
        console.print(f"[magenta]Created {cbz_name}[/]")

    # Remove only folders containing archived images. Keep folders with pending
    # downloads, symlinks, or any other file that was excluded from the archive.
    archived_files = set(files_to_add.values())
    for name in sorted(os.listdir(base_folder)):
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
    return cbz_name
