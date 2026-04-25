"""System utilities: updates and credits."""

import os
import platform
import shlex
import shutil
import subprocess
import sys
from typing import List, Dict, Union

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
                    f"- {item['name']} "
                    f"({item['category']}): {item['description']} "
                    f"[{item['url']}]"
                )

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
    console.print("[white]2)[/] Managed venv in installed app directory")
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


def _get_install_root_windows() -> str:
    """Get user-local install root for Windows."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, "mdl")
    return os.path.join(os.path.expanduser("~"), "AppData", "Local", "mdl")


def _get_install_root_unix() -> str:
    """Get user-local install root for Unix-like systems."""
    return os.path.join(os.path.expanduser("~"), ".local", "share", "mdl")


def _sync_installed_app(base_path: str, install_root: str, include_server: bool) -> str | None:
    """Copy runnable project files to a managed install directory."""
    app_path = os.path.join(install_root, "app")

    try:
        os.makedirs(install_root, exist_ok=True)
        if os.path.exists(app_path):
            shutil.rmtree(app_path)
        os.makedirs(app_path, exist_ok=True)

        required_files = ["main.py", "requirements.txt"]
        required_dirs = ["src"]

        for filename in required_files:
            src_path = os.path.join(base_path, filename)
            if not os.path.exists(src_path):
                console.print(f"[red]✗ Missing required file: {src_path}[/]")
                return None
            shutil.copy2(src_path, os.path.join(app_path, filename))

        for dirname in required_dirs:
            src_dir = os.path.join(base_path, dirname)
            if not os.path.isdir(src_dir):
                console.print(f"[red]✗ Missing required directory: {src_dir}[/]")
                return None
            shutil.copytree(
                src_dir,
                os.path.join(app_path, dirname),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

        if include_server:
            src_dir = os.path.join(base_path, "server")
            if os.path.isdir(src_dir):
                shutil.copytree(
                    src_dir,
                    os.path.join(app_path, "server"),
                    ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc"),
                )

        console.print(f"[green]✓ Installed app copy prepared at {app_path}[/]")
        return app_path
    except Exception as e:
        console.print(f"[red]✗ Failed to prepare installed app copy: {e}[/]")
        return None


def _setup_windows_python(mode: str, install_root: str, py_cmd: List[str]) -> List[str] | None:
    """Prepare Python argv list for Windows according to selected mode."""
    if mode == "venv":
        venv_path = os.path.join(install_root, "venv")
        if not os.path.exists(venv_path):
            if not _run_command([*py_cmd, "-m", "venv", venv_path], "Creating virtual environment"):
                return None
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        return [python_exe]
    return py_cmd


def _setup_unix_python(mode: str, install_root: str) -> List[str] | None:
    """Prepare Python argv list for Unix according to selected mode."""
    if mode == "venv":
        venv_path = os.path.join(install_root, "venv")
        if not os.path.exists(venv_path):
            if not _run_command(["python3", "-m", "venv", venv_path], "Creating virtual environment"):
                return None
        python_exe = os.path.join(venv_path, "bin", "python")
        return [python_exe]
    return ["python3"]


def _install_cli_wrapper_windows(app_path: str, py_cmd: List[str]) -> bool:
    """Install user-local CLI wrapper on Windows."""
    user_bin = os.path.join(os.path.expanduser("~"), "bin")
    os.makedirs(user_bin, exist_ok=True)
    wrapper_path = os.path.join(user_bin, "mdl.cmd")

    py_str = subprocess.list2cmdline(py_cmd)
    with open(wrapper_path, "w", encoding="utf-8") as wrapper:
        wrapper.write("@echo off\n")
        wrapper.write(f"{py_str} \"{os.path.join(app_path, 'main.py')}\" %*\n")

    console.print(f"[green]✓ CLI wrapper installed at {wrapper_path}[/]")
    return True


def _install_cli_wrapper_unix(app_path: str, py_cmd: List[str]) -> bool:
    """Install user-local CLI wrapper on Unix."""
    user_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    os.makedirs(user_bin, exist_ok=True)
    wrapper_path = os.path.join(user_bin, "mdl")

    py_str = " ".join(shlex.quote(p) for p in py_cmd)
    with open(wrapper_path, "w", encoding="utf-8") as wrapper:
        wrapper.write("#!/bin/bash\n")
        wrapper.write(f"exec {py_str} \"{os.path.join(app_path, 'main.py')}\" \"$@\"\n")

    os.chmod(wrapper_path, 0o755)
    console.print(f"[green]✓ CLI wrapper installed at {wrapper_path}[/]")
    return True


def _resolve_project_base_path() -> str:
    """Resolve the MDL project root regardless of caller CWD."""
    candidates = [
        os.path.dirname(os.path.abspath(sys.argv[0])),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]

    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, "requirements.txt")):
            return candidate

    return candidates[0]


def update() -> None:
    """Update the application and its dependencies."""
    os_name = platform.system().lower()
    base_path = _resolve_project_base_path()
    
    console.print(Panel.fit(
        f"[bold cyan]MDL Dependency Update[/]\n[yellow]Base path: {base_path}[/]",
        border_style="cyan",
        title="[white on cyan] Setup [/]"
    ))

    options = _collect_update_options()
    install_root = _get_install_root_windows() if os_name == "windows" else _get_install_root_unix()
    app_path = _sync_installed_app(base_path, install_root, include_server=bool(options["node_deps"]))
    if not app_path:
        return

    if os_name == "windows":
        _update_windows(app_path, install_root, options)
    else:
        _update_unix(app_path, install_root, options)


def _update_windows(app_path: str, install_root: str, options: dict[str, bool | str]) -> None:
    """Update dependencies on Windows."""
    console.print("\n[bold cyan]Setting up for Windows...[/]\n")
    
    # Check Python launcher
    py_cmd = _resolve_windows_python_cmd()

    if not py_cmd:
        console.print("[red]✗ Error: Python is not installed or not in PATH[/]")
        console.print("[yellow]  Install from https://www.python.org/downloads/[/]")
        return

    run_py = _setup_windows_python(str(options["mode"]), install_root, py_cmd)
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

        req_path = os.path.join(app_path, "requirements.txt")
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

    # Setup API server in the server/ directory
    manga_api_path = os.path.join(app_path, "server")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if options["node_deps"] and has_npm and os.path.exists(package_json_path):
        if not _run_command(["npm", "install"], "Installing Node.js dependencies", cwd=manga_api_path):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    elif options["node_deps"] and not has_npm and os.path.exists(package_json_path):
        console.print("[yellow]⚠ npm not found, skipping server/ setup[/]\n")
    elif options["node_deps"]:
        console.print("[yellow]⚠ server/package.json not found, skipping npm setup[/]\n")

    if options["cli_wrapper"]:
        _install_cli_wrapper_windows(app_path, run_py)

    _print_completion_message("windows", str(options["mode"]), install_root)


def _update_unix(app_path: str, install_root: str, options: dict[str, bool | str]) -> None:
    """Update dependencies on Unix-like systems (macOS, Linux)."""
    console.print("\n[bold cyan]Setting up for Unix/Linux (macOS, Linux)...[/]\n")
    
    # Check Python 3
    if not _check_command_exists("python3"):
        console.print("[red]✗ Error: python3 is not installed[/]")
        console.print("[yellow]  macOS: brew install python[/]")
        console.print("[yellow]  Linux: sudo apt-get install python3 python3-pip[/]")
        return

    run_py = _setup_unix_python(str(options["mode"]), install_root)
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

        req_path = os.path.join(app_path, "requirements.txt")
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

    # Setup API server (server/ directory)
    manga_api_path = os.path.join(app_path, "server")
    package_json_path = os.path.join(manga_api_path, "package.json")
    
    if options["node_deps"] and has_npm and os.path.exists(package_json_path):
        if not _run_command(["npm", "install"], "Installing Node.js dependencies", cwd=manga_api_path):
            console.print("[yellow]⚠ Node.js setup failed, but Python CLI will still work[/]\n")
    elif options["node_deps"] and not has_npm and os.path.exists(package_json_path):
        console.print("[yellow]⚠ npm not found, skipping server/ setup[/]\n")
    elif options["node_deps"]:
        console.print("[yellow]⚠ server/package.json not found, skipping npm setup[/]\n")

    if options["cli_wrapper"]:
        _install_cli_wrapper_unix(app_path, run_py)

    _print_completion_message("unix", str(options["mode"]), install_root)


def _print_completion_message(os_name: str, mode: str, install_root: str) -> None:
    """Print completion message with next steps."""
    venv_path = os.path.join(install_root, "venv")
    app_path = os.path.join(install_root, "app")

    mode_line = "[yellow]Mode: user site-packages (no venv)[/]"
    if mode == "venv":
        activate_cmd = (
            f"call {os.path.join(venv_path, 'Scripts', 'activate')}"
            if os_name == "windows"
            else f"source {os.path.join(venv_path, 'bin', 'activate')}"
        )
        mode_line = f"[yellow]Mode: venv (activate with {activate_cmd})[/]"

    console.print(Panel(
        "[bold green]✓ Installation Complete![/]\n"
        f"[cyan]Install location: {install_root}[/]\n"
        "[cyan]Next steps:[/]\n"
        f"{mode_line}\n"
        f"[yellow]1. Run manga downloader: python {os.path.join(app_path, 'main.py')} -M manga-name[/]\n"
        "[yellow]2. (Optional) Start API: cd server && npm start[/]\n"
        f"[cyan]For more info: python {os.path.join(app_path, 'main.py')} --help[/]",
        border_style="green",
        title="[white on green] Ready [/]"
    ))

