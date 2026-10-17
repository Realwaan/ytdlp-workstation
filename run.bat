@echo off
setlocal enabledelayedexpansion

:: YT-DLP Supercharged Workstation - Launcher v2.0
:: Pure ASCII batch - no box-drawing or Unicode art (cmd.exe safe)
title YT-DLP Supercharged Workstation v2.0
chcp 65001 >nul
cd /d "%~dp0"

color 0B >nul 2>&1

set "OK=[OK]"
set "X=[X]"
set "ARROW=->"
set "BULLET=*"
set "HLINE==="
set "VLINE=|"

cls
echo.
echo  +-------------------------------------------------------------+
echo  ^|              YT-DLP SUPERCHARGED WORKSTATION v2.0           ^|
echo  +-------------------------------------------------------------+
echo.

:: STEP 0: Detect Python (3.8+)
echo [0/5] Detecting Python environment...
set "PYTHON_EXE="

python -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    echo   %OK% Found python (PATH)
) else (
    py -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=py"
        echo   %OK% Found py launcher
    ) else (
        echo   %X% Python 3.8+ not detected - will auto-install
        set "NEED_SETUP=1"
    )
)

:: STEP 1: Ensure bin/ is on PATH
echo [1/5] Preparing runtime PATH...
if exist "bin" (
    set "PATH=%~dp0bin;!PATH!"
    echo   %OK% bin/ added to PATH
) else (
    echo   %BULLET% bin/ not found - components will be downloaded
)

:: STEP 2: Verify required binaries (yt-dlp.exe, ffmpeg.exe)
echo [2/5] Verifying required components...
set "MISSING_YTDLP=1"
set "MISSING_FFMPEG=1"

if exist "bin\yt-dlp.exe" (
    echo   %OK% bin\yt-dlp.exe
    set "MISSING_YTDLP=0"
) else (
    where yt-dlp >nul 2>&1
    if !errorlevel! equ 0 (
        echo   %OK% yt-dlp found in system PATH
        set "MISSING_YTDLP=0"
    ) else (
        echo   %X% yt-dlp.exe missing
    )
)

if exist "bin\ffmpeg.exe" (
    echo   %OK% bin\ffmpeg.exe
    set "MISSING_FFMPEG=0"
) else (
    where ffmpeg >nul 2>&1
    if !errorlevel! equ 0 (
        echo   %OK% ffmpeg found in system PATH
        set "MISSING_FFMPEG=0"
    ) else (
        echo   %X% ffmpeg.exe missing
    )
)

:: STEP 3: Decide if setup is needed
set "NEED_SETUP=0"
if "!PYTHON_EXE!"=="" set "NEED_SETUP=1"
if "!MISSING_YTDLP!"=="1" set "NEED_SETUP=1"
if "!MISSING_FFMPEG!"=="1" set "NEED_SETUP=1"

:: STEP 4: Run automated setup if anything is missing
if "!NEED_SETUP!"=="1" (
    echo.
    echo %BULLET% First-time setup or missing components detected.
    echo   Auto-installing Python, yt-dlp, and FFmpeg...
    echo   ------------------------------------------------------------
    echo.

    if exist "scripts\setup.bat" (
        call scripts\setup.bat --from-run
    ) else if exist "setup.bat" (
        call setup.bat --from-run
    ) else (
        echo %X% setup.bat not found. Please run from the project folder.
        pause
        exit /b 1
    )

    :: Re-detect Python after setup
    set "PYTHON_EXE="
    python -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        py -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON_EXE=py"
    )
)

:: STEP 5: Launch
if "!PYTHON_EXE!"=="" (
    echo.
    echo %X% Python could not be detected. Please restart this terminal window.
    echo   Tip: Install Python from https://www.python.org/ and re-run run.bat
    pause
    exit /b 1
)

echo.
echo   %OK% All components ready. Launching workstation...
echo   ------------------------------------------------------------
echo.

set "PYTHONIOENCODING=utf-8"
%PYTHON_EXE% -m ytdlp_workstation
set "EXIT_CODE=!errorlevel!"

echo.
echo   ------------------------------------------------------------

if !EXIT_CODE! neq 0 (
    echo %X% Workstation exited with error code !EXIT_CODE!.
    echo   Tip: Check that yt-dlp.exe and ffmpeg.exe are in bin/ and try again.
) else (
    echo %OK% Workstation closed normally.
)

echo.
echo !ARROW! Press any key to close this window...
pause >nul
exit /b !EXIT_CODE!
