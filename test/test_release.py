"""Release validation must fail before publishing mismatched artifacts."""

import hashlib
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
release = runpy.run_path(str(ROOT / "scripts" / "release.py"))


@pytest.mark.parametrize("version", ["0.0.0", "3.5.1", "12.10.0", "3.6.0-rc.1"])
def test_valid_version(tmp_path, version):
    source = tmp_path / "version.py"
    source.write_text(f'raise RuntimeError("must not execute")\n__version__ = {version!r}\n')
    assert release["read_version"](source) == version
    release["validate_tag"](version, f"v{version}")


@pytest.mark.parametrize("version", ["v3.5.1", "3.5", "03.5.1", "3.5.1-rc.01", "3.5.1+build", "3.5.1\n"])
def test_invalid_version(tmp_path, version):
    source = tmp_path / "version.py"
    source.write_text(f"__version__ = {version!r}\n")
    with pytest.raises(ValueError):
        release["read_version"](source)


def test_mismatched_tag_stops_before_build(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release.py"), "--tag", "v999999.0.0",
         "--output-dir", str(tmp_path / "assets")], capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert not (tmp_path / "assets").exists()


def test_release_assets_and_checksums(tmp_path):
    release["build_assets"](tmp_path, release["read_version"]())
    assert {p.name for p in tmp_path.iterdir()} == {
        "mdl.py", "requirements.txt", "LICENSE", "INSTALL.txt", "SHA256SUMS"
    }
    assert (tmp_path / "mdl.py").read_text().startswith("#!/usr/bin/env python3\n")
    for line in (tmp_path / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ")
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == checksum


def test_bundle_version_is_verified(tmp_path):
    with pytest.raises(ValueError, match="unexpected version"):
        release["build_assets"](tmp_path, "999999.0.0")
    assert not (tmp_path / "SHA256SUMS").exists()


def test_workflow_version_outputs(tmp_path):
    output = tmp_path / "outputs"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "release.py"),
                    "--check-only", "--github-output", str(output)], check=True)
    version = release["read_version"]()
    assert output.read_text() == (
        f"version={version}\ntag=v{version}\nprerelease={str('-' in version).lower()}\n"
    )
