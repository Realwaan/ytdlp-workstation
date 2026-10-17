@echo off
setlocal enabledelayedexpansion

:: YT-DLP Supercharged Workstation - Automated Setup Wizard v2.0
:: Pure ASCII batch - no box-drawing or Unicode art (cmd.exe safe)
title YT-DLP Supercharged Workstation - Setup Wizard
chcp 65001 >nul
cd /d "%~dp0.."

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
echo  ^|              AUTOMATED SETUP WIZARD v2.0                    ^|
echo  +-------------------------------------------------------------+
echo   This wizard will install Python, yt-dlp, and FFmpeg for you.
echo.

:: Ensure directories exist
if not exist "bin" mkdir "bin" >nul 2>&1
if not exist "data" mkdir "data" >nul 2>&1
if not exist "downloads" mkdir "downloads" >nul 2>&1

:: STEP 1: Python
echo [1/5] Checking Python environment...
set "PYTHON_EXE="

python -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    echo   %OK% Found python (PATH)
    goto :PYTHON_READY
)

py -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py"
    echo   %OK% Found py launcher
    goto :PYTHON_READY
)

echo   %BULLET% Python 3.8+ not detected - downloading official installer...
call :INSTALL_PYTHON

:PYTHON_READY
if "!PYTHON_EXE!"=="" set "PYTHON_EXE=python"
for /f "tokens=*" %%i in ('!PYTHON_EXE! --version 2^>^&1') do echo   %OK% %%i

:: STEP 2: Python dependencies
echo.
echo [2/5] Installing Python dependencies...
echo   colorama, pyperclip, yt-dlp
!PYTHON_EXE! -m pip install -r requirements.txt --quiet --disable-pip-version-check
if !errorlevel! neq 0 (
    echo   %BULLET% Quiet install failed, retrying with --user flag...
    !PYTHON_EXE! -m pip install -r requirements.txt --user --quiet
)
echo   %OK% Python dependencies installed.

:: STEP 3: yt-dlp.exe
echo.
echo [3/5] Checking yt-dlp executable...
if exist "bin\yt-dlp.exe" (
    echo   %OK% bin\yt-dlp.exe
    goto :YTDLP_READY
)
if exist "yt-dlp.exe" (
    move /y "yt-dlp.exe" "bin\yt-dlp.exe" >nul
    echo   %OK% yt-dlp.exe moved to bin/
    goto :YTDLP_READY
)
where yt-dlp >nul 2>&1
if %errorlevel% equ 0 (
    echo   %OK% yt-dlp found in system PATH
    goto :YTDLP_READY
)

echo   %BULLET% Downloading latest yt-dlp.exe from GitHub...
call :DOWNLOAD_YTDLP
if exist "bin\yt-dlp.exe" (
    echo   %OK% Downloaded bin\yt-dlp.exe
) else (
    echo   %X% Could not auto-download yt-dlp.exe.
    echo     Manual: https://github.com/yt-dlp/yt-dlp/releases
)

:YTDLP_READY

:: STEP 4: FFmpeg
echo.
echo [4/5] Checking FFmpeg binaries...
if exist "bin\ffmpeg.exe" (
    echo   %OK% bin\ffmpeg.exe
    goto :FFMPEG_READY
)
if exist "ffmpeg.exe" (
    move /y "ffmpeg.exe" "bin\ffmpeg.exe" >nul
    if exist "ffprobe.exe" move /y "ffprobe.exe" "bin\ffprobe.exe" >nul
    echo   %OK% ffmpeg.exe moved to bin/
    goto :FFMPEG_READY
)
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo   %OK% ffmpeg found in system PATH
    goto :FFMPEG_READY
)

echo   %BULLET% Downloading standalone FFmpeg Windows build...
echo     (This may take 1-2 minutes)
call :DOWNLOAD_FFMPEG
if exist "bin\ffmpeg.exe" (
    echo   %OK% FFmpeg installed into bin/
) else (
    echo   %X% Could not auto-download FFmpeg.
    echo     Manual: https://www.gyan.dev/ffmpeg/builds
)

:FFMPEG_READY

:: STEP 5: Config & directories
echo.
echo [5/5] Initializing configuration...
if not exist "data\config.json" (
    if exist "data\config.example.json" (
        copy "data\config.example.json" "data\config.json" >nul
        echo   %OK% Created data\config.json
    )
)
if not exist "downloads" (
    mkdir "downloads" >nul 2>&1
    echo   %OK% Created downloads folder
)
echo   %OK% Configuration initialized.

:: Done
echo.
echo %OK% SETUP COMPLETE!
echo   ------------------------------------------------------------
echo   YT-DLP Supercharged Workstation is ready to launch.
echo.

if "%~1"=="--from-run" (
    echo   Launching workstation now...
    ping 127.0.0.1 -n 3 >nul
    exit /b 0
)

echo   %ARROW% Double-click 'run.bat' in the main folder to launch
echo   %ARROW% Run 'scripts\create_desktop_shortcut.bat' to pin a Desktop icon
echo.
pause
exit /b 0

:: SUBROUTINES

:INSTALL_PYTHON
echo.
echo   %BULLET% Python was NOT detected on this PC.
echo   Downloading official Python 3.12 for Windows...
echo.

set "PY_INSTALLER=python_setup_temp.exe"
set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"

where curl.exe >nul 2>&1
if %errorlevel% equ 0 (
    echo   %ARROW% Downloading via curl...
    curl.exe -L -# -o "!PY_INSTALLER!" "!PY_URL!"
) else (
    echo   %ARROW% Downloading via PowerShell...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('!PY_URL!', '!PY_INSTALLER!')"
)

if not exist "!PY_INSTALLER!" (
    echo.
    echo   %X% Could not download Python automatically.
    echo     Please download manually from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo   Installing Python 3.12 (adding to PATH, including pip)...
echo     A progress bar will appear. Please wait 30-60 seconds...
"!PY_INSTALLER!" /passive InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0 SimpleInstall=1

if exist "!PY_INSTALLER!" del /f /q "!PY_INSTALLER!" >nul 2>&1

set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;!PATH!"

python -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    echo   %OK% Python 3.12 installed successfully!
    exit /b 0
)

py -c "import sys; exit(0 if sys.hexversion >= 0x03080000 else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py"
    echo   %OK% Python 3.12 launcher recognized!
    exit /b 0
)

echo   %X% Python installed but not detected. Please restart your terminal.
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
    "Write-Host '      Downloading FFmpeg essentials...';" ^
    "(New-Object Net.WebClient).DownloadFile('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip', $zip);" ^
    "Write-Host '      Extracting binaries into bin/...';" ^
    "Expand-Archive -Path $zip -DestinationPath 'ffmpeg-temp' -Force;" ^
    "Get-ChildItem -Path 'ffmpeg-temp' -Recurse -Filter '*.exe' | Move-Item -Destination bin -Force;" ^
    "Remove-Item -Path 'ffmpeg-temp' -Recurse -Force;" ^
    "Remove-Item -Path $zip -Force;"
if exist "bin\ffplay.exe" del /f /q "bin\ffplay.exe" >nul 2>&1
exit /b 0
