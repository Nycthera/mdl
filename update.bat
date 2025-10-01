@echo off
setlocal enabledelayedexpansion

echo Are you sure you want to update? (y/n)
set /p answer=

if /I "%answer%"=="Y" (
    echo 🔄 Updating repo...
    git pull origin main
    if errorlevel 1 (
        echo ❌ Git pull failed.
        exit /b 1
    )

    set TARGET=C:\Program Files\mdl\mdl.exe
    set BACKUP=C:\Program Files\mdl\mdl.bak.exe
    set NEW=%USERPROFILE%\Downloads\mdl\main.py

    if exist "%TARGET%" (
        echo ✅ mdl found in "%TARGET%", backing up...
        ren "%TARGET%" mdl.bak.exe

        echo 📦 Installing new mdl...
        copy /Y "%NEW%" "%TARGET%" >nul
        echo 🎉 Update complete! Old version saved as mdl.bak.exe
    ) else (
        echo ⚠️ mdl not found in "%TARGET%", skipping copy.
    )
) else (
    echo ❎ Update cancelled.
)
endlocal
pause
