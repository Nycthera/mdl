# Installation and Setup

MDL requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and
Python 3.13 or newer. uv installs the correct dependencies into a project-local
`.venv` from the committed lockfile, without modifying your system Python.

## Source checkout

```bash
git clone https://github.com/Nycthera/mdl.git
cd mdl
uv sync --locked
uv run playwright install chromium
uv run python main.py --help
```

The browser install is only required for browser-based sources. MangaDex and
direct image sources can run without it.

The convenience installers perform the same environment setup and optionally
install Chromium:

```bash
# macOS/Linux
./install.sh

# Windows
install.bat
```

## Running MDL

```bash
uv run python main.py -M "one-piece"
uv run python main.py -M "https://mangadex.org/title/uuid"
uv run python main.py --help
```

After pulling changes, synchronize the environment again:

```bash
uv sync --locked
```

You can also run `uv run python main.py --update` from an already synchronized
checkout.

## Standalone command on macOS/Linux

The standalone installer embeds the application source in one file and uses uv
to create an isolated runtime environment:

```bash
uv run python install_single.py
```

This installs `mdl.py` and an `mdl` symlink under `~/.local/bin` by default.
Use `--playwright` to install Chromium, `--bin-dir` or `--venv-dir` to choose
other locations, and `--build-only` to create `dist/mdl.py` without installing.

```bash
uv run python install_single.py --playwright
uv run python install_single.py --build-only
```

The installed bundle's `--update` command prints rebuild instructions. Pull the
source and rerun `install_single.py` to update a standalone installation.

## Development

The default sync includes the `dev` dependency group:

```bash
uv sync --locked
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
```

Runtime-only environments can omit development tools:

```bash
uv sync --locked --no-dev
```

Add or remove dependencies with `uv add`, `uv add --dev`, and `uv remove`, then
commit both `pyproject.toml` and `uv.lock`.

## Troubleshooting

Check the managed interpreter and dependency state with:

```bash
uv run python --version
uv sync --locked --check
```

If Chromium is missing or outdated, reinstall it with:

```bash
uv run playwright install chromium
```

On Linux, Playwright may also require system packages:

```bash
uv run playwright install-deps chromium
```
