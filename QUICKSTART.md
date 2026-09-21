# Quick Start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
git clone https://github.com/Nycthera/mdl.git
cd mdl
uv sync --locked
uv run playwright install chromium
uv run python main.py -M "one-piece"
```

Downloaded files are written below a new folder named for the manga.

## Common commands

```bash
# Download from MangaDex
uv run python main.py -M "https://mangadex.org/title/uuid"

# Create a CBZ archive
uv run python main.py -M "manga" --cbz

# Change concurrency
uv run python main.py -M "manga" --workers 20

# Show all options
uv run python main.py --help

# Run the test suite
uv run python -m pytest
```

See [INSTALLATION.md](INSTALLATION.md) for standalone installation, development,
and troubleshooting details.
