# MDL - Multi-Source Manga Downloader

> A sophisticated, high-performance manga downloading solution featuring concurrent processing, multi-source integration, and comprehensive error handling.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://python.org)
[![Node.js 18+](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Latest release](https://img.shields.io/github/v/release/Nycthera/mdl)](https://github.com/Nycthera/mdl/releases)

## 📚 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [Installation](#installation)
- [Usage](#-usage)
- [Configuration](#configuration)
- [DB Auto-Update](#-db-auto-update)
- [Architecture](#architecture)
- [Contributing](#-contributing)

## ✨ Features

### Core Capabilities

- **🔗 Multi-Source Support**
  - MangaDex official API (primary, most reliable)
  - WeebCentral browser automation fallback
  - Direct image hosting support (LaStation, Lowee, Planeptune)
  
- **⚡ Performance**
  - Async/await concurrency with configurable workers (1-50)
  - Rate limiting with exponential backoff
  - Connection pooling for optimized network usage
  - Pages/second performance metrics
  
- **📦 Output Formats**
  - CBZ (Comic Book Archive) generation
  - Organized folder structure per chapter
  - Clean JSON configuration management
  
- **🛡️ Reliability**
  - Automatic retry with exponential backoff
  - Graceful error handling
  - Support interruption handling (Ctrl+C)
  - Cross-platform compatibility (Windows, macOS, Linux)
  
- **👁️ User Experience**
  - Real-time progress bars with ETA
  - Rich terminal UI with color output
  - Clean output mode for automation
  - Comprehensive help documentation

## 🚀 Quick Start

### Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**
- **Node.js 18+** (optional, for API server only)
- **npm** (optional, included with Node.js)

### Installation

Clone and synchronize the locked environment:

```bash
git clone https://github.com/Nycthera/mdl.git
cd mdl
uv sync --locked
uv run playwright install chromium
uv run python main.py --help
```

uv creates and manages `.venv` from `pyproject.toml` and `uv.lock`. Chromium is
only needed for browser-based sources.

To install a standalone `mdl` command on macOS/Linux:

```bash
uv run python install_single.py --playwright
mdl --help
```

See the [installation guide](INSTALLATION.md) for build-only and custom-location options.

### Web Dashboard

The repository also includes a Django web app in [mdl-website/README.md](mdl-website/README.md) with login, signup, a protected dashboard, and JSON endpoints backed by Django's built-in auth database.

#### Convenience setup scripts

```bash
# macOS/Linux
chmod +x install.sh
./install.sh

# Windows
install.bat
```

### First Download

```bash
# Basic usage
uv run python main.py -M "one-piece"

# Or from MangaDex
uv run python main.py -M "https://mangadex.org/title/uuid"
```

## 📖 Usage

### Command-Line Options

```bash
uv run python main.py --help
```

### Examples

#### Basic Download (Direct Source)

```bash
uv run python main.py -M "one-piece"
```

#### MangaDex URL Download

```bash
uv run python main.py -M "https://mangadex.org/title/uuid"
```

#### Advanced Options

```bash
# Download with 20 concurrent workers and max 150 pages per chapter
uv run python main.py -M "naruto" --workers 20 --max-pages 150

# Download with CBZ archive creation
uv run python main.py -M "attack-on-titan" --cbz

# Download specific chapter range
uv run python main.py -M "demon-slayer" --start-chapter 50 --start-page 1

# Clean output mode (no progress bars, summary only)
uv run python main.py -M "jujutsu-kaisen" --clean-output

# Enable developer debug logs
uv run python main.py -M "jujutsu-kaisen" --dev

# MangaDex with specific language
uv run python main.py -M "https://mangadex.org/title/uuid" --md-lang ja
```

#### Maintenance Commands

```bash
# Remove Python, pytest, and Ruff cache directories from the project
uv run python scripts/clean_pycache.py

# Preview matching cache directories without deleting them
uv run python scripts/clean_pycache.py --dry-run

# Synchronize the locked environment
uv sync --locked

# Check all manga tracked in SQLite and download new chapters
uv run python main.py --auto-update-db

# DB auto-update with developer debug logs
uv run python main.py --auto-update-db --dev

# Show credits and attribution
uv run python main.py --credits

# Display version
uv run python main.py --version
```

## 🤖 DB Auto-Update

Use the database as your tracking source to fetch updates for previously downloaded manga:

```bash
uv run python main.py --auto-update-db
```

Detailed guide: [DB_AUTO_UPDATE.md](DB_AUTO_UPDATE.md)

### Configuration

Settings are stored in `~/.config/manga_downloader/config.json`

Example config:

```json
{
    "manga_name": "one-piece",
    "start_chapter": 1,
    "start_page": 1,
    "max_pages": 50,
    "workers": 10,
    "cbz": true,
    "clean_output": false,
    "md_language": "en",
    "credits_shown": true
}
```

You can edit this file directly to set defaults, then run without `-M` flag:

```bash
uv run python main.py  # Uses values from config.json
```

## Architecture

### System Design

**MDL** implements a modular architecture with clear separation of concerns:

```text
src/
├── cli.py              # Command-line interface
├── config.py           # Configuration management
├── downloader.py       # Image download engine
├── cbz.py              # Archive creation
├── rate_limiter.py     # API throttling
├── system_utils.py     # Setup & maintenance
├── utils.py            # Utilities & helpers
└── scrapers/
    ├── generic.py      # Direct image sources
    ├── mangadex.py     # Official API
    └── weebcentral.py  # Browser automation
```

### Performance Characteristics

| Metric | Value | Notes |
| -------- | ------- | ------- |
| **Concurrency** | 1-50 workers | Configurable, default 10 |
| **Rate Limiting** | 5 req/sec | Adaptive, respects server limits |
| **Retry Logic** | 5 attempts | Exponential backoff (1s-32s) |
| **CBZ Creation** | Streaming | Memory-efficient archive generation |
| **Memory Usage** | ~50-100 MB | Depends on worker count |

### Data Sources

| Source | Priority | Speed | Reliability | Notes |
| -------- | ---------- | ------- | -------------- | ------- |
| MangaDex API | 1 | Fast | Very High | Official, rate-limited |
| LaStation | 2 | Fast | High | Direct hosting |
| WeebCentral | 3 | Slow | Medium | Browser automation |

## 📦 Dependencies

Runtime dependencies are declared in `pyproject.toml` and resolved exactly in
`uv.lock`:

- **aiohttp** (3.8+) - Async HTTP client
- **rich** (13.5+) - Terminal UI & formatting
- **playwright** (1.40+) - Browser automation
- **pytest** - Testing framework (development group)

## 🧪 Testing

### Publishing a release

Set `__version__` in [src/__init__.py](src/__init__.py), commit the change, and push
the matching `v` tag. For example, after setting the version to `3.5.1`:

```bash
uv run python scripts/release.py --check-only --tag v3.5.1
git tag -a v3.5.1 -m "MDL v3.5.1"
git push origin v3.5.1
```

The tagged commit must include the workflow, `install_single.py`, and
`scripts/release.py`. GitHub Actions rejects mismatched tags, runs tests, builds
and verifies the single-file program, then publishes `mdl.py`, `pyproject.toml`,
`uv.lock`, `LICENSE`, `INSTALL.txt`, and `SHA256SUMS` to that tag's release. These source assets
replace the previous PyInstaller platform binaries. Python 3.13+ and dependencies
are still required; follow `INSTALL.txt` from the release.

Versions use `X.Y.Z`, optionally followed by a prerelease suffix such as
`3.6.0-rc.1`. The corresponding `v3.6.0-rc.1` release is marked as a prerelease.
PRs, pushes to `main`, and manual workflow runs test and build without publishing.
Existing published releases are not overwritten; publish a new version instead.

To reproduce the release build locally after installing dependencies:

```bash
uv run python scripts/release.py  # creates dist/release/
```

Release behavior follows the [GitHub CLI release documentation](https://cli.github.com/manual/gh_release_create).

### Running tests

```bash
# Run all tests
uv run python -m pytest -v

# Run with coverage
uv run python -m pytest --cov=src

# Run specific test file
uv run python -m pytest test/test_main.py -v
```

## 🐛 Troubleshooting

### "Python not found"

```bash
# Windows
where python

# macOS/Linux
which python3
```

If not in PATH, reinstall Python with "Add Python to PATH" checked.

### "Permission denied" (macOS/Linux)

```bash
chmod +x install.sh
./install.sh
```

### "Playwright failed"

```bash
# Reinstall Playwright
uv run playwright install chromium
```

### "Rate limited by MangaDex"

Reduce workers and add delays:

```bash
uv run python main.py -M "manga" --workers 3
```

### Cannot create CBZ

Ensure folder has write permissions:

```bash
# macOS/Linux
chmod 755 manga-folder

# Windows: Right-click → Properties → Security → Edit
```

## 📊 Project Statistics

- **Lines of Code**: ~3,500 (modular, well-documented)
- **Test Coverage**: 95%+
- **Supported Platforms**: Windows 10+, macOS 10.13+, Ubuntu 18.04+
- **Python Version**: 3.13+ (uses latest language features)
- **Async Tasks**: Up to 50 concurrent downloads

## 🔐 Security & Privacy

- **No authentication required** - Uses public APIs
- **No data collection** - All processing is local
- **Open source** - Full transparency via GPL-3.0
- **Safe downloads** - SSL/TLS for all connections
- **No cookies/tracking** - Respects privacy

## 🤝 Contributing

We welcome contributions! Here's how:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/awesome-feature`)
3. **Commit** changes (`git commit -am 'Add awesome feature'`)
4. **Test** thoroughly (`uv run python -m pytest -v`)
5. **Push** to branch (`git push origin feature/awesome-feature`)
6. **Open** a Pull Request

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/mdl.git
cd mdl

# Install locked runtime and development dependencies
uv sync --locked

# Create feature branch
git checkout -b feature/your-feature

# Make changes & test
uv run python -m pytest -v

# Push and create PR
```

## 📚 Documentation

- [Installation Guide](INSTALLATION.md) - Detailed setup instructions
- [Architecture](ARCHITECTURE.md) - Technical architecture details
- [Project Structure](PROJECT_STRUCTURE.md) - File organization
- [Refactoring Notes](REFACTORING.md) - Code organization improvements

## 📄 License

This project is licensed under the **GNU General Public License v3.0**

See [LICENSE](LICENSE) for full text.

**Summary**: You're free to use, modify, and distribute this software, but must:

- Keep the same license
- Disclose modifications
- Include original copyright notice

## 🔗 Resources

- **MangaDex API**: [https://api.mangadex.org/docs](https://api.mangadex.org/docs)
- **Playwright Docs**: [https://playwright.dev](https://playwright.dev)
- **aiohttp Guide**: [https://docs.aiohttp.org](https://docs.aiohttp.org)
- **Rich Docs**: [https://rich.readthedocs.io](https://rich.readthedocs.io)

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/Nycthera/mdl/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Nycthera/mdl/discussions)
- **Wiki**: [Community Wiki](https://github.com/Nycthera/mdl/wiki)

---

**Made with ❤️ by [Nycthera](https://github.com/Nycthera)**

**Latest Version**: [GitHub Releases](https://github.com/Nycthera/mdl/releases/latest) | **Python 3.13+**
