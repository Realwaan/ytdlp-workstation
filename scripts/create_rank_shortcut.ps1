$repoRoot = (Get-Item $PSScriptRoot).Parent.FullName
$desktop = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop "YT Automation Ranking Downloader.lnk"
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $repoRoot "run_rank_downloader.bat"
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "1-Click YouTube Automation Ranking Video Downloader (E:\YTAutomationFiles\src)"
$iconPath = Join-Path $repoRoot "bin\yt-dlp.exe"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}
$shortcut.Save()

Write-Host ""
Write-Host "[OK] Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host "Location: $shortcutPath" -ForegroundColor Cyan
Write-Host ""
