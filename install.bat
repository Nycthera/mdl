@echo off
echo ==========================================
echo   Manga Downloader - Windows Installer
echo ==========================================

REM Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    echo Please install it from https://www.python.org/downloads/
    exit /b 1
)

REM Check for Node.js
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Node.js is not installed or not in PATH.
    echo Please install it from https://nodejs.org/
    exit /b 1
)

REM Create virtual environment if missing
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate

REM Generate requirements.txt if missing
if not exist requirements.txt (
    echo requests > requirements.txt
    echo rich >> requirements.txt
)

REM Install Python deps
pip install --upgrade pip
pip install -r requirements.txt

REM Install Playwright
playwright install

REM Setup Manga-API
cd Manga-API
if exist package.json (
    npm install
) else (
    echo Warning: package.json not found, skipping npm install.
)
cd ..

echo.
echo Installation complete.
echo To activate Python venv: call venv\Scripts\activate
echo To start Node server: cd Manga-API && npm start
pause
