"""Bounded, in-place image optimization for downloaded manga pages."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MODES = ("off", "lossless", "balanced", "small")


def optimize_image(path: str, mode: str) -> bool:
    """Replace a page atomically only when the encoded image is smaller.

    Keep the source format and filename so download history and repair paths stay
    valid. Unsupported and animated formats are left untouched.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown image optimization mode: {mode}")
    if mode == "off":
        return False

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        return False

    pending: str | None = None
    try:
        with Image.open(source) as opened:
            if getattr(opened, "n_frames", 1) != 1:
                return False
            opened.load()
            metadata = {
                key: opened.info[key] for key in ("exif", "icc_profile") if opened.info.get(key)
            }

            if suffix in {".jpg", ".jpeg"}:
                if mode == "lossless":
                    return False  # Pillow cannot losslessly recompress JPEGs.
                image = opened.copy()
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                options = {"quality": 78 if mode == "balanced" else 58, "optimize": True}
                format_name = "JPEG"
            elif suffix == ".png":
                image = opened.copy()
                if mode != "lossless":
                    has_alpha = "A" in image.getbands() or "transparency" in opened.info
                    image = image.convert("RGBA" if has_alpha else "RGB")
                    image = image.quantize(colors=256 if mode == "balanced" else 64)
                options = {"optimize": True}
                format_name = "PNG"
            else:
                if mode == "lossless":
                    # Re-encoding lossy WebP as lossless cannot restore lost data.
                    return False
                image = opened.copy()
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                options = {"quality": 78 if mode == "balanced" else 58, "method": 4}
                format_name = "WEBP"

            fd, pending = tempfile.mkstemp(
                prefix=".pending_optimized_", suffix=suffix, dir=source.parent
            )
            os.close(fd)
            image.save(pending, format=format_name, **options, **metadata)

        if os.path.getsize(pending) >= source.stat().st_size:
            return False
        os.replace(pending, source)
        pending = None
        return True
    except (UnidentifiedImageError, OSError, TypeError, ValueError):
        # A successfully downloaded page remains available in its original form.
        return False
    finally:
        if pending is not None and os.path.exists(pending):
            os.unlink(pending)
