# Installation & Setup Guide

Version: 3.5.0
Updated: March 2026

Installers now open a selection screen so you can choose what to install:

- Python dependency mode: user site-packages or project venv
- Playwright browsers
- Manga-API/Node dependencies
- CLI wrapper

## System Requirements

- Python 3.13+
- pip (bundled with Python)
- Node.js 18+ (optional, only for Manga-API)

## Recommended Install (One Command)

```bash
git clone https://github.com/Nycthera/mdl.git
cd mdl
python main.py --update
```

What this does:

- Shows a selection screen for components and Python mode
- Verifies Python is available
- Installs selected dependencies and tools

## Script Installers

### macOS/Linux

```bash
chmod +x install.sh
./install.sh
```

The script prompts you to choose install mode and optional components.

The script creates a CLI wrapper at:

```text
~/.local/bin/mdl
```

If needed, add this to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Windows

```bat
install.bat
```

The script prompts you to choose install mode and optional components.

The script creates a CLI wrapper at:

```text
%USERPROFILE%\bin\mdl.cmd
```

Add `%USERPROFILE%\bin` to your PATH, then open a new terminal.

## Manual Install (No venv)

### 1. Install Python dependencies

```bash
python -m pip install --upgrade pip
python -m pip install --user -r requirements.txt
```

### 2. Install Playwright browsers

```bash
python -m playwright install
```

### 3. Optional: install API server dependencies

```bash
cd server
npm install
cd ..
```

## Running MDL

```bash
python main.py --help
python main.py -M "one-piece"
```

If your CLI wrapper is on PATH:

```bash
mdl --help
mdl -M "one-piece"
```

## Verification

```bash
python --version
python -c "import aiohttp, rich, playwright; print('ok')"
python main.py --version
```

## Troubleshooting

### Python command not found

- Windows: install Python from python.org and enable Add to PATH
- macOS: install with Homebrew (`brew install python3`)
- Linux: install with your package manager (`python3`, `python3-pip`)

### Dependency install permission errors

Use user-scoped install:

```bash
python -m pip install --user -r requirements.txt
```

If your distro blocks user-site installs, use your package manager Python and pip setup.

### Playwright browser install fails

```bash
python -m playwright install
```

Linux only (if required):

```bash
python -m playwright install-deps
```

### CLI command not found after install

- macOS/Linux: ensure `~/.local/bin` is in PATH
- Windows: ensure `%USERPROFILE%\bin` is in PATH
- Restart terminal after PATH changes

## Notes

- User mode: no activation step is needed.
- Venv mode: activate with `source venv/bin/activate` (Unix) or `call venv\Scripts\activate` (Windows).
- Re-run `python main.py --update` any time you pull new changes.
