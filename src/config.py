"""Configuration management for the manga downloader."""

import json
import os
from typing import Any, Dict

from src.utils import cprint, Colors


def get_config_path() -> str:
    """Get the configuration file path, creating directory if needed."""
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "manga_downloader")
    os.makedirs(config_dir, exist_ok=True)
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
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=4)
    cprint(f"Default config created: {CONFIG_FILE}", Colors.GREEN)


def load_config() -> Dict[str, Any]:
    """Load configuration from file, creating defaults if needed."""
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    # Add missing keys with defaults
    changed = False
    if "credits_shown" not in config:
        config["credits_shown"] = False
        changed = True

    if changed:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)

    return config


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
