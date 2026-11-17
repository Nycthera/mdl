"""System utilities: updates and credits."""

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except Exception:  # ImportError and any other issues loading Rich
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]

_RICH_AVAILABLE = Console is not None

if _RICH_AVAILABLE:
    console = Console()
else:

    class _PlainConsole:
        """Minimal console fallback when Rich is unavailable."""

        def print(self, *args, **kwargs) -> None:  # noqa: D401
            # Ignore Rich-specific markup and styles; just print text.
            text = " ".join(str(a) for a in args)
            print(text)

    console = _PlainConsole()


def credits(show: bool = False) -> list[dict[str, str]]:
    """Return a structured list of credits. Optionally print a table."""
    entries = [
        {
            "name": "WeebCentral",
            "url": "https://weebcentral.com/",
            "description": "Manga hosting site used as a scraping source.",
            "category": "Site",
        },
        {
            "name": "MangaDex",
            "url": "https://mangadex.org/",
            "description": "Official API source for direct, reliable downloads.",
            "category": "API",
        },
        {
            "name": "Playwright",
            "url": "https://playwright.dev/",
            "description": "Browser automation used to capture dynamic image URLs.",
            "category": "Library",
        },
    ]

    if show:
        if _RICH_AVAILABLE:
            table = Table(title="Credits")
            table.add_column("Name", style="cyan", no_wrap=True)
            table.add_column("Category", style="magenta", no_wrap=True)
            table.add_column("Description", style="white")
            table.add_column("URL", style="green")
            for item in entries:
                table.add_row(
                    item["name"],
                    item["category"],
                    item["description"],
                    item["url"],
                )
            console.print(Panel.fit(table, border_style="cyan"))
        else:
            # Fallback plain-text credits when Rich is unavailable.
            console.print("Credits:")
            for item in entries:
                console.print(
                    f"- {item['name']} ({item['category']}): {item['description']} [{item['url']}]"
                )

    return entries


def _resolve_project_root() -> Path:
    """Resolve the MDL project root regardless of the caller's directory."""
    candidates = [
        Path(sys.argv[0]).resolve().parent,
        Path(__file__).resolve().parents[1],
    ]
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return candidates[0]


def update() -> None:
    """Synchronize the locked project environment with uv."""
    project_root = _resolve_project_root()
    if shutil.which("uv") is None:
        console.print("[red]uv is required. Install it from https://docs.astral.sh/uv/[/]")
        return

    console.print(f"[cyan]Syncing dependencies in {project_root}...[/]")
    try:
        subprocess.run(["uv", "sync", "--locked"], cwd=project_root, check=True)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Dependency sync failed with exit code {exc.returncode}.[/]")
        return

    console.print("[green]Dependencies are synchronized.[/]")
    console.print("[cyan]Run with: uv run python main.py --help[/]")
