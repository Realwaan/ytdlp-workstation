@echo off
setlocal
echo ===================================================
echo   Installing Local Git CI Hooks
echo ===================================================

if not exist ".git" (
    echo [ERROR] Must run from repository root.
    exit /b 1
)

copy /y "scripts\hooks\pre-push" ".git\hooks\pre-push" >nul

if %ERRORLEVEL% EQU 0 (
    echo [OK] Pre-push hook installed successfully!
    echo Every 'git push' will now run the test suite locally.
    echo No GitHub Actions or paid cloud minutes required.
) else (
    echo [ERROR] Failed to install pre-push hook.
)
exit /b %ERRORLEVEL%
