@echo off
chcp 65001 >nul 2>&1
:: ===================================================
::  Packing Planner — VLO-127S
::  Build Standalone .exe (ไม่ต้องมี Python บนเครื่องปลายทาง)
:: ===================================================
::  รันบน DEV MACHINE ที่มี Python + .venv
::  Output: dist\PackingPlanner\  (copy ทั้ง folder ไปวาง PC ปลายทาง)
:: ===================================================

title Build Packing Planner .exe — VLO-127S

echo ==============================================
echo   Build Packing Planner Standalone .exe
echo   VLO-127S
echo ==============================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: --- Ensure virtual environment ---
if not exist ".venv\Scripts\activate.bat" (
    echo [.venv] Creating virtual environment...
    python -m venv .venv
)
call ".venv\Scripts\activate.bat"

echo [0/4] Installing/updating build/runtime dependencies from requirements.txt...
python -m pip install --upgrade pip
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo [WARN] requirements.txt not found; ensure PyInstaller and PyQt5 are installed.
)

:: --- Build configuration ---
set "BUILD_ONEFILE=1"
set "PYI_EXE=.venv\Scripts\pyinstaller.exe"
if not exist "%PYI_EXE%" set "PYI_EXE=pyinstaller"

echo [1/4] Building standalone application...
echo     Using PyInstaller at: %PYI_EXE%
echo     This may take a few minutes on first build...
echo.

if "%BUILD_ONEFILE%"=="1" (
    "%PYI_EXE%" --noconfirm --clean --onefile --name "PackingPlanner" --windowed ^
        --add-data "app;app" ^
        --add-data "ui;ui" ^
        --add-data "core;core" ^
        --hidden-import "yaml" ^
        --hidden-import "csv" ^
        --hidden-import "websockets" ^
        --hidden-import "websockets.asyncio.server" ^
        --hidden-import "websockets.legacy.server" ^
        --icon "app_icon.ico" ^
        main.py
) else (
    "%PYI_EXE%" --noconfirm --clean --name "PackingPlanner" --windowed ^
        --add-data "app;app" ^
        --add-data "ui;ui" ^
        --add-data "core;core" ^
        --hidden-import "yaml" ^
        --hidden-import "csv" ^
        --hidden-import "websockets" ^
        --hidden-import "websockets.asyncio.server" ^
        --hidden-import "websockets.legacy.server" ^
        --icon "app_icon.ico" ^
        main.py
)

:: Check if build actually produced the exe
if "%BUILD_ONEFILE%"=="1" (
    if not exist "dist\PackingPlanner.exe" (
        echo.
        echo [ERROR] Build failed! dist\PackingPlanner.exe not created.
        pause
        exit /b 1
    ) else (
        if not exist "dist\PackingPlanner" mkdir "dist\PackingPlanner"
        move /Y "dist\PackingPlanner.exe" "dist\PackingPlanner\" >nul
    )
) else (
    if not exist "dist\PackingPlanner\PackingPlanner.exe" (
        echo.
        echo [ERROR] Build failed! PackingPlanner.exe was not created.
        pause
        exit /b 1
    )
)

echo.

:: --- Copy config and support files to dist ---
echo [2/4] Preparing distribution folder...
if not exist "dist\PackingPlanner\app" mkdir "dist\PackingPlanner\app"
if not exist "dist\PackingPlanner\output" mkdir "dist\PackingPlanner\output"
if exist "app\config.yaml"   copy /Y "app\config.yaml"   "dist\PackingPlanner\app\" >nul
if exist "app_icon.ico"      copy /Y "app_icon.ico"       "dist\PackingPlanner\"     >nul
if exist "install_pc.bat"    copy /Y "install_pc.bat"     "dist\PackingPlanner\"     >nul

:: --- Copy firewall installer ---
echo [3/4] Adding firewall setup to distribution...
if exist "install_firewall.bat" (
    copy /Y "install_firewall.bat" "dist\PackingPlanner\" >nul
    echo [OK] install_firewall.bat included in dist.
) else (
    echo [WARN] install_firewall.bat not found; LAN monitor may require manual firewall setup.
)

echo.

echo [4/4] Final distribution contents:
dir /b "dist\PackingPlanner\"

echo.
echo ==============================================
echo   Build Complete!
echo ==============================================
echo.
echo   Output folder:
echo     %SCRIPT_DIR%dist\PackingPlanner\
echo.
echo   How to deploy:
echo     1. Copy the entire "dist\PackingPlanner" folder
echo        to the target PC (USB drive, network, etc.)
echo     2. On the target PC, run (as Administrator, ONE TIME):
echo           install_firewall.bat
echo     3. Double-click:
echo           PackingPlanner\PackingPlanner.exe
echo.
echo   LAN Monitor (on other devices in same network):
echo     Open browser on phone/tablet and go to URL shown
echo     in [LAN URL] button inside the app Monitor page.
echo.
echo   No Python or Qt5 installation needed on target PC!
echo.
pause
