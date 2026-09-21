"""Configuration management for the manga downloader."""

import json
import os
import tempfile
from typing import Any

from src.utils import Colors, cprint


def get_config_path() -> str:
    """Get the configuration path without writing during module import."""
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "manga_downloader")
    return os.path.join(config_dir, "config.json")


CONFIG_FILE = get_config_path()


def create_default_config() -> None:
    """Create a default configuration file."""
    default_config = {
        "manga_name": "",
        "start_chapter": 1,
        "start_page": 1,
        "max_pages": 50,
        "workers": 10,
        "cbz": True,
        "clean_output": False,
        "md_language": "en",
        "credits_shown": False,
    }
    save_config(default_config)
    cprint(f"Default config created: {CONFIG_FILE}", Colors.GREEN)


def load_config() -> dict[str, Any]:
    """Load configuration from file, creating defaults if needed."""
    if not os.path.exists(CONFIG_FILE):
        create_default_config()

    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {CONFIG_FILE}: {exc.msg}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Configuration in {CONFIG_FILE} must be a JSON object")
    for key, minimum, maximum in (
        ("start_chapter", 0, None),
        ("start_page", 1, None),
        ("max_pages", 1, None),
        ("workers", 1, 100),
    ):
        if key not in config:
            continue
        value = config[key]
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"Invalid {key} in {CONFIG_FILE}: {value!r}")
    for key in ("cbz", "clean_output", "credits_shown", "update"):
        if key in config and type(config[key]) is not bool:
            raise ValueError(f"Configuration option {key} must be a boolean")
    for key in ("manga_name", "md_language"):
        if key in config and not isinstance(config[key], str):
            raise ValueError(f"Configuration option {key} must be a string")

    # Add missing keys with defaults
    changed = False
    if "credits_shown" not in config:
        config["credits_shown"] = False
        changed = True

    if changed:
        save_config(config)

    return config


def save_config(config: dict[str, Any]) -> None:
    """Atomically save preferences without truncating the previous config."""
    directory = os.path.dirname(os.path.abspath(CONFIG_FILE))
    os.makedirs(directory, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as stream:
            pending = stream.name
            json.dump(config, stream, indent=4)
        os.replace(pending, CONFIG_FILE)
    finally:
        if pending is not None and os.path.exists(pending):
            os.unlink(pending)
