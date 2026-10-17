"""
System operations: Disk space metrics, file cleanup, console title, and dependency bootstrapping.
"""

import os
import sys
import re
import shutil
import ctypes
import subprocess
from pathlib import Path
from ..core.config import BASE_DIR, YTDLP_EXE, FFMPEG_EXE, DEFAULT_DOWNLOAD_DIR


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filesystem usage."""
    if not name:
        return "Untitled"
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip() or "Untitled"


def cleanup_orphaned_fragments(directory: Path = None) -> None:
    """Clean up dangling *-Frag* and *.part files from interrupted downloads."""
    try:
        target_dir = Path(directory or DEFAULT_DOWNLOAD_DIR)
        if target_dir.exists():
            for f in target_dir.glob("*-Frag*"):
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


def get_free_disk_space_gb(directory: Path = None) -> float:
    """Return free disk space in Gigabytes for target directory."""
    target = Path(directory or DEFAULT_DOWNLOAD_DIR)
    try:
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(target)
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return -1.0


def set_console_title(title: str) -> None:
    """Update Windows console title bar."""
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass


def reset_console_title() -> None:
    """Reset console title to default workstation title."""
    set_console_title("★ YT-DLP Supercharged Workstation ★")


def bootstrap_workstation_environment() -> None:
    """Auto-detects missing core dependencies and bootstraps them."""
    missing_pkgs = []
    try:
        import colorama
    except ImportError:
        missing_pkgs.append("colorama")
    try:
        import pyperclip
    except ImportError:
        missing_pkgs.append("pyperclip")

    if missing_pkgs:
        try:
            print(f"[*] Installing recommended Python libraries: {', '.join(missing_pkgs)}...")
            subprocess.run([sys.executable, "-m", "pip", "install", *missing_pkgs, "--quiet"], check=False)
        except Exception:
            pass

    has_ytdlp = YTDLP_EXE.exists() or shutil.which("yt-dlp")
    if not has_ytdlp:
        print("[*] yt-dlp binary not found. Downloading latest official yt-dlp.exe from GitHub...")
        try:
            import urllib.request
            url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
            urllib.request.urlretrieve(url, str(YTDLP_EXE))
            print("[✓] yt-dlp.exe downloaded successfully.")
        except Exception as e:
            print(f"[!] Note: yt-dlp.exe could not be auto-downloaded: {e}")
            print("    Please run setup.bat or install yt-dlp manually.")

    has_ffmpeg = FFMPEG_EXE.exists() or shutil.which("ffmpeg")
    if not has_ffmpeg:
        print("[!] Note: FFmpeg is not detected in this folder or in system PATH.")
        print("    Run 'setup.bat' to auto-download and install FFmpeg.")
