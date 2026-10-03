"""Library integrity verification and URL-backed repair helpers."""

from __future__ import annotations

import asyncio
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from src.database.manga_db import get_latest_page_records
from src.utils import sanitize_folder_name

IMAGE_SUFFIXES = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True)
class VerificationIssue:
    path: str
    reason: str
    url: str | None = None
    folder: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    root: str
    checked: int
    issues: tuple[VerificationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def _image_data_problem(suffix: str, size: int, header: bytes, tail: bytes) -> str | None:
    """Check common image formats from their leading and trailing bytes."""
    if size == 0:
        return "empty file"
    if suffix in {".jpg", ".jpeg"} and not (
        header.startswith(b"\xff\xd8") and tail.endswith(b"\xff\xd9")
    ):
        return "invalid JPEG markers"
    if suffix == ".png" and not (header.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in tail):
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
    expected = {record["file_path"]: record for record in records}
    paths: dict[str, dict[str, str] | None] = {path: record for path, record in expected.items()}

    if not root_path.exists() and not paths:
        issue = VerificationIssue(str(root_path), "path does not exist")
        return VerificationReport(str(root_path), 0, (issue,))

    if root_path.is_file():
        paths.setdefault(str(root_path), None)
    elif root_path.is_dir():
        for path in root_path.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                paths.setdefault(str(path.resolve()), None)

    issues: list[VerificationIssue] = []
    archive_path = root_path / f"{sanitize_folder_name(root_path.name)}.cbz"
    archive = None
    if root_path.is_dir() and archive_path.exists():
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            issues.append(VerificationIssue(str(archive_path), f"unreadable archive: {exc}"))
    try:
        archived_names = set(archive.namelist()) if archive else set()
        for path_text, record in sorted(paths.items()):
            path = Path(path_text)
            url = record.get("url") if record else None
            folder = record.get("folder") if record else None
            if path.exists():
                problem = _image_problem(path)
            else:
                try:
                    archive_name = path.resolve().relative_to(root_path).as_posix()
                except ValueError:
                    archive_name = ""
                if archive_name in archived_names:
                    try:
                        data = archive.read(archive_name)
                        problem = _image_data_problem(
                            path.suffix.lower(), len(data), data[:32], data[-32:]
                        )
                    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                        problem = f"unreadable archive entry: {exc}"
                else:
                    problem = "missing file"
            if problem:
                issues.append(VerificationIssue(path_text, problem, url, folder))
    finally:
        if archive:
            archive.close()

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

    archive_path = Path(root) / f"{sanitize_folder_name(Path(root).name)}.cbz"
    if (
        archive_path.exists()
        and repairable
        and all(
            Path(issue.path).exists() and _image_problem(Path(issue.path)) is None
            for issue in repairable
        )
    ):
        from src.cbz import create_cbz_for_all

        await asyncio.to_thread(create_cbz_for_all, str(Path(root)))

    return before, verify_library(root)
