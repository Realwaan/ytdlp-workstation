@echo off
setlocal enabledelayedexpansion
title YT-DLP Supercharged Workstation - Setup Wizard
chcp 65001 >nul

echo ===================================================================
echo   ⚡ YT-DLP Supercharged Workstation - Automated Setup
echo ===================================================================
echo.

:: 1. Verify Python Installation
echo [1/5] Checking Python environment...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] ERROR: Python is not installed or not in your system PATH!
    echo     Please install Python 3.8+ from https://www.python.org/
    echo     (Make sure to check "Add python.exe to PATH" during installation)
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [✓] Found %%i

:: 2. Install Python Dependencies
echo.
echo [2/5] Installing Python dependencies (colorama, pyperclip)...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [!] Pip install encountered an issue, retrying with user flag...
    python -m pip install -r requirements.txt --user --quiet
)
echo [✓] Python dependencies installed successfully.

:: 3. Check / Download yt-dlp.exe
echo.
echo [3/5] Checking yt-dlp executable...
if not exist "yt-dlp.exe" (
    echo [*] yt-dlp.exe not found. Downloading latest official release from GitHub...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe', 'yt-dlp.exe')"
    if exist "yt-dlp.exe" (
        echo [✓] Downloaded yt-dlp.exe successfully.
    ) else (
        echo [X] Could not download yt-dlp.exe automatically. Please download manually from https://github.com/yt-dlp/yt-dlp/releases
    )
) else (
    echo [✓] Found yt-dlp.exe.
)

:: 4. Check / Download ffmpeg.exe & ffprobe.exe
echo.
echo [4/5] Checking FFmpeg binaries...
set HAS_FFMPEG=0
if exist "ffmpeg.exe" (
    set HAS_FFMPEG=1
) else (
    where ffmpeg >nul 2>&1
    if !errorlevel! equ 0 (
        set HAS_FFMPEG=1
        echo [✓] Found system-wide FFmpeg in PATH.
    )
)

if !HAS_FFMPEG! equ 0 (
    echo [*] FFmpeg not found. Downloading standalone Windows build...
    echo     (This may take 1-2 minutes depending on your internet connection)
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue';" ^
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
        "$zip = 'ffmpeg-temp.zip';" ^
        "Write-Host '    Downloading FFmpeg essentials...';" ^
        "(New-Object Net.WebClient).DownloadFile('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip', $zip);" ^
        "Write-Host '    Extracting binaries...';" ^
        "Expand-Archive -Path $zip -DestinationPath 'ffmpeg-temp' -Force;" ^
        "Get-ChildItem -Path 'ffmpeg-temp' -Recurse -Filter '*.exe' | Move-Item -Destination . -Force;" ^
        "Remove-Item -Path 'ffmpeg-temp' -Recurse -Force;" ^
        "Remove-Item -Path $zip -Force;"
    if exist "ffmpeg.exe" (
        echo [✓] FFmpeg installed successfully.
    ) else (
        echo [!] Could not auto-download FFmpeg. Please install FFmpeg and place ffmpeg.exe in this folder.
    )
) else (
    echo [✓] FFmpeg is ready.
)

:: 5. Initialize Configuration & Directories
echo.
echo [5/5] Initializing configuration and downloads directory...
if not exist "config.json" (
    if exist "config.example.json" (
        copy "config.example.json" "config.json" >nul
        echo [✓] Created default config.json.
    )
)
if not exist "downloads" (
    mkdir "downloads" >nul 2>&1
    echo [✓] Created downloads folder.
)

echo.
echo ===================================================================
echo   🎉 SETUP COMPLETE! YT-DLP Supercharged Workstation is ready!
echo ===================================================================
echo.
echo You can now:
echo   - Double-click 'run.bat' to launch the workstation
echo   - Run 'create_desktop_shortcut.bat' to place an icon on your Desktop
echo.
pause
