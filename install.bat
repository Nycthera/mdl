@echo off
setlocal

echo ==========================================
echo   Manga Downloader - Windows Installer
echo ==========================================

echo.
echo ================= Selection =================
echo 1^) User site-packages ^(no venv^)
echo 2^) Project venv ^(./venv^)
set "INSTALL_MODE=1"
set /p INSTALL_MODE=Choose Python install mode [1/2] (default 1): 
if "%INSTALL_MODE%"=="" set "INSTALL_MODE=1"

call :ask_yes_no "Install Python dependencies" Y INSTALL_PYTHON
call :ask_yes_no "Install Playwright browsers" Y INSTALL_PLAYWRIGHT
call :ask_yes_no "Install Manga-API/Node dependencies" Y INSTALL_NODE
call :ask_yes_no "Install CLI wrapper (mdl)" Y INSTALL_CLI

REM Resolve Python launcher
set "PY_CMD="
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 set "PY_CMD=python"
)

if "%PY_CMD%"=="" (
    echo Error: Python is not installed or not in PATH.
    echo Please install it from https://www.python.org/downloads/
    exit /b 1
)

set "RUN_PY=%PY_CMD%"
set "RUN_PY_IS_PATH=N"
if "%INSTALL_MODE%"=="2" (
    if not exist venv (
        echo Creating virtual environment...
        %PY_CMD% -m venv venv
        if %errorlevel% neq 0 exit /b 1
    )
    set "RUN_PY=%CD%\venv\Scripts\python.exe"
    set "RUN_PY_IS_PATH=Y"
)

if /I "%INSTALL_PYTHON%"=="Y" (
    if "%RUN_PY_IS_PATH%"=="Y" (
        "%RUN_PY%" -m pip install --upgrade pip
    ) else (
        %RUN_PY% -m pip install --upgrade pip
    )
    if %errorlevel% neq 0 exit /b 1

    if "%INSTALL_MODE%"=="2" (
        "%RUN_PY%" -m pip install -r requirements.txt
    ) else (
        %RUN_PY% -m pip install --user -r requirements.txt
    )
    if %errorlevel% neq 0 exit /b 1
)

if /I "%INSTALL_PLAYWRIGHT%"=="Y" (
    if "%RUN_PY_IS_PATH%"=="Y" (
        "%RUN_PY%" -m playwright install
    ) else (
        %RUN_PY% -m playwright install
    )
    if %errorlevel% neq 0 exit /b 1
)

REM Setup API server (optional)
if /I "%INSTALL_NODE%"=="Y" (
    if exist server\package.json (
        where npm >nul 2>nul
        if %errorlevel% equ 0 (
            pushd server
            npm install
            popd
        ) else (
            echo Warning: npm not found, skipping server/ dependency install.
        )
    ) else (
        echo server/ not found, skipping Node.js setup.
    )
)

if /I "%INSTALL_CLI%"=="Y" (
    echo.
    echo ==========================================
    echo   Installing CLI Command
    echo ==========================================

    set "USER_BIN=%USERPROFILE%\bin"
    if not exist "%USER_BIN%" (
        mkdir "%USER_BIN%"
    )

    REM Create mdl.cmd wrapper script
    (
        echo @echo off
        if "%RUN_PY_IS_PATH%"=="Y" (
            echo "%RUN_PY%" "%CD%\main.py" %%*
        ) else (
            echo %RUN_PY% "%CD%\main.py" %%*
        )
    ) > "%USER_BIN%\mdl.cmd"
)

echo.
echo Installation complete!
if "%INSTALL_MODE%"=="2" (
    echo Mode: venv ^(%CD%\venv^)
    echo Activate with: call venv\Scripts\activate
) else (
    echo Mode: user site-packages ^(no venv^)
)
if /I "%INSTALL_CLI%"=="Y" (
    echo CLI wrapper created at: %USERPROFILE%\bin\mdl.cmd
    echo To use CLI globally:
    echo   1. Add %USERPROFILE%\bin to PATH
    echo   2. Open a new terminal
    echo   3. Run: mdl --help
)
echo.
echo To start Node server: cd server ^&^& npm start
pause
exit /b 0

:ask_yes_no
setlocal
set "PROMPT=%~1"
set "DEFAULT=%~2"
set "ANSWER="
if /I "%DEFAULT%"=="Y" (
    set /p ANSWER=%PROMPT% [Y/n]: 
) else (
    set /p ANSWER=%PROMPT% [y/N]: 
)
if "%ANSWER%"=="" set "ANSWER=%DEFAULT%"
for %%A in (y Y yes YES n N no NO) do (
    if /I "%ANSWER%"=="%%A" goto :valid_answer
)
set "ANSWER=%DEFAULT%"

:valid_answer
if /I "%ANSWER%"=="YES" set "ANSWER=Y"
if /I "%ANSWER%"=="NO" set "ANSWER=N"
if /I "%ANSWER%"=="Y" (endlocal & set "%~3=Y" & goto :eof)
endlocal & set "%~3=N"
goto :eof
