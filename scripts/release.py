#!/usr/bin/env python3
"""Validate release versions and build the single-file release assets."""

import argparse
import ast
import hashlib
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "__init__.py"
PROJECT_FILE = ROOT / "pyproject.toml"
# SemVer without build metadata: each version has exactly one release tag.
VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


def read_version(path: Path = VERSION_FILE) -> str:
    """Read the literal version without importing application dependencies."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError("src/__init__.py must define one literal __version__ string")
    version = values[0]
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        raise ValueError(f"Invalid version {version!r}; use X.Y.Z or X.Y.Z-rc.1")
    if match[1] and any(
        part.isdigit() and len(part) > 1 and part.startswith("0") for part in match[1].split(".")
    ):
        raise ValueError("Numeric prerelease identifiers cannot have leading zeros")
    return version


def validate_tag(version: str, tag: str) -> None:
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(
            f"Tag {tag!r} does not match __version__={version!r}; expected {expected!r}"
        )


def validate_project_version(version: str, path: Path = PROJECT_FILE) -> None:
    """Require project metadata and application source to use the same version."""
    with path.open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]
    if project_version != version:
        raise ValueError(
            f"pyproject.toml version {project_version!r} does not match __version__={version!r}"
        )


def build_assets(output: Path, version: str) -> None:
    """Build, smoke-test independently of the checkout, and hash exact assets."""
    builder = runpy.run_path(str(ROOT / "install_single.py"))["build"]
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / "mdl.py"
    builder(bundle)
    with tempfile.TemporaryDirectory(prefix="mdl-release-") as directory:
        isolated = Path(directory) / "mdl.py"
        shutil.copyfile(bundle, isolated)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["HOME"] = str(Path(directory) / "home")
        result = subprocess.run(
            [sys.executable, "-I", str(isolated), "--clean-output", "--version"],
            cwd=directory,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        # First-run config creation may print a message before argparse's version.
        if result.stdout.strip().splitlines()[-1] != f"mdl.py {version}":
            raise ValueError(f"Bundle reports an unexpected version: {result.stdout!r}")
        subprocess.run(
            [sys.executable, "-I", str(isolated), "--help"],
            cwd=directory,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    for name in ("pyproject.toml", "uv.lock", "LICENSE"):
        shutil.copyfile(ROOT / name, output / name)
    (output / "INSTALL.txt").write_text(
        f"MDL v{version}\n\n"
        "Requires uv and Python 3.13+. Keep mdl.py, pyproject.toml, and uv.lock together.\n"
        "Install the locked runtime dependencies and run MDL:\n"
        "  uv sync --locked --no-dev\n"
        "  uv run --no-dev python mdl.py --help\n"
        "For browser-based sources, also run:\n"
        "  uv run --no-dev playwright install chromium\n\n"
        "The .py file contains all application source; dependencies and browsers\n"
        "are installed separately. On macOS/Linux, activate the environment and\n"
        "use: install -m 755 mdl.py ~/.local/bin/mdl (create the directory first).\n"
        "Keep that environment active when invoking the installed command.\n",
        encoding="utf-8",
    )
    assets = [
        output / name for name in ("mdl.py", "pyproject.toml", "uv.lock", "LICENSE", "INSTALL.txt")
    ]
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Require this exact v-prefixed version tag")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist" / "release")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    version = read_version()
    validate_project_version(version)
    if args.tag is not None:
        validate_tag(version, args.tag)
    if not args.check_only:
        build_assets(args.output_dir.resolve(), version)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(
                f"version={version}\ntag=v{version}\nprerelease={str('-' in version).lower()}\n"
            )
    print(
        f"Validated MDL v{version}"
        if args.check_only
        else f"Built MDL v{version}: {args.output_dir}"
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, SyntaxError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Release failed: {exc}")
