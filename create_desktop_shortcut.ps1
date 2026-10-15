$desktop = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop "YT-DLP Auto-Downloader.lnk"
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $PSScriptRoot "run.bat"
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Automated YT-DLP Clipboard Downloader"
$shortcut.IconLocation = "$PSScriptRoot\yt-dlp.exe,0"
$shortcut.Save()

Write-Host ""
Write-Host "[OK] Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host "Location: $shortcutPath" -ForegroundColor Cyan
Write-Host ""
