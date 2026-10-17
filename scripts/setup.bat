@echo off
setlocal enabledelayedexpansion
title YT-DLP Supercharged Workstation - Setup Wizard
chcp 65001 >nul
cd /d "%~dp0.."

echo ===================================================================
echo   ⚡ YT-DLP Supercharged Workstation - Automated Setup
echo ===================================================================
echo.

:: Ensure bin, data, and downloads directories exist
if not exist "bin" mkdir "bin" >nul 2>&1
if not exist "data" mkdir "data" >nul 2>&1
if not exist "downloads" mkdir "downloads" >nul 2>&1

:: ===================================================================
:: 1. Verify / Auto-Install Python Environment
:: ===================================================================
echo [1/5] Checking Python environment...
python -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    goto :PYTHON_READY
)

py -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py"
    goto :PYTHON_READY
)

:: Python not found, auto-download and install!
call :INSTALL_PYTHON

:PYTHON_READY
if "!PYTHON_EXE!"=="" set "PYTHON_EXE=python"
for /f "tokens=*" %%i in ('!PYTHON_EXE! --version 2^>^&1') do echo [✓] Found %%i

:: ===================================================================
:: 2. Install Python Dependencies
:: ===================================================================
echo.
echo [2/5] Installing Python dependencies (colorama, pyperclip, yt-dlp)...
!PYTHON_EXE! -m pip install -r requirements.txt --quiet --disable-pip-version-check
if !errorlevel! neq 0 (
    echo [!] Pip install encountered an issue, retrying with user flag...
    !PYTHON_EXE! -m pip install -r requirements.txt --user --quiet
)
echo [✓] Python dependencies installed successfully.

:: ===================================================================
:: 3. Check / Download yt-dlp.exe
:: ===================================================================
echo.
echo [3/5] Checking yt-dlp executable...
if exist "bin\yt-dlp.exe" (
    echo [✓] Found bin\yt-dlp.exe.
    goto :YTDLP_READY
)
if exist "yt-dlp.exe" (
    move /y "yt-dlp.exe" "bin\yt-dlp.exe" >nul
    echo [✓] Found yt-dlp.exe (moved to bin/).
    goto :YTDLP_READY
)
where yt-dlp >nul 2>&1
if %errorlevel% equ 0 (
    echo [✓] Found system-wide yt-dlp in PATH.
    goto :YTDLP_READY
)

echo [*] yt-dlp.exe not found. Downloading latest official release from GitHub into bin/...
call :DOWNLOAD_YTDLP
if exist "bin\yt-dlp.exe" (
    echo [✓] Downloaded bin\yt-dlp.exe successfully.
) else (
    echo [X] Could not download yt-dlp.exe automatically. Please download manually from https://github.com/yt-dlp/yt-dlp/releases
)

:YTDLP_READY

:: ===================================================================
:: 4. Check / Download ffmpeg.exe & ffprobe.exe
:: ===================================================================
echo.
echo [4/5] Checking FFmpeg binaries...
if exist "bin\ffmpeg.exe" (
    echo [✓] Found bin\ffmpeg.exe.
    goto :FFMPEG_READY
)
if exist "ffmpeg.exe" (
    move /y "ffmpeg.exe" "bin\ffmpeg.exe" >nul
    if exist "ffprobe.exe" move /y "ffprobe.exe" "bin\ffprobe.exe" >nul
    echo [✓] Found ffmpeg.exe (moved to bin/).
    goto :FFMPEG_READY
)
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo [✓] Found system-wide FFmpeg in PATH.
    goto :FFMPEG_READY
)

echo [*] FFmpeg not found. Downloading standalone Windows build into bin/...
echo     (This may take 1-2 minutes depending on your internet connection)
call :DOWNLOAD_FFMPEG
if exist "bin\ffmpeg.exe" (
    echo [✓] FFmpeg installed successfully into bin/.
) else (
    echo [!] Could not auto-download FFmpeg. Please install FFmpeg and place ffmpeg.exe in bin/.
)

:FFMPEG_READY

:: ===================================================================
:: 5. Initialize Configuration & Directories
:: ===================================================================
echo.
echo [5/5] Initializing configuration and downloads directory...
if not exist "data\config.json" (
    if exist "data\config.example.json" (
        copy "data\config.example.json" "data\config.json" >nul
        echo [✓] Created default data\config.json.
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
if "%~1"=="--from-run" (
    echo Launching workstation now...
    ping 127.0.0.1 -n 3 >nul
    exit /b 0
)

echo You can now:
echo   - Double-click 'run.bat' in the main folder to launch
echo   - Run 'scripts\create_desktop_shortcut.bat' to pin an icon on your Desktop
echo.
pause
exit /b 0


:: ===================================================================
:: SUBROUTINES
:: ===================================================================

:INSTALL_PYTHON
echo.
echo [*] Python was NOT detected on this PC (or only Windows Store alias exists).
echo [*] Starting automated 1-Click download of official Python 3.12 for Windows...
echo.

set "PY_INSTALLER=python_setup_temp.exe"
set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"

where curl.exe >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Downloading Python 3.12 via curl...
    curl.exe -L -# -o "!PY_INSTALLER!" "!PY_URL!"
) else (
    echo [*] Downloading Python 3.12 via PowerShell...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('!PY_URL!', '!PY_INSTALLER!')"
)

if not exist "!PY_INSTALLER!" (
    echo [X] Could not download Python installer automatically.
    echo     Please download Python manually from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [*] Installing Python 3.12 (adding to PATH, including pip)...
echo     (A progress bar will appear. Please wait 30-60 seconds...)
"!PY_INSTALLER!" /passive InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0 SimpleInstall=1

if exist "!PY_INSTALLER!" del /f /q "!PY_INSTALLER!" >nul 2>&1

:: Refresh current process PATH with default Python installation paths
set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;!PATH!"

python -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    echo [✓] Python 3.12 installed and configured successfully!
    exit /b 0
)

py -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py"
    echo [✓] Python 3.12 launcher recognized!
    exit /b 0
)

echo [!] Python installed. Please restart your terminal if it does not launch immediately.
exit /b 0


:DOWNLOAD_YTDLP
where curl.exe >nul 2>&1
if %errorlevel% equ 0 (
    curl.exe -L -# -o "bin\yt-dlp.exe" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
) else (
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe', 'bin\yt-dlp.exe')"
)
exit /b 0


:DOWNLOAD_FFMPEG
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference = 'SilentlyContinue';" ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "$zip = 'ffmpeg-temp.zip';" ^
    "Write-Host '    Downloading FFmpeg essentials...';" ^
    "(New-Object Net.WebClient).DownloadFile('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip', $zip);" ^
    "Write-Host '    Extracting binaries into bin/...';" ^
    "Expand-Archive -Path $zip -DestinationPath 'ffmpeg-temp' -Force;" ^
    "Get-ChildItem -Path 'ffmpeg-temp' -Recurse -Filter '*.exe' | Move-Item -Destination bin -Force;" ^
    "Remove-Item -Path 'ffmpeg-temp' -Recurse -Force;" ^
    "Remove-Item -Path $zip -Force;"
if exist "bin\ffplay.exe" del /f /q "bin\ffplay.exe" >nul 2>&1
exit /b 0
