@echo off
setlocal
echo ===================================================
echo   YT-DLP Workstation - Local Test Suite Runner
echo ===================================================
echo Running test suite with python -m pytest...
echo.

python -m pytest -v --tb=short

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ===================================================
    echo   [SUCCESS] All tests passed! Ready to push/deploy.
    echo ===================================================
) else (
    echo.
    echo ===================================================
    echo   [FAILURE] One or more tests failed.
    echo ===================================================
)

exit /b %ERRORLEVEL%
