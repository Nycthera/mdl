#!/usr/bin/env python3
"""Make a smaller CBZ by converting its images to WebP.

Requires Pillow: ``python3 -m pip install pillow``. The input archive is never
modified. ZIP entries are processed in a bounded queue to keep memory usage low.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
import zipfile
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image

IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def convert(data: bytes, quality: int, method: int) -> bytes:
    with Image.open(BytesIO(data)) as image:
        image.load()
        metadata = {
            name: image.info[name]
            for name in ("icc_profile", "exif", "xmp")
            if image.info.get(name)
        }
        if image.mode not in {"RGB", "RGBA"}:
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=method, **metadata)
        return output.getvalue()


def write_entry(
    target: zipfile.ZipFile, source_info: zipfile.ZipInfo, name: str, data: bytes
) -> None:
    info = zipfile.ZipInfo(name, source_info.date_time)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = source_info.external_attr
    info.create_system = source_info.create_system
    target.writestr(info, data)


def optimize(
    source_path: Path, output_path: Path, quality: int, method: int, workers: int
) -> None:
    if source_path.resolve() == output_path.resolve():
        raise ValueError("The output must differ from the input archive")
    if output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path}")

    fd, pending_name = tempfile.mkstemp(
        prefix=".pending_optimized_", suffix=".cbz", dir=output_path.parent
    )
    os.close(fd)
    pending_path = Path(pending_name)
    started = time.monotonic()
    try:
        with zipfile.ZipFile(source_path) as source:
            entries = [info for info in source.infolist() if not info.is_dir()]
            entries = [
                info
                for info in entries
                if PurePosixPath(info.filename).name != ".DS_Store"
            ]
            output_names = [
                (
                    str(PurePosixPath(info.filename).with_suffix(".webp"))
                    if PurePosixPath(info.filename).suffix.lower() in IMAGE_EXTENSIONS
                    else info.filename
                )
                for info in entries
            ]
            if len(output_names) != len(set(output_names)):
                raise ValueError(
                    "Converting image extensions would create duplicate entry names"
                )

            with zipfile.ZipFile(pending_path, "w", allowZip64=True) as target:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    queue: deque[tuple[zipfile.ZipInfo, str, Future[bytes] | bytes]] = (
                        deque()
                    )
                    written = 0
                    total_output = 0

                    def flush_one() -> None:
                        nonlocal written, total_output
                        info, name, job = queue.popleft()
                        data = job.result() if isinstance(job, Future) else job
                        write_entry(target, info, name, data)
                        written += 1
                        total_output += len(data)
                        if written % 1000 == 0 or written == len(entries):
                            elapsed = time.monotonic() - started
                            print(
                                f"{written:,}/{len(entries):,} pages; "
                                f"{total_output / 1e9:.2f} GB written; {elapsed:.0f}s elapsed",
                                flush=True,
                            )

                    for info, name in zip(entries, output_names, strict=True):
                        data = source.read(info)
                        job = (
                            pool.submit(convert, data, quality, method)
                            if name != info.filename
                            else data
                        )
                        queue.append((info, name, job))
                        if len(queue) >= workers * 2:
                            flush_one()
                    while queue:
                        flush_one()

        with zipfile.ZipFile(pending_path) as result:
            if len(result.infolist()) != len(entries):
                raise ValueError("Output entry count differs from input")
            if bad := result.testzip():
                raise zipfile.BadZipFile(f"Corrupt output entry: {bad}")
        os.replace(pending_path, output_path)
        print(
            f"Saved {output_path}: {output_path.stat().st_size:,} bytes "
            f"from {source_path.stat().st_size:,} bytes "
            f"({100 * (1 - output_path.stat().st_size / source_path.stat().st_size):.1f}% smaller).",
            flush=True,
        )
    finally:
        pending_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Input CBZ file")
    parser.add_argument("output", type=Path, help="New CBZ file")
    parser.add_argument(
        "--quality", type=int, default=60, choices=range(1, 101), metavar="1..100"
    )
    parser.add_argument(
        "--method", type=int, default=4, choices=range(7), metavar="0..6"
    )
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    optimize(args.source, args.output, args.quality, args.method, args.workers)


if __name__ == "__main__":
    main()
