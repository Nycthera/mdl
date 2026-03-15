#!/bin/bash

set -euo pipefail

base_path=$(pwd)
echo "Base path is $base_path"

ask_yes_no() {
    local prompt="$1"
    local default="$2"
    local answer
    while true; do
        if [ "$default" = "y" ]; then
            read -r -p "$prompt [Y/n]: " answer
        else
            read -r -p "$prompt [y/N]: " answer
        fi
        answer=$(echo "${answer:-}" | tr '[:upper:]' '[:lower:]')
        if [ -z "$answer" ]; then
            answer="$default"
        fi
        case "$answer" in
            y|yes) return 0 ;;
            n|no) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

echo ""
echo "=== MDL Install Selection ==="
echo "1) User site-packages (no venv)"
echo "2) Project venv (./venv)"
read -r -p "Choose Python install mode [1/2] (default 1): " install_mode
install_mode=${install_mode:-1}

install_python_deps=false
install_playwright=false
install_node=false
install_cli=false

if ask_yes_no "Install Python dependencies" y; then install_python_deps=true; fi
if ask_yes_no "Install Playwright browsers" y; then install_playwright=true; fi
if ask_yes_no "Install API server (server/) Node dependencies" y; then install_node=true; fi
if ask_yes_no "Install CLI wrapper (mdl)" y; then install_cli=true; fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed."
    exit 1
fi

run_py="python3"
if [ "$install_mode" = "2" ]; then
    if [ ! -d "$base_path/venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$base_path/venv"
    fi
    run_py="$base_path/venv/bin/python"
fi

if [ "$install_python_deps" = true ]; then
    if [ "$install_mode" = "2" ]; then
        "$run_py" -m pip install --upgrade pip
    fi
    if [ "$install_mode" = "2" ]; then
        "$run_py" -m pip install -r "$base_path/requirements.txt"
    else
        "$run_py" -m pip install --user -r "$base_path/requirements.txt"
    fi
fi

if [ "$install_playwright" = true ]; then
    "$run_py" -m playwright install
fi

if [ "$install_node" = true ]; then
    echo "Setting up API server (server/, Node.js, optional)..."
    if [ -d "$base_path/server" ] && [ -f "$base_path/server/package.json" ]; then
        if command -v npm >/dev/null 2>&1; then
            (cd "$base_path/server" && npm install)
        else
            echo "Warning: npm not found. Skipping server/ dependency install."
        fi
    else
        echo "server/ not found. Skipping Node.js setup."
    fi
fi

if [ "$install_cli" = true ]; then
    echo "Installing user-local CLI wrapper..."
    user_bin="$HOME/.local/bin"
    mkdir -p "$user_bin"

    cat > "$user_bin/mdl" <<EOF
#!/bin/bash
exec "$run_py" "$base_path/main.py" "\$@"
EOF
    chmod +x "$user_bin/mdl"
fi

echo ""
echo "Installation complete!"
if [ "$install_mode" = "2" ]; then
    echo "Mode: venv ($base_path/venv)"
    echo "Activate with: source venv/bin/activate"
else
    echo "Mode: user site-packages (no venv)"
fi
if [ "$install_cli" = true ]; then
    echo "CLI installed at: $HOME/.local/bin/mdl"
    echo "If needed, add to PATH: export PATH=\"$HOME/.local/bin:\$PATH\""
fi
echo "Run: python main.py --help"
