# Installation & Setup Guide

Application version: see [src/__init__.py](src/__init__.py).
Published versions: [GitHub Releases](https://github.com/Nycthera/mdl/releases).

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

### Single-file Python command (macOS/Linux)

From a complete checkout, run with Python 3.13+:

```bash
python3 install_single.py
```

This collects `main.py` and every `src/**/*.py` file into an executable
`~/.local/bin/mdl.py`, with a `mdl` symlink beside it. It installs the dependencies
from `requirements.txt` into `~/.local/share/mdl/venv` and checks that the bundle
starts before installing it. The command works after moving or deleting the
checkout; keep the virtual environment and its Python installation in place.
Add `~/.local/bin` to your PATH if needed.

```bash
# Include Chromium for browser-based sources
python3 install_single.py --playwright

# Build only: creates dist/mdl.py without installing dependencies
python3 install_single.py --build-only

# Use the invoking Python and its already-installed dependencies
python3 install_single.py --skip-deps

# Choose another writable command directory
python3 install_single.py --bin-dir /usr/local/bin
```

If `/usr/local/bin` requires administrator access, first install normally, then
copy the verified file and create the command (check for an existing `mdl` first):

```bash
sudo install -m 755 "$HOME/.local/bin/mdl.py" /usr/local/bin/mdl.py
sudo ln -s mdl.py /usr/local/bin/mdl
```

That copied command still uses your user's virtual environment. For a shared
installation, an administrator must choose a shared `--venv-dir` and `--bin-dir`.
The generated file embeds application source and the license; Python, external
packages, Playwright browsers, and the optional Node server are not embedded.
Build-only output uses `python3` from PATH; installed output pins its interpreter.
Interpreter paths containing whitespace or longer than 120 bytes are rejected.

The bundled `mdl --update` prints rebuild instructions. To update, pull the source
and rerun the installer with the same options. Existing unrelated `mdl` commands
are preserved; select another `--bin-dir` if one already exists. Configuration and
the database continue to use their existing user locations; legacy databases
inside the checkout are not bundled or migrated by this installer.

Implementation references: Python's documented
[import hooks](https://docs.python.org/3/library/importlib.html) preserve module
namespaces, and [virtual environments](https://docs.python.org/3/library/venv.html)
provide dependencies without modifying system Python.

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
