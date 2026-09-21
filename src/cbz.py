"""CBZ (Comic Book Archive) creation functionality."""

import os
import shutil
import tempfile
import zipfile

from rich.console import Console

from src.utils import sanitize_folder_name

console = Console()
CLEAN_OUTPUT = False


def set_clean_output(value: bool) -> None:
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def create_cbz_for_all(folder_path: str) -> str | None:
    """Atomically merge downloaded files into an archive, retaining source files.

    Older versions removed chapter folders after packaging. Preserve their
    archived entries when adding new chapters, and never truncate a good archive
    before its replacement has been completely written.
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
        with zipfile.ZipFile(pending, "w") as target:
            if os.path.exists(cbz_name):
                with zipfile.ZipFile(cbz_name) as previous:
                    for entry in previous.infolist():
                        if entry.filename not in files_to_add:
                            with previous.open(entry) as source, target.open(entry, "w") as dest:
                                shutil.copyfileobj(source, dest)
            for name, path in sorted(files_to_add.items()):
                target.write(path, arcname=name)
        os.replace(pending, cbz_name)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    if not CLEAN_OUTPUT:
        console.print(f"[magenta]Created {cbz_name}[/]")
    return cbz_name
