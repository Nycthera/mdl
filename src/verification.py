"""Library integrity verification and URL-backed repair helpers."""

from __future__ import annotations

import asyncio
import os
import time
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from src.cbz import index_cbz_pages
from src.database.manga_db import get_latest_page_records
from src.utils import sanitize_folder_name

IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class VerificationIssue:
    path: str
    reason: str
    url: str | None = None
    folder: str | None = None
    archive_path: str | None = None
    archive_name: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    root: str
    checked: int
    issues: tuple[VerificationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def _image_data_problem(
    suffix: str, size: int, header: bytes, tail: bytes
) -> str | None:
    """Check common image formats from their leading and trailing bytes."""
    if size == 0:
        return "empty file"
    if suffix in {".jpg", ".jpeg"} and not (
        header.startswith(b"\xff\xd8") and tail.endswith(b"\xff\xd9")
    ):
        return "invalid JPEG markers"
    if suffix == ".png" and not (
        header.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in tail
    ):
        return "invalid PNG markers"
    if suffix == ".gif" and not header.startswith((b"GIF87a", b"GIF89a")):
        return "invalid GIF header"
    if suffix == ".webp" and not (
        header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP"
    ):
        return "invalid WebP header"
    if suffix == ".bmp" and not header.startswith(b"BM"):
        return "invalid BMP header"
    if suffix == ".avif" and b"ftyp" not in header[:16]:
        return "invalid AVIF header"
    return None


def _image_problem(path: Path) -> str | None:
    """Return a concise corruption reason using dependency-free format checks."""
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(32)
            stream.seek(max(0, size - 32))
            tail = stream.read(32)
    except OSError as exc:
        return f"unreadable: {exc}"
    return _image_data_problem(path.suffix.lower(), size, header, tail)


def verify_library(root: str) -> VerificationReport:
    """Check known pages plus image files found below ``root``."""
    root_path = Path(root).expanduser().resolve()
    records = get_latest_page_records(str(root_path))
    expected = {str(Path(record["file_path"]).resolve()): record for record in records}
    paths: dict[str, dict[str, str] | None] = {
        path: record for path, record in expected.items()
    }

    if not root_path.exists() and not paths:
        issue = VerificationIssue(str(root_path), "path does not exist")
        return VerificationReport(str(root_path), 0, (issue,))

    if root_path.is_file():
        paths.setdefault(str(root_path), None)
    elif root_path.is_dir():
        for path in root_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                paths.setdefault(str(path.resolve()), None)

    archive_errors = []
    archived = (
        index_cbz_pages(str(root_path), errors=archive_errors)
        if root_path.is_dir()
        else {}
    )
    for path in archived:
        paths.setdefault(path, None)
    issues = [
        VerificationIssue(path, f"unreadable archive: {error}")
        for path, error in archive_errors
    ]
    with ExitStack() as stack:
        opened = {}
        for path_text, record in sorted(paths.items()):
            path = Path(path_text)
            url = record.get("url") if record else None
            folder = record.get("folder") if record else None
            archive_path, archive_name = archived.get(path_text, (None, None))
            if path.exists():
                problem = _image_problem(path)
            else:
                if archive_path:
                    try:
                        if archive_path not in opened:
                            opened[archive_path] = stack.enter_context(
                                zipfile.ZipFile(archive_path)
                            )
                        archive = opened[archive_path]
                        data = archive.read(archive_name)
                        problem = _image_data_problem(
                            path.suffix.lower(), len(data), data[:32], data[-32:]
                        )
                    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                        problem = f"unreadable archive entry: {exc}"
                else:
                    problem = "missing file"
            if problem:
                # A missing page can still belong to an existing archive.
                if archive_path is None and path.is_relative_to(root_path):
                    relative = path.relative_to(root_path)
                    chapter_archive = root_path / f"{relative.parts[0]}.cbz"
                    series_archive = (
                        root_path / f"{sanitize_folder_name(root_path.name)}.cbz"
                    )
                    if len(relative.parts) > 1 and chapter_archive.is_file():
                        archive_path = str(chapter_archive)
                        archive_name = Path(*relative.parts[1:]).as_posix()
                    elif series_archive.is_file():
                        archive_path, archive_name = (
                            str(series_archive),
                            relative.as_posix(),
                        )
                issues.append(
                    VerificationIssue(
                        path_text, problem, url, folder, archive_path, archive_name
                    )
                )

    return VerificationReport(str(root_path), len(paths), tuple(issues))


async def repair_library(
    root: str,
    *,
    workers: int = 10,
    max_retries: int = 5,
) -> tuple[VerificationReport, VerificationReport]:
    """Redownload missing/corrupt pages whose original URLs exist in history."""
    from src.downloader import download_all_pages

    before = verify_library(root)
    repairable = [issue for issue in before.issues if issue.url]
    backups: dict[str, str] = {}
    downloads: list[tuple[str, str]] = []

    for issue in repairable:
        path = Path(issue.path)
        if path.exists():
            backup = path.with_name(f".corrupt_{time.time_ns()}_{path.name}")
            os.replace(path, backup)
            backups[str(path)] = str(backup)
        downloads.append((str(issue.url), str(path.parent)))

    if downloads:
        await download_all_pages(
            downloads,
            max_workers=workers,
            manga_name=Path(root).name or "repair",
            track_to_db=False,
            track_history=False,
            max_retries=max_retries,
        )

    for original, backup in backups.items():
        try:
            if os.path.exists(original):
                os.remove(backup)
            elif os.path.exists(backup):
                os.replace(backup, original)
        except OSError:
            pass

    from src.cbz import _remove_archived_image_folders, update_cbz

    archive_repairs: dict[str, dict[str, str]] = {}
    for issue in repairable:
        if (
            issue.archive_path
            and issue.archive_name
            and Path(issue.path).exists()
            and _image_problem(Path(issue.path)) is None
        ):
            archive_repairs.setdefault(issue.archive_path, {})[
                issue.archive_name
            ] = issue.path
    archived_files = set()
    for archive_path, files in archive_repairs.items():
        await asyncio.to_thread(update_cbz, archive_path, files, {})
        archived_files.update(files.values())
    if archived_files:
        await asyncio.to_thread(
            _remove_archived_image_folders, str(Path(root).resolve()), archived_files
        )

    return before, verify_library(root)
