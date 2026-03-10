# Installation & Setup Guide

**Version**: 3.4.0 | **Updated**: March 2026 | **Maintained for**: Python 3.13+, Node.js 18+

## 📋 Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation Methods](#-installation-methods)
3. [CLI Installation](#cli-installation)
4. [Verification](#-verification)
5. [Configuration](#-configuration)
6. [Troubleshooting](#-troubleshooting)
7. [Next Steps](#-next-steps)

---

## System Requirements

### Minimum Requirements

| Component | Minimum | Recommended |
| ----------- | --------- | ------------- |
| **Python** | 3.13+ | 3.13+ |
| **Node.js** | 18+ (optional) | 20 LTS |
| **Disk Space** | 500 MB | 2 GB |
| **RAM** | 512 MB | 2+ GB |
| **OS** | Windows 10, macOS 10.13, Ubuntu 18.04+ | Latest LTS |

### Python Version Check

```bash
# macOS/Linux
python3 --version

# Windows
python --version
```

Must be **Python 3.13 or higher**.

### Node.js (Optional, for API server)

```bash
# Check Node.js
node --version    # Should be v18 or higher
npm --version     # Should be 8 or higher
```

---

## 🚀 Installation Methods

### Method 1: Automated Setup (Recommended)

The easiest way to get started. Handles all dependencies automatically.

```bash
# 1. Clone the repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# 2. Run the automated setup
python main.py --update
```

That's it! The script will:

- ✅ Detect your operating system
- ✅ Verify Python and Node.js installations
- ✅ Create virtual environment
- ✅ Install all Python dependencies
- ✅ Install Playwright browsers
- ✅ Install Node.js dependencies (if Manga-API exists)

**Advantages:**

- One command setup
- Platform-aware installation
- Automatic dependency resolution
- Built-in error checking

---

### Method 2: Shell Script Installation

Use provided installer scripts for your OS.

#### macOS / Linux

```bash
# 1. Clone repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# 2. Make script executable
chmod +x install.sh

# 3. Run installer
./install.sh
```

#### Windows (PowerShell as Administrator)

```bash
# 1. Clone repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# 2. Run installer
install.bat
```

---

### Method 3: Manual Installation

For fine-grained control over the installation process.

#### Step 1: Create Virtual Environment

```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt)
python -m venv venv
venv\Scripts\activate
```

#### Step 2: Upgrade pip

```bash
# macOS/Linux
python -m pip install --upgrade pip

# Windows
python -m pip install --upgrade pip
```

#### Step 3: Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs:

- `aiohttp` (3.8+) - Async HTTP client
- `rich` (13.5+) - Terminal UI
- `playwright` (1.40+) - Browser automation
- `requests` (2.31+) - HTTP library
- `pytest` (7.4+) - Testing framework

#### Step 4: Install Playwright Browsers

```bash
python -m playwright install
```

This downloads necessary browser engines (~1 GB):

- Chromium
- Firefox
- WebKit

#### Step 5: Install Node.js Dependencies (Optional)

For API server only:

```bash
cd Manga-API
npm install
cd ..
```

---

## CLI Installation

After installation, the `mdl` command is automatically available in your PATH.

### Using the CLI

```bash
# Show version
mdl --version

# Show help
mdl --help

# Download a manga
mdl -M "manga_name"
```

### Verify CLI Installation

```bash
# Show CLI location
which mdl          # macOS/Linux
where mdl          # Windows

# Verify version
mdl --version      # Should output: main.py 3.4.0
```

### Manual CLI Setup (if needed)

**macOS/Linux:**

```bash
# Create wrapper at /usr/local/bin/mdl
sudo bash -c 'mkdir -p /usr/local/bin && cat > /usr/local/bin/mdl <<'"'"'EOF'"'"'
#!/bin/bash
/Users/chris/Downloads/mdl/venv/bin/python3 /Users/chris/Downloads/mdl/main.py "$@"
EOF
chmod +x /usr/local/bin/mdl'
```

**Windows:**

- CLI wrapper is available as `mdl.bat` in the `bin/` directory
- To use globally, add the project directory to your PATH environment variable

### Version Information

The CLI displays the current version, stored in [src init file](../src/__init__.py):

```python
__version__ = "3.4.0"
```

---

## ✅ Verification

### Verify Installation

```bash
# Check Python environment
python --version

# Verify dependencies installed
python -c "import aiohttp, rich, playwright; print('✓ All dependencies installed')"

# Test the CLI
python main.py --version
```

### First Run Test

```bash
# Download a test manga (clean output)
python main.py -M "one-piece" --clean-output --max-pages 5

# Should output similar to:
# Downloaded 'one-piece': chapters=1, pages=5, cbz='/path/to/one-piece.cbz'
```

---

## 🔧 Configuration

### Automatic Configuration

First run creates a config file automatically at:

```text
~/.config/manga_downloader/config.json
```

### Manual Configuration

Edit the config file directly:

```bash
# Open in your editor
# macOS/Linux
nano ~/.config/manga_downloader/config.json

# Windows PowerShell
notepad $env:USERPROFILE\.config\manga_downloader\config.json
```

### Example Config

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

### Configuration Options

| Option | Type | Default | Description |
| -------- | ------ | --------- | ------------- |
| `manga_name` | string | "" | Default manga to download |
| `start_chapter` | int | 1 | Starting chapter number |
| `start_page` | int | 1 | Starting page number |
| `max_pages` | int | 50 | Max pages per chapter |
| `workers` | int | 10 | Concurrent download tasks |
| `cbz` | bool | true | Create CBZ archive |
| `clean_output` | bool | false | Suppress progress bars |
| `md_language` | string | "en" | MangaDex language code |
| `credits_shown` | bool | false | Show credits on first run |

---

## 🐛 Troubleshooting

### "Python not found" or "Python is not in PATH"

#### Windows

1. Reinstall Python from [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. **Important**: Check "Add Python to PATH" during installation
3. Restart Command Prompt
4. Verify: `python --version`

#### macOS

```bash
# Install via Homebrew if not present
brew install python3

# Verify installation
python3 --version
```

#### Linux

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install python3 python3-venv

# CentOS/RHEL
sudo yum install python3

# Verify installation
python3 --version
```

---

### "Node.js not found" (for API server)

Node.js is **optional**. Only needed if you want to run the API server.

**To install:**

1. Visit [https://nodejs.org/](https://nodejs.org/)
2. Download Node.js 18 LTS or higher
3. Run installer and follow prompts
4. Restart terminal
5. Verify: `node --version` and `npm --version`

---

### "Permission denied" (macOS/Linux)

```bash
# Make scripts executable
chmod +x install.sh
./install.sh

# Or manually fix permissions
chmod 755 /path/to/mdl
```

---

### "Playwright install failed"

```bash
# Reinstall Playwright browsers
python -m playwright install

# If that fails, try with system dependencies (Linux)
python -m playwright install-deps

# Alternatively, use specific browser
python -m playwright install chromium
```

---

### "Rate limited by MangaDex"

Reduce concurrent workers:

```bash
python main.py -M "manga-name" --workers 3
```

Or wait a few minutes and retry.

---

### "Cannot write to output folder"

Check folder permissions:

```bash
# macOS/Linux
chmod -R 755 manga-folder

# Windows PowerShell (as Administrator)
icacls "manga-folder" /grant:r "$env:USERNAME":(F)
```

---

### Virtual Environment Issues

**Deactivate and reactivate:**

```bash
# Deactivate current environment
deactivate

# Activate again
# macOS/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**Recreate virtual environment if corrupted:**

```bash
# Remove old environment
rm -rf venv        # macOS/Linux
rmdir /s venv      # Windows

# Create fresh environment
python -m venv venv

# Activate and reinstall
# macOS/Linux: source venv/bin/activate
# Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 📖 Next Steps

### 1. First Download

```bash
# Activate virtual environment if not already active
# macOS/Linux: source venv/bin/activate
# Windows: venv\Scripts\activate

# Download a manga
python main.py -M "one-piece"
```

### 2. Configure Defaults

Edit `~/.config/manga_downloader/config.json` to set your preferences.

### 3. More Examples

```bash
# Download from MangaDex
python main.py -M "https://mangadex.org/title/uuid"

# Download with custom settings
python main.py -M "naruto" --workers 15 --max-pages 100 --cbz

# Clean output (for scripts/automation)
python main.py -M "manga" --clean-output

# MangaDex with different language
python main.py -M "https://mangadex.org/title/uuid" --md-lang ja
```

### 4. View Help

```bash
python main.py --help
```

### 5. Update Anytime

```bash
python main.py --update
```

---

## 🔄 Updating

### Update Dependencies

```bash
# If you already have mdl installed
python main.py --update

# Or manually
pip install -r requirements.txt --upgrade
python -m playwright install
```

### Update Code

```bash
# Pull latest changes
git pull origin main

# Update dependencies
python main.py --update
```

---

## 📊 Verification Checklist

After installation, verify each step:

- [ ] Python 3.13+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed (`pip list` should show aiohttp, rich, playwright, etc.)
- [ ] Playwright browsers installed
- [ ] Config file created at `~/.config/manga_downloader/config.json`
- [ ] Test download completes successfully
- [ ] CBZ file created (if `--cbz` used)

---

## 📞 Getting Help

If you encounter issues:

1. **Check this guide**  
   Most common issues are covered in [Troubleshooting](#-troubleshooting)

2. **Check GitHub Issues**  
   [https://github.com/Nycthera/mdl/issues](https://github.com/Nycthera/mdl/issues)

3. **Create a New Issue**  
   Include:
   - Your OS and Python version
   - Full error message
   - Steps to reproduce
   - Output of `python main.py --version`

---

**Need help? Open an issue on [GitHub](https://github.com/Nycthera/mdl/issues)**

**Last Updated**: March 2026 | **For Version**: 3.4.0+

```json
{
  "manga_name": "",
  "start_chapter": 1,
  "start_page": 1,
  "max_pages": 50,
  "workers": 10,
  "cbz": true,
  "clean_output": false,
  "md_language": "en"
}
```

### Playwright install

```bash
playwright install
```

## Development

### Running Tests

```bash
# Python tests
pytest -v

# API integration tests
python test.py
```

### CI/CD

GitHub Actions automatically runs tests on push/PR and supports optional releases via workflow dispatch.
