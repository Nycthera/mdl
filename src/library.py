"""Human-readable views of the saved library; these commands do not query sources."""

from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text

from src.database.manga_db import get_library_entries, get_library_entry


def _timestamp(value) -> str:
    return (
        datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M %Z") if value else "—"
    )


def print_library(console) -> None:
    entries = get_library_entries()
    if not entries:
        console.print("No tracked titles. Download a manga to add it to your library.")
        return
    table = Table(title="Library (saved status)")
    for heading in ("ID", "Title", "Source", "Local chapter", "Last run", "Last checked"):
        table.add_column(heading)
    for entry in entries:
        table.add_row(
            f"id:{entry['id']}",
            Text(entry["manga_name"]),
            entry["source_type"],
            f"{entry['latest_chapter_local']:g}",
            entry["run_status"] or "unrecorded",
            _timestamp(entry["date_last_checked"]),
        )
    console.print(table)


def print_library_status(console, selector: str) -> None:
    entry = get_library_entry(selector)
    output = entry["output_path"]
    fields = [
        ("ID", f"id:{entry['id']}"),
        ("Title", entry["manga_name"]),
        ("Source", entry["source_type"]),
        ("Source URL", entry["source_url"] or "—"),
        ("Language", entry["language"] or "unknown"),
        ("Local chapter", f"{entry['latest_chapter_local']:g}"),
        ("Last checked", _timestamp(entry["date_last_checked"])),
        ("Output folder", output or "not recorded"),
        ("Folder exists", str(Path(output).is_dir()) if output else "unknown"),
        ("Last run", entry["run_status"] or "unrecorded"),
    ]
    if entry["source_type"] == "mangadex":
        fields.append(
            ("Last recorded source chapter", f"{entry['latest_chapter_from_mangadex']:g}")
        )
    if entry["run_status"]:
        fields.extend(
            [
                ("Run started", _timestamp(entry["started_at"])),
                ("Run finished", _timestamp(entry["finished_at"])),
                ("Pages completed", f"{entry['successful_pages']}/{entry['total_pages']}"),
                ("Pages failed", str(entry["failed_pages"])),
            ]
        )
    table = Table(title="Saved library status", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for key, value in fields:
        table.add_row(key, Text(value))
    console.print(table)
