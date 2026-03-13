#!/bin/bash

# -------- Base path --------
base_path=$(pwd)
echo "Base path is $base_path"

# -------- Python setup --------
echo "Setting up Python environment..."
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed."
    exit 1
fi

# Create virtual environment if not exists
if [ ! -d "$base_path/venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created at $base_path/venv"
fi

# Activate venv
source venv/bin/activate

# Auto-generate requirements.txt (only if missing)
if [ ! -f "$base_path/requirements.txt" ]; then
    echo "Generating requirements.txt..."
    cat <<EOF > requirements.txt
requests
rich
playwright
playwright-stealth
pytest
aiohttp
pytest-asyncio
EOF
fi

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install
# -------- Node.js setup --------
echo "Setting up Manga-API (Node.js)..."
cd "$base_path/Manga-API" || exit
if [ -f "package.json" ]; then
    npm install
else
    echo "Warning: package.json not found in Manga-API. Skipping npm install."
fi
cd "$base_path"

# -------- CLI Installation --------
echo "Installing CLI to /usr/local/bin/mdl..."

# Create /usr/local/bin directory if needed and install CLI
sudo bash -c "mkdir -p /usr/local/bin && cat > /usr/local/bin/mdl <<'EOF'
#!/bin/bash
# Manga Downloader CLI wrapper
mdl_dir=\"$base_path\"
\"\$mdl_dir/venv/bin/python3\" \"\$mdl_dir/main.py\" \"\$@\"
EOF
chmod +x /usr/local/bin/mdl"

if [ $? -eq 0 ]; then
    echo "✓ CLI installed successfully"
    echo "  Usage: mdl [options]"
    echo "  Example: mdl --help"
else
    echo "✗ Failed to install CLI to /usr/local/bin"
    echo "  You may need to run: sudo vi /usr/local/bin/mdl"
fi

# -------- Finish --------
echo ""
echo "Installation complete!"
echo "To activate Python venv: source venv/bin/activate"
echo "To start the Node server: cd Manga-API && npm start"
echo "To use CLI: mdl --help"
