"""System utilities: updates and credits."""

import os
import platform
import subprocess
from typing import List, Dict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def credits(show: bool = False) -> List[Dict[str, str]]:
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

    return entries


def _check_command_exists(cmd: str, check_cmd: str) -> bool:
    """Check if a command is available in PATH."""
    try:
        subprocess.run(
            check_cmd, 
            shell=True, 
            check=True, 
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _run_command(cmd: str, description: str = "", shell_executable: str | None = None) -> bool:
    """Run a shell command and handle errors."""
    if description:
        console.print(f"[cyan]{description}...[/]")
    
    try:
        subprocess.run(
            cmd, 
            shell=True, 
            executable=shell_executable,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]✗ Command failed: {cmd}[/]")
        console.print(f"[red]  Error: {e}[/]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {e}[/]")
        return False


def update() -> None:
    """Update the application and its dependencies."""
    os_name = platform.system().lower()
    base_path = os.getcwd()
    
    console.print(Panel.fit(
        f"[bold cyan]MDL Dependency Update[/]\n[yellow]Base path: {base_path}[/]",
        border_style="cyan",
        title="[white on cyan] Setup [/]"
    ))

    if os_name == "windows":
        _update_windows(base_path)
    else:
        _update_unix(base_path)


def _update_windows(base_path: str) -> None:
    """Update dependencies on Windows."""
    console.print("\n[bold cyan]Setting up for Windows...[/]\n")
    
    # Check Python
    if not _check_command_exists("python", "where python"):
        console.print("[red]✗ Error: Python is not installed or not in PATH[/]")
        console.print("[yellow]  Install from https://www.python.org/downloads/[/]")
        return

    console.print("[green]✓ Python found[/]")

    # Check Node.js
    if not _check_command_exists("npm", "where npm"):
        console.print("[red]✗ Error: Node.js is not installed or not in PATH[/]")
        console.print("[yellow]  Install from https://nodejs.org/[/]")
        return

    console.print("[green]✓ Node.js found[/]\n")

    # Create venv if missing
    venv_path = os.path.join(base_path, "venv")
    if not os.path.exists(venv_path):
        if not _run_command("python -m venv venv", "Creating Python virtual environment"):
            return
        console.print("[green]✓ Virtual environment created[/]\n")

    python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")
    
    # Upgrade pip
    if not _run_command(f'"{python_exe}" -m pip install --upgrade pip', "Upgrading pip"):
        return

    # Install Python dependencies
    req_path = os.path.join(base_path, "requirements.txt")
    if not _run_command(f'"{pip_exe}" install -r "{req_path}"', "Installing Python dependencies"):
        return

    console.print("[green]✓ Python dependencies installed[/]\n")

    # Install Playwright browsers
    if not _run_command(f'"{python_exe}" -m playwright install', "Installing Playwright browsers"):
        return

    console.print("[green]✓ Playwright browsers installed[/]\n")

    # Setup Manga-API
    manga_api_path = os.path.join(base_path, "Manga-API")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if os.path.exists(package_json_path):
        if not _run_command(f'cd "{manga_api_path}" && npm install', "Installing Node.js dependencies"):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    else:
        console.print("[yellow]⚠ Manga-API/package.json not found, skipping npm setup[/]\n")

    _print_completion_message("windows")


def _update_unix(base_path: str) -> None:
    """Update dependencies on Unix-like systems (macOS, Linux)."""
    console.print("\n[bold cyan]Setting up for Unix/Linux (macOS, Linux)...[/]\n")
    
    # Check Python 3
    if not _check_command_exists("python3", "command -v python3"):
        console.print("[red]✗ Error: python3 is not installed[/]")
        console.print("[yellow]  macOS: brew install python[/]")
        console.print("[yellow]  Linux: sudo apt-get install python3 python3-venv[/]")
        return

    console.print("[green]✓ Python found[/]")

    # Check Node.js
    if not _check_command_exists("npm", "command -v npm"):
        console.print("[red]✗ Error: Node.js is not installed[/]")
        console.print("[yellow]  Install from https://nodejs.org/ or use your package manager[/]")
        return

    console.print("[green]✓ Node.js found[/]\n")

    # Create venv if missing
    venv_path = os.path.join(base_path, "venv")
    if not os.path.exists(venv_path):
        if not _run_command("python3 -m venv venv", "Creating Python virtual environment", "/bin/bash"):
            return
        console.print("[green]✓ Virtual environment created[/]\n")

    python_exe = os.path.join(venv_path, "bin", "python")
    pip_exe = os.path.join(venv_path, "bin", "pip")
    
    # Upgrade pip
    if not _run_command(f'"{python_exe}" -m pip install --upgrade pip', "Upgrading pip", "/bin/bash"):
        return

    # Install Python dependencies
    req_path = os.path.join(base_path, "requirements.txt")
    if not _run_command(f'"{pip_exe}" install -r "{req_path}"', "Installing Python dependencies", "/bin/bash"):
        return

    console.print("[green]✓ Python dependencies installed[/]\n")

    # Install Playwright browsers
    if not _run_command(f'"{python_exe}" -m playwright install', "Installing Playwright browsers", "/bin/bash"):
        return

    console.print("[green]✓ Playwright browsers installed[/]\n")

    # Setup Manga-API
    manga_api_path = os.path.join(base_path, "Manga-API")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if os.path.exists(package_json_path):
        if not _run_command(f'cd "{manga_api_path}" && npm install', "Installing Node.js dependencies", "/bin/bash"):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    else:
        console.print("[yellow]⚠ Manga-API/package.json not found, skipping npm setup[/]\n")

    _print_completion_message("unix")


def _print_completion_message(os_name: str) -> None:
    """Print completion message with next steps."""
    console.print(Panel(
        "[bold green]✓ Installation Complete![/]\n"
        "[cyan]Next steps:[/]\n"
        f"{'[yellow]1. Activate venv: call venv\\Scripts\\activate[/]' if os_name == 'windows' else '[yellow]1. Activate venv: source venv/bin/activate[/]'}\n"
        "[yellow]2. Run manga downloader: python main.py -M manga-name[/]\n"
        "[yellow]3. (Optional) Start API: cd Manga-API && npm start[/]\n"
        "[cyan]For more info: python main.py --help[/]",
        border_style="green",
        title="[white on green] Ready [/]"
    ))

