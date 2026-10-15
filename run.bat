@echo off
setlocal enabledelayedexpansion
title YT-DLP Auto-Downloader Workstation
chcp 65001 >nul
mode con: cols=100 lines=34
cd /d "%~dp0"

:: 1. Check if a working Python is installed
set "PYTHON_EXE="
python -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
) else (
    py -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
    )
)

:: 2. Check if all required components exist
set "NEED_SETUP=0"
if "!PYTHON_EXE!"=="" set "NEED_SETUP=1"
if not exist "yt-dlp.exe" (
    where yt-dlp >nul 2>&1
    if !errorlevel! neq 0 set "NEED_SETUP=1"
)
if not exist "ffmpeg.exe" (
    where ffmpeg >nul 2>&1
    if !errorlevel! neq 0 set "NEED_SETUP=1"
)

:: 3. Run automated 1-Click setup if anything is missing
if "!NEED_SETUP!"=="1" (
    echo ===================================================================
    echo   ⚡ FIRST-TIME SETUP OR MISSING COMPONENTS DETECTED
    echo   Auto-installing Python, yt-dlp, and FFmpeg for you...
    echo ===================================================================
    echo.
    call setup.bat --from-run
    
    :: Refresh PATH for current session
    set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;!PATH!"

    python -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        py -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON_EXE=py"
    )
)

if "!PYTHON_EXE!"=="" (
    echo [X] Python could not be detected. Please restart this terminal window.
    pause
    exit /b 1
)

:: 4. Launch the workstation
!PYTHON_EXE! auto_downloader.py
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)

