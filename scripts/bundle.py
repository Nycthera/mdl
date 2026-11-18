#!/usr/bin/env python3
"""Build a single-file MDL executable while preserving module namespaces."""

import argparse
import runpy
from pathlib import Path


def bundle(source_dir: Path, output: Path) -> None:
    """Use the same verified bundler as installation and release builds."""
    build = runpy.run_path(str(source_dir / "install_single.py"))["build"]
    build(output)
    print(f"Bundle written: {output} ({output.stat().st_size:,} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    if not (source_dir / "main.py").is_file():
        parser.error(f"{source_dir} does not look like the MDL repository (no main.py)")
    bundle(source_dir, args.output or source_dir / "mdl_single.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
