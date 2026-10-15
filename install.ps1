# ==============================================================================
# ⚡ YT-DLP Workstation 1-Line Web Installer for Windows
# Run via: powershell -c "irm https://raw.githubusercontent.com/Realwaan/ytdlp-workstation/main/install.ps1 | iex"
# ==============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "    ⚡ YT-DLP WORKSTATION - 1-LINE INSTALLER" -ForegroundColor Yellow
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verify Python availability
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
}

if (-not $pythonCmd) {
    Write-Host "[*] Python was not found on your system." -ForegroundColor Yellow
    Write-Host "[*] Attempting automated installation via winget..." -ForegroundColor Cyan
    try {
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $pythonCmd = "python"
    } catch {
        Write-Host "[!] Could not auto-install Python via winget." -ForegroundColor Red
        Write-Host "    Please download & install Python from: https://www.python.org/downloads/" -ForegroundColor White
        Exit 1
    }
}

# 2. Install / Upgrade ytdlp-workstation from GitHub repository
Write-Host "[*] Installing ytdlp-workstation via pip..." -ForegroundColor Cyan
& $pythonCmd -m pip install --upgrade --no-warn-script-location "git+https://github.com/Realwaan/ytdlp-workstation.git"

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Installation failed. Trying local dependencies..." -ForegroundColor Red
    Exit 1
}

# 3. Detect Python User Scripts folder and ensure it is on user PATH
try {
    $pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"
    $candidateScripts = @(
        "$env:APPDATA\Python\Python$pyVer\Scripts",
        "$env:APPDATA\Python\Scripts",
        (Join-Path (& $pythonCmd -c "import sys; from pathlib import Path; print(Path(sys.executable).parent)") "Scripts")
    )

    $targetScriptsDir = $null
    foreach ($cand in $candidateScripts) {
        if (Test-Path (Join-Path $cand "ytdlp-workstation.exe")) {
            $targetScriptsDir = $cand
            break
        }
    }

    if ($targetScriptsDir) {
        $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        if ($currentPath -notlike "*$targetScriptsDir*") {
            [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$targetScriptsDir", "User")
            $env:PATH = "$env:PATH;$targetScriptsDir"
            Write-Host "[✓] Added '$targetScriptsDir' to your User PATH!" -ForegroundColor Green
        }
    }
} catch {
    # Silently continue if path modification fails
}

# 4. Create Desktop Shortcut
try {
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopDir "YT-DLP Workstation.lnk"
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)

    if ($targetScriptsDir -and (Test-Path (Join-Path $targetScriptsDir "ytdlp-workstation.exe"))) {
        $shortcut.TargetPath = (Join-Path $targetScriptsDir "ytdlp-workstation.exe")
        $shortcut.WorkingDirectory = $desktopDir
    } else {
        $shortcut.TargetPath = "$pythonCmd.exe"
        $shortcut.Arguments = "-m ytdlp_workstation"
        $shortcut.WorkingDirectory = $desktopDir
    }

    $shortcut.Description = "Launch YT-DLP Supercharged Workstation"
    $shortcut.Save()
    Write-Host "[✓] Created Desktop Shortcut: '$shortcutPath'" -ForegroundColor Green
} catch {
    Write-Host "[!] Could not create Desktop shortcut automatically: $_" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "    ✓ INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "  You can now start the workstation anytime by typing:" -ForegroundColor White
Write-Host ""
Write-Host "      ytdlp-workstation" -ForegroundColor Cyan
Write-Host "   or python -m ytdlp_workstation" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Or double-click the 'YT-DLP Workstation' shortcut on your Desktop!" -ForegroundColor White
Write-Host ""
