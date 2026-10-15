@echo off
title YT-DLP Auto-Downloader Terminal
chcp 65001 >nul
mode con: cols=100 lines=34
cd /d "%~dp0"

:: Auto-detect first time setup if yt-dlp or ffmpeg is missing
if not exist "yt-dlp.exe" (
    where yt-dlp >nul 2>&1
    if errorlevel 1 (
        echo [*] Missing yt-dlp binary. Running automated setup wizard...
        call setup.bat
    )
)

python auto_downloader.py
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)
