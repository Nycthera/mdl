"""System utilities: updates and credits."""

import os
import platform
import shlex
import shutil
import subprocess
import sys
from typing import List, Dict, Union

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


def _check_command_exists(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    if shutil.which(cmd) is not None:
        return True
    console.print(f"[yellow]Command not available in PATH: {cmd}[/]")
    return False


def _run_command(
    cmd: Union[str, List[str]],
    description: str = "",
    cwd: str | None = None,
) -> bool:
    """Run a command and handle errors.

    Pass a list for ``shell=False`` (preferred); pass a string only when a
    shell built-in or shell feature is strictly required (``shell=True``).
    """
    if description:
        console.print(f"[cyan]{description}...[/]")
    use_shell = isinstance(cmd, str)
    try:
        subprocess.run(
            cmd,
            shell=use_shell,
            check=True,
            cwd=cwd,
        )
        return True
    except subprocess.CalledProcessError as e:
        display = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
        console.print(f"[red]✗ Command failed: {display}[/]")
        console.print(f"[red]  Error: {e}[/]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {e}[/]")
        return False


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt the user for a yes/no decision."""
    if not sys.stdin.isatty():
        return default

    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("[yellow]Please answer y or n.[/]")


def _ask_install_mode() -> str:
    """Prompt for dependency install mode."""
    if not sys.stdin.isatty():
        return "user"

    console.print("\n[bold cyan]Python install mode[/]")
    console.print("[white]1)[/] User site-packages (no venv)")
    console.print("[white]2)[/] Project venv at ./venv")
    while True:
        answer = input("Choose mode [1/2] (default 1): ").strip()
        if answer in {"", "1"}:
            return "user"
        if answer == "2":
            return "venv"
        console.print("[yellow]Please choose 1 or 2.[/]")


def _collect_update_options() -> dict[str, bool | str]:
    """Collect interactive choices for update/install actions."""
    mode = _ask_install_mode()
    return {
        "mode": mode,
        "python_deps": _ask_yes_no("Install Python dependencies", True),
        "playwright": _ask_yes_no("Install Playwright browsers", True),
        "node_deps": _ask_yes_no("Install API server (server/) Node dependencies", True),
        "cli_wrapper": _ask_yes_no("Install CLI wrapper command (mdl)", True),
    }


def _resolve_windows_python_cmd() -> List[str] | None:
    """Resolve Python launcher argv for Windows usage."""
    if _check_command_exists("py"):
        return ["py", "-3"]
    if _check_command_exists("python"):
        return ["python"]
    return None


def _setup_windows_python(mode: str, base_path: str, py_cmd: List[str]) -> List[str] | None:
    """Prepare Python argv list for Windows according to selected mode."""
    if mode == "venv":
        venv_path = os.path.join(base_path, "venv")
        if not os.path.exists(venv_path):
            if not _run_command([*py_cmd, "-m", "venv", venv_path], "Creating virtual environment"):
                return None
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        return [python_exe]
    return py_cmd


def _setup_unix_python(mode: str, base_path: str) -> List[str] | None:
    """Prepare Python argv list for Unix according to selected mode."""
    if mode == "venv":
        venv_path = os.path.join(base_path, "venv")
        if not os.path.exists(venv_path):
            if not _run_command(["python3", "-m", "venv", venv_path], "Creating virtual environment"):
                return None
        python_exe = os.path.join(venv_path, "bin", "python")
        return [python_exe]
    return ["python3"]


def _install_cli_wrapper_windows(base_path: str, py_cmd: List[str]) -> bool:
    """Install user-local CLI wrapper on Windows."""
    user_bin = os.path.join(os.path.expanduser("~"), "bin")
    os.makedirs(user_bin, exist_ok=True)
    wrapper_path = os.path.join(user_bin, "mdl.cmd")

    py_str = subprocess.list2cmdline(py_cmd)
    with open(wrapper_path, "w", encoding="utf-8") as wrapper:
        wrapper.write("@echo off\n")
        wrapper.write(f"{py_str} \"{os.path.join(base_path, 'main.py')}\" %*\n")

    console.print(f"[green]✓ CLI wrapper installed at {wrapper_path}[/]")
    return True


def _install_cli_wrapper_unix(base_path: str, py_cmd: List[str]) -> bool:
    """Install user-local CLI wrapper on Unix."""
    user_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    os.makedirs(user_bin, exist_ok=True)
    wrapper_path = os.path.join(user_bin, "mdl")

    py_str = " ".join(shlex.quote(p) for p in py_cmd)
    with open(wrapper_path, "w", encoding="utf-8") as wrapper:
        wrapper.write("#!/bin/bash\n")
        wrapper.write(f"exec {py_str} \"{os.path.join(base_path, 'main.py')}\" \"$@\"\n")

    os.chmod(wrapper_path, 0o755)
    console.print(f"[green]✓ CLI wrapper installed at {wrapper_path}[/]")
    return True


def update() -> None:
    """Update the application and its dependencies."""
    os_name = platform.system().lower()
    base_path = os.getcwd()
    
    console.print(Panel.fit(
        f"[bold cyan]MDL Dependency Update[/]\n[yellow]Base path: {base_path}[/]",
        border_style="cyan",
        title="[white on cyan] Setup [/]"
    ))

    options = _collect_update_options()

    if os_name == "windows":
        _update_windows(base_path, options)
    else:
        _update_unix(base_path, options)


def _update_windows(base_path: str, options: dict[str, bool | str]) -> None:
    """Update dependencies on Windows."""
    console.print("\n[bold cyan]Setting up for Windows...[/]\n")
    
    # Check Python launcher
    py_cmd = _resolve_windows_python_cmd()

    if not py_cmd:
        console.print("[red]✗ Error: Python is not installed or not in PATH[/]")
        console.print("[yellow]  Install from https://www.python.org/downloads/[/]")
        return

    run_py = _setup_windows_python(str(options["mode"]), base_path, py_cmd)
    if not run_py:
        return

    console.print(f"[green]✓ Python found (mode={options['mode']})[/]")

    has_npm = _check_command_exists("npm")
    if has_npm:
        console.print("[green]✓ Node.js found[/]\n")
    else:
        console.print("[yellow]⚠ Node.js not found. API server (server/) setup will be skipped[/]\n")
    
    if options["python_deps"]:
        if not _run_command([*run_py, "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip"):
            return

        if options["mode"] == "venv":
            pip_cmd = [*run_py, "-m", "pip", "install", "-r", req_path]
        else:
            pip_cmd = [*run_py, "-m", "pip", "install", "--user", "-r", req_path]
        if not _run_command(pip_cmd, "Installing Python dependencies"):
            return
        console.print("[green]✓ Python dependencies installed[/]\n")

    if options["playwright"]:
        if not _run_command([*run_py, "-m", "playwright", "install"], "Installing Playwright browsers"):
            return
        console.print("[green]✓ Playwright browsers installed[/]\n")

    # Setup API server (server/ submodule)
    manga_api_path = os.path.join(base_path, "server")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if options["node_deps"] and has_npm and os.path.exists(package_json_path):
        if not _run_command(["npm", "install"], "Installing Node.js dependencies", cwd=manga_api_path):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    elif options["node_deps"] and not has_npm and os.path.exists(package_json_path):
        console.print("[yellow]⚠ npm not found, skipping server/ setup[/]\n")
    elif options["node_deps"]:
        console.print("[yellow]⚠ server/package.json not found, skipping npm setup[/]\n")

    if options["cli_wrapper"]:
        _install_cli_wrapper_windows(base_path, run_py)

    _print_completion_message("windows", str(options["mode"]))


def _update_unix(base_path: str, options: dict[str, bool | str]) -> None:
    """Update dependencies on Unix-like systems (macOS, Linux)."""
    console.print("\n[bold cyan]Setting up for Unix/Linux (macOS, Linux)...[/]\n")
    
    # Check Python 3
    if not _check_command_exists("python3"):
        console.print("[red]✗ Error: python3 is not installed[/]")
        console.print("[yellow]  macOS: brew install python[/]")
        console.print("[yellow]  Linux: sudo apt-get install python3 python3-pip[/]")
        return

    run_py = _setup_unix_python(str(options["mode"]), base_path)
    if not run_py:
        return

    console.print(f"[green]✓ Python found (mode={options['mode']})[/]")

    has_npm = _check_command_exists("npm")
    if has_npm:
        console.print("[green]✓ Node.js found[/]\n")
    else:
        console.print("[yellow]⚠ Node.js not found. API server (server/) setup will be skipped[/]\n")
    
    if options["python_deps"]:
        if not _run_command([*run_py, "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip"):
            return

        req_path = os.path.join(base_path, "requirements.txt")
        if options["mode"] == "venv":
            pip_cmd = [*run_py, "-m", "pip", "install", "-r", req_path]
        else:
            pip_cmd = [*run_py, "-m", "pip", "install", "--user", "-r", req_path]
        if not _run_command(pip_cmd, "Installing Python dependencies"):
            return
        console.print("[green]✓ Python dependencies installed[/]\n")

    if options["playwright"]:
        if not _run_command([*run_py, "-m", "playwright", "install"], "Installing Playwright browsers"):
            return
        console.print("[green]✓ Playwright browsers installed[/]\n")

    # Setup API server (server/ submodule)
    manga_api_path = os.path.join(base_path, "server")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if options["node_deps"] and has_npm and os.path.exists(package_json_path):
        if not _run_command(["npm", "install"], "Installing Node.js dependencies", cwd=manga_api_path):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    elif options["node_deps"] and not has_npm and os.path.exists(package_json_path):
        console.print("[yellow]⚠ npm not found, skipping server/ setup[/]\n")
    elif options["node_deps"]:
        console.print("[yellow]⚠ server/package.json not found, skipping npm setup[/]\n")

    if options["cli_wrapper"]:
        _install_cli_wrapper_unix(base_path, run_py)

    _print_completion_message("unix", str(options["mode"]))


def _print_completion_message(os_name: str, mode: str) -> None:
    """Print completion message with next steps."""
    mode_line = "[yellow]Mode: user site-packages (no venv)[/]"
    if mode == "venv":
        mode_line = (
            "[yellow]Mode: venv (activate with call venv\\Scripts\\activate)[/]"
            if os_name == "windows"
            else "[yellow]Mode: venv (activate with source venv/bin/activate)[/]"
        )

    console.print(Panel(
        "[bold green]✓ Installation Complete![/]\n"
        "[cyan]Next steps:[/]\n"
        f"{mode_line}\n"
        "[yellow]1. Run manga downloader: python main.py -M manga-name[/]\n"
        "[yellow]2. (Optional) Start API: cd server && npm start[/]\n"
        "[cyan]For more info: python main.py --help[/]",
        border_style="green",
        title="[white on green] Ready [/]"
    ))

