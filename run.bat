@echo off
title YT-DLP Auto-Downloader Terminal
chcp 65001 >nul
mode con: cols=100 lines=34
cd /d "%~dp0"
python auto_downloader.py
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)
