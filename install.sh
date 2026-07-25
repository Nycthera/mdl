#!/bin/bash
set -euo pipefail

base_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Base path: $base_path"

ask_yes_no() {
    local prompt="$1" default="$2" answer
    while true; do
        if [ "$default" = "y" ]; then
            read -r -p "$prompt [Y/n]: " answer
        else
            read -r -p "$prompt [y/N]: " answer
        fi
        answer="$(echo "${answer:-}" | tr '[:upper:]' '[:lower:]')"
        [ -z "$answer" ] && answer="$default"
        case "$answer" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed or not in PATH."
    exit 1
fi
PY="python3"

echo ""
echo "=== MDL Install ==="
echo "Bundles all source files into a single mdl_single.py and installs it as 'mdl'."

install_python_deps=false
install_playwright=false
install_to_system=false

if ask_yes_no "Install Python dependencies (pip install --user -r requirements.txt)" y; then
    install_python_deps=true
fi
if ask_yes_no "Install Playwright browsers (~300 MB download)" y; then
    install_playwright=true
fi

echo ""
echo "Install location for the bundled 'mdl' command:"
echo "  1) ~/.local/bin/mdl           (user-local, recommended)"
echo "  2) /usr/local/bin/mdl         (system-wide, requires sudo)"
echo "  3) ./mdl_single.py            (just leave it in the project folder)"
read -r -p "Choose [1/2/3] (default 1): " loc_choice
loc_choice="${loc_choice:-1}"

case "$loc_choice" in
    1) install_target="$HOME/.local/bin/mdl" ;;
    2) install_target="/usr/local/bin/mdl"; install_to_system=true ;;
    3) install_target="$base_path/mdl_single.py" ;;
    *) install_target="$HOME/.local/bin/mdl" ;;
esac

if [ "$install_python_deps" = true ]; then
    echo ""
    echo "--- Installing Python dependencies ---"
    "$PY" -m pip install --user --upgrade pip
    "$PY" -m pip install --user -r "$base_path/requirements.txt"
    echo "✓ Python dependencies installed"
fi

if [ "$install_playwright" = true ]; then
    echo ""
    echo "--- Installing Playwright browsers ---"
    "$PY" -m playwright install
    echo "✓ Playwright browsers installed"
fi

echo ""
echo "--- Bundling source into a single file ---"
if [ ! -f "$base_path/scripts/bundle.py" ]; then
    echo "Error: scripts/bundle.py not found."
    exit 1
fi

tmp_bundle="$(mktemp -t mdl_single.XXXXXX.py)"
"$PY" "$base_path/scripts/bundle.py" --output "$tmp_bundle"
echo "✓ Bundle created ($(wc -c < "$tmp_bundle" | tr -d ' ') bytes)"

echo "--- Verifying bundle imports cleanly ---"
if "$PY" -c "
import importlib.util
spec = importlib.util.spec_from_file_location('mdl_single', '$tmp_bundle')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, 'main'), 'missing main()'
assert hasattr(mod, 'parse_args'), 'missing parse_args()'
print('OK — bundle exposes main() and parse_args()')
" 2>&1; then
    echo "✓ Bundle verification passed"
else
    echo "Error: bundle verification failed. Aborting."
    rm -f "$tmp_bundle"
    exit 1
fi

echo ""
echo "--- Installing to $install_target ---"
target_dir="$(dirname "$install_target")"
[ ! -d "$target_dir" ] && mkdir -p "$target_dir"

if [ "$install_to_system" = true ]; then
    sudo mv "$tmp_bundle" "$install_target"
    sudo chmod +x "$install_target"
else
    mv "$tmp_bundle" "$install_target"
    chmod +x "$install_target"
fi
echo "✓ Installed: $install_target"

if [ "$loc_choice" != "3" ]; then
    cp "$install_target" "$base_path/mdl_single.py"
    echo "  (reference copy left at $base_path/mdl_single.py)"
fi

if [ "$loc_choice" = "1" ]; then
    case ":$PATH:" in
        *":$HOME/.local/bin:"*)
            echo ""
            echo "✓ $HOME/.local/bin is already on your PATH." ;;
        *)
            echo ""
            echo "⚠ $HOME/.local/bin is NOT on your PATH."
            echo "  Add this line to your ~/.zshrc or ~/.bashrc:"
            echo ""
            echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
            echo ""
            echo "  Then: source ~/.zshrc  (or start a new terminal)" ;;
    esac
fi

echo ""
echo "=== Installation complete ==="
echo "  Try:  mdl --help"
echo ""
echo "To re-bundle after editing source:"
echo "  python3 $base_path/scripts/bundle.py --output $install_target"
