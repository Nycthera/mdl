"""CBZ (Comic Book Archive) creation functionality."""

import os
import zipfile
from rich.console import Console

from src.utils import sanitize_folder_name

console = Console()

# Global state
CLEAN_OUTPUT = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def create_cbz_for_all(folder_path: str) -> str | None:
    """Create a CBZ archive from the folder structure."""
    base_folder = os.path.abspath(folder_path)

    # Defensive checks: folder must exist and have files to archive
    if not os.path.isdir(base_folder):
        if not CLEAN_OUTPUT:
            console.print(
                f"[red]Folder does not exist, skipping CBZ creation: {base_folder}[/]"
            )
        return None

    # Ensure there's at least one file (excluding existing .cbz) to archive
    has_files = False
    for root, dirs, files in os.walk(base_folder):
        for f in files:
            if not f.lower().endswith(".cbz"):
                has_files = True
                break
        if has_files:
            break

    if not has_files:
        if not CLEAN_OUTPUT:
            console.print(
                f"[red]No files found in {base_folder}; skipping CBZ creation.[/]"
            )
        return None

    base_name = os.path.basename(base_folder)
    safe_base_name = sanitize_folder_name(base_name)
    # Place the CBZ inside the manga root folder
    cbz_name = os.path.join(base_folder, f"{safe_base_name}.cbz")
    if not CLEAN_OUTPUT:
        console.print(f"[magenta]Creating CBZ archive: {cbz_name}[/]")

    # Create the CBZ
    with zipfile.ZipFile(cbz_name, "w") as cbz:
        for root, dirs, files in os.walk(base_folder):
            files = sorted(files)
            for file in files:
                file_path = os.path.join(root, file)
                # avoid adding the cbz itself if it's inside the folder
                if os.path.abspath(file_path) == os.path.abspath(cbz_name):
                    continue
                arcname = os.path.relpath(file_path, base_folder)
                cbz.write(file_path, arcname=arcname)

    if not CLEAN_OUTPUT:
        console.print(f"[magenta]Created {cbz_name}[/]")

    # Delete only subfolders (per chapter folders) inside the manga root folder
    for item in os.listdir(base_folder):
        item_path = os.path.join(base_folder, item)
        # don't remove the generated cbz file
        if item.lower().endswith(".cbz"):
            continue
        if os.path.isdir(item_path):
            try:
                import shutil
                shutil.rmtree(item_path)
                if not CLEAN_OUTPUT:
                    console.print(f"[green]Deleted folder {item_path}[/]")
            except Exception as e:
                if not CLEAN_OUTPUT:
                    console.print(f"[red]Failed to delete {item_path}: {e}[/]")

    return cbz_name
