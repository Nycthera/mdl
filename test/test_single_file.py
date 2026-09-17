"""Integration checks for the single-file distribution, outside the checkout."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
build = runpy.run_path(str(ROOT / "install_single.py"))["build"]


@pytest.fixture
def bundle(tmp_path):
    output = tmp_path / "standalone" / "mdl.py"
    build(output, sys.executable)
    return output


def run_bundle(bundle, *arguments):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(bundle.parent / "home")
    return subprocess.run(
        [str(bundle), *arguments],
        cwd=bundle.parent,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_deterministic_and_complete(bundle, tmp_path):
    second = tmp_path / "second.py"
    build(second, sys.executable)
    assert bundle.read_bytes() == second.read_bytes()
    data = runpy.run_path(str(bundle))
    expected = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")}
    assert {entry[0] for entry in data["_SOURCES"].values()} == expected
    assert data["_MAIN"] == (ROOT / "main.py").read_text()


def test_cli_without_checkout(bundle):
    assert "--workers" in run_bundle(bundle, "--help").stdout
    version = runpy.run_path(str(ROOT / "src" / "__init__.py"))["__version__"]
    assert run_bundle(bundle, "--version").stdout.strip().endswith(f"mdl.py {version}")
    assert "rerun install_single.py" in run_bundle(bundle, "--update").stdout


def test_imports_keep_separate_globals(bundle):
    code = """
import runpy, sys
data = runpy.run_path(sys.argv[1])
sys.meta_path.insert(0, data['_EmbeddedModules']())
import src.downloader as downloader
import src.cbz as cbz
import src.database.manga_db as db
assert downloader.__file__.startswith(sys.argv[1] + '/')
downloader.set_clean_output(True)
assert downloader.CLEAN_OUTPUT is True
assert cbz.CLEAN_OUTPUT is False
assert db.has_new_mangadex_release(1, 2)
"""
    env = os.environ.copy()
    env["HOME"] = str(bundle.parent / "home")
    subprocess.run(
        [sys.executable, "-I", "-c", code, str(bundle)], cwd=bundle.parent, env=env, check=True
    )


def test_install_and_reinstall(tmp_path):
    destination = tmp_path / "bin with spaces"
    args = [
        sys.executable,
        str(ROOT / "install_single.py"),
        "--skip-deps",
        "--bin-dir",
        str(destination),
    ]
    for _ in range(2):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
        assert (destination / "mdl").is_symlink()
        assert "--workers" in run_bundle(destination / "mdl", "--help").stdout


def test_preserve_existing_command(tmp_path):
    (tmp_path / "mdl").write_text("existing command")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install_single.py"),
            "--skip-deps",
            "--bin-dir",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
    assert (tmp_path / "mdl").read_text() == "existing command"
