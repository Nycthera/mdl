#!/bin/bash

set -euo pipefail

base_path=$(pwd)
echo "Base path is $base_path"
install_root="$HOME/.local/share/mdl"
app_path="$install_root/app"

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
echo "2) Managed venv (~/.local/share/mdl/venv)"
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

echo "Preparing installed app copy..."
rm -rf "$app_path"
mkdir -p "$app_path"
cp "$base_path/main.py" "$app_path/main.py"
cp "$base_path/requirements.txt" "$app_path/requirements.txt"
cp -R "$base_path/src" "$app_path/src"
if [ "$install_node" = true ] && [ -d "$base_path/server" ]; then
    cp -R "$base_path/server" "$app_path/server"
    rm -rf "$app_path/server/node_modules"
fi

run_py="python3"
if [ "$install_mode" = "2" ]; then
    if [ ! -d "$install_root/venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$install_root/venv"
    fi
    run_py="$install_root/venv/bin/python"
fi

if [ "$install_python_deps" = true ]; then
    if [ "$install_mode" = "2" ]; then
        "$run_py" -m pip install --upgrade pip
    fi
    if [ "$install_mode" = "2" ]; then
        "$run_py" -m pip install -r "$app_path/requirements.txt"
    else
        "$run_py" -m pip install --user -r "$app_path/requirements.txt"
    fi
fi

if [ "$install_playwright" = true ]; then
    "$run_py" -m playwright install
fi

if [ "$install_node" = true ]; then
    echo "Setting up API server (server/, Node.js, optional)..."
    if [ -d "$base_path/server" ] && [ -f "$base_path/server/package.json" ]; then
        if command -v npm >/dev/null 2>&1; then
            (cd "$app_path/server" && npm install)
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
exec "$run_py" "$app_path/main.py" "\$@"
EOF
    chmod +x "$user_bin/mdl"
fi

echo ""
echo "Installation complete!"
if [ "$install_mode" = "2" ]; then
    echo "Mode: managed venv ($install_root/venv)"
    echo "Activate with: source $install_root/venv/bin/activate"
else
    echo "Mode: user site-packages (no venv)"
fi
echo "Installed app path: $app_path"
if [ "$install_cli" = true ]; then
    echo "CLI installed at: $HOME/.local/bin/mdl"
    echo "If needed, add to PATH: export PATH=\"$HOME/.local/bin:\$PATH\""
fi
echo "Run: python main.py --help"
