# Quick Start Guide

**Get started in 60 seconds!**

## Prerequisites

- Python 3.13+
- Git (optional, for cloning)

## Installation (30 seconds)

```bash
# 1. Get the code
git clone https://github.com/Nycthera/mdl.git
cd mdl

# 2. Run setup
python main.py --update
```

Done! ✅

## First Download (15 seconds)

```bash
python main.py -M "one-piece"
```

Your manga will be in a new folder: `one-piece/`

## Common Commands

```bash
# Download manga (basic)
python main.py -M "manga-name"

# Download from MangaDex URL
python main.py -M "https://mangadex.org/title/uuid"

# Create CBZ archive
python main.py -M "manga" --cbz

# Use more workers (faster, default is 10)
python main.py -M "manga" --workers 20

# Download with specific language (MangaDex)
python main.py -M "https://mangadex.org/title/uuid" --md-lang ja

# Show only summary (no progress bars)
python main.py -M "manga" --clean-output

# View all options
python main.py --help
```

## Configuration

Edit `~/.config/manga_downloader/config.json` to set defaults:

```json
{
    "manga_name": "one-piece",
    "workers": 10,
    "cbz": true
}
```

Then just run: `python main.py`

## Troubleshooting

### "Python not found"

- Windows: Reinstall Python with "Add to PATH" checked
- macOS: `brew install python3`
- Linux: `sudo apt-get install python3`

### "Playwright install failed"

```bash
python -m playwright install
```

### Rate limited

Reduce workers:

```bash
python main.py -M "manga" --workers 3
```

## Need Help?

- **Full guide**: [INSTALLATION.md](INSTALLATION.md)
- **All options**: `python main.py --help`
- **Issues**: [GitHub Issues](https://github.com/Nycthera/mdl/issues)

---

**Version 3.4.0** | For complete docs, see [README.md](README.md)
