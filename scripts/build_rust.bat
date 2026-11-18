@echo off
setlocal
echo ===================================================
echo   YT-DLP Workstation - Local Rust Core Builder
echo ===================================================

if exist "%USERPROFILE%\.cargo\bin" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
if exist "C:\msys64\ucrt64\bin" set "PATH=C:\msys64\ucrt64\bin;%PATH%"

where cargo >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] Error: Rust 'cargo' was not found on PATH.
    echo     Install via: winget install Rustlang.Rustup
    exit /b 1
)

pushd "%~dp0..\rust_core"
if exist dist del /q dist\ytdlp_rust_core-*.whl
echo [*] Building optimized release wheel with Maturin...
python -m maturin build --release --out dist
if %ERRORLEVEL% NEQ 0 (
    popd
    echo [!] Rust extension build failed.
    exit /b 1
)

for %%f in (dist\ytdlp_rust_core-*.whl) do (
    echo [*] Installing %%f...
    python -m pip install --force-reinstall --no-deps "%%f"
)
popd

python -c "from ytdlp_workstation.engine.rust_accel import HAS_RUST_CORE, RUST_CORE_VERSION; print(f'[OK] Rust Core active: {HAS_RUST_CORE} (v{RUST_CORE_VERSION})')"
exit /b %ERRORLEVEL%
