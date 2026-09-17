@echo off
setlocal

where uv >nul 2>nul
if errorlevel 1 (
    echo Error: uv is required. Install it from https://docs.astral.sh/uv/
    exit /b 1
)

echo Synchronizing the locked MDL environment...
uv sync --locked --project "%~dp0"
if errorlevel 1 exit /b 1

set "INSTALL_BROWSER=Y"
set /p INSTALL_BROWSER=Install the Playwright Chromium browser? [Y/n]:
if /I not "%INSTALL_BROWSER%"=="N" if /I not "%INSTALL_BROWSER%"=="NO" (
    uv run --project "%~dp0" playwright install chromium
    if errorlevel 1 exit /b 1
)

echo MDL is ready. Run: uv run --project "%~dp0" python main.py --help
