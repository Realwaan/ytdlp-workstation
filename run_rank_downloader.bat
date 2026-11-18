@echo off
setlocal enabledelayedexpansion

:: YT Automation Ranking Downloader Launcher
title YT Automation Ranking Downloader
chcp 65001 >nul
cd /d "%~dp0"

color 0B >nul 2>&1

:: STEP 1: Add bin/ to PATH
if exist "%~dp0bin" (
    set "PATH=%~dp0bin;!PATH!"
)

:: STEP 2: Detect Python
set "PYTHON_EXE="
where python >nul 2>&1
if !errorlevel! equ 0 (
    python -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
        goto :rank_python_detected
    )
)
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
    if !errorlevel! equ 0 set "PYTHON_EXE=py"
)
:rank_python_detected

if "!PYTHON_EXE!"=="" (
    echo.
    echo [X] Python 3.8+ not detected. Please install Python to run.
    pause
    exit /b 1
)

:: STEP 3: Launch Dedicated Ranking Downloader
set "PYTHONIOENCODING=utf-8"
%PYTHON_EXE% -m ytdlp_workstation.cli.rank_runner
set "EXIT_CODE=!errorlevel!"

if !EXIT_CODE! neq 0 (
    echo.
    echo [!] Process exited with code !EXIT_CODE!.
    pause
)
exit /b !EXIT_CODE!
