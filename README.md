# MDL - Multi-Source Manga Downloader

> A sophisticated, high-performance manga downloading solution featuring concurrent processing, multi-source integration, and comprehensive error handling.

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://python.org)
[![Node.js 18+](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version 3.5.0](https://img.shields.io/badge/version-3.5.0-brightgreen.svg)](https://github.com/Nycthera/mdl/releases)

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
- **Node.js 18+** (optional, for API server only)
- **pip/npm** (included with Python/Node.js)

### Installation

#### Option 1: Automated Setup (Recommended)

```bash
# Clone repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# Install minimal Python dependencies required for the updater
python -m pip install --upgrade pip
python -m pip install rich

# Run automated setup
python main.py --update
```

The updater shows a selection screen so you can choose Python mode (user/venv) and optional components.

#### Option 2: Manual Setup

```bash
# macOS/Linux
chmod +x install.sh
./install.sh

# Windows
install.bat
```

#### Option 3: Manual Installation

```bash
# Install dependencies in user site-packages (no venv)
python -m pip install --upgrade pip
python -m pip install --user -r requirements.txt

# Install Playwright browsers
python -m playwright install
```

### First Download

```bash
# Basic usage
python main.py -M "one-piece"

# Or from MangaDex
python main.py -M "https://mangadex.org/title/uuid"
```

## 📖 Usage

### Command-Line Options

```bash
python main.py --help
```

### Examples

#### Basic Download (Direct Source)

```bash
python main.py -M "one-piece"
```

#### MangaDex URL Download

```bash
python main.py -M "https://mangadex.org/title/uuid"
```

#### Advanced Options

```bash
# Download with 20 concurrent workers and max 150 pages per chapter
python main.py -M "naruto" --workers 20 --max-pages 150

# Download with CBZ archive creation
python main.py -M "attack-on-titan" --cbz

# Download specific chapter range
python main.py -M "demon-slayer" --start-chapter 50 --start-page 1

# Clean output mode (no progress bars, summary only)
python main.py -M "jujutsu-kaisen" --clean-output

# Enable developer debug logs
python main.py -M "jujutsu-kaisen" --dev

# MangaDex with specific language
python main.py -M "https://mangadex.org/title/uuid" --md-lang ja
```

#### Maintenance Commands

```bash
# Update all dependencies
python main.py --update

# Check all manga tracked in SQLite and download new chapters
python main.py --auto-update-db

# DB auto-update with developer debug logs
python main.py --auto-update-db --dev

# Show credits and attribution
python main.py --credits

# Display version
python main.py --version
```

## 🤖 DB Auto-Update

Use the database as your tracking source to fetch updates for previously downloaded manga:

```bash
python main.py --auto-update-db
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
python main.py  # Uses values from config.json
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

See [requirements.txt](requirements.txt) for exact versions:

- **aiohttp** (3.8+) - Async HTTP client
- **rich** (13.5+) - Terminal UI & formatting
- **playwright** (1.40+) - Browser automation
- **requests** (2.31+) - HTTP library
- **pytest** (7.4+) - Testing framework

## 🧪 Testing

```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov=src

# Run specific test file
pytest test/test_main.py -v
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
python -m playwright install
```

### "Rate limited by MangaDex"

Reduce workers and add delays:

```bash
python main.py -M "manga" --workers 3
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
4. **Test** thoroughly (`pytest -v`)
5. **Push** to branch (`git push origin feature/awesome-feature`)
6. **Open** a Pull Request

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/mdl.git
cd mdl

# Install dev dependencies
pip install -r requirements.txt

# Create feature branch
git checkout -b feature/your-feature

# Make changes & test
pytest -v

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

**Latest Version**: 3.5.0 | **Updated**: March 2026 | **Python 3.13+**
