"""
Configuration management and filesystem path resolution.
Handles portable installation vs user-home directory data storage.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Root repository or package directory
MODULE_DIR = Path(__file__).resolve().parent.parent.parent


def _detect_portable_mode() -> bool:
    """Check if workstation is running in portable folder mode or installed globally."""
    try:
        if (MODULE_DIR / "run.bat").exists() or (MODULE_DIR / "scripts" / "setup.bat").exists() or (MODULE_DIR / "setup.bat").exists():
            test_file = MODULE_DIR / ".write_test"
            test_file.touch()
            test_file.unlink()
            return True
    except (PermissionError, OSError):
        pass
    return False


IS_PORTABLE = _detect_portable_mode()

if IS_PORTABLE:
    BASE_DIR = MODULE_DIR
    BIN_DIR = BASE_DIR / "bin"
    DATA_DIR = BASE_DIR / "data"
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USER_DATA_DIR = DATA_DIR
    DEFAULT_DOWNLOAD_DIR = MODULE_DIR / "downloads"
else:
    USER_DATA_DIR = Path.home() / ".ytdlp-workstation"
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR = USER_DATA_DIR
    BIN_DIR = BASE_DIR / "bin"
    DATA_DIR = USER_DATA_DIR
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YT-DLP"


def _find_binary(name: str) -> Path:
    """Locate executable in bin/ subfolder or root folder."""
    if (BIN_DIR / name).exists():
        return BIN_DIR / name
    if (BASE_DIR / name).exists():
        return BASE_DIR / name
    return BIN_DIR / name


YTDLP_EXE = _find_binary("yt-dlp.exe")
FFMPEG_EXE = _find_binary("ffmpeg.exe")
ARIA2C_EXE = _find_binary("aria2c.exe")

# Ensure binary paths are appended to PATH so bundled binaries are found
for _p in [str(BIN_DIR), str(BASE_DIR), str(MODULE_DIR)]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# Key file paths (organized in data/ folder)
CONFIG_FILE = DATA_DIR / "config.json" if (DATA_DIR / "config.json").exists() else (USER_DATA_DIR / "config.json")
HISTORY_FILE = DATA_DIR / "history.json"
ARCHIVE_FILE = DATA_DIR / "archive.txt"

DEFAULT_CONFIG: Dict[str, Any] = {
    "clipboard_mode": "auto",           # 'auto', 'prompt', 'off'
    "ask_quality_each_time": True,      # Prompt single-key quality picker per download
    "default_stream_referer": "https://movy.sx/",
    "preset": 1,                        # Default preset ID (1-12)
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "sound_effects": True,
    "desktop_notifications": True,
    "browser_cookies": "none",          # 'none', 'chrome', 'edge', 'firefox', 'brave', etc.
    "cookies_file": "none",             # Netscape formatted cookies.txt path or 'none'
    "subtitles_mode": "off",            # 'off', 'en', 'all'
    "speed_limit": "none",              # 'none', '5M', '10M', etc.
    "sponsorblock": False,              # Auto-skip sponsored YouTube segments
    "media_filter_only": True,          # Filter clipboard to only known media domains/extensions
    "max_concurrent_downloads": 2,      # Multi-worker parallel downloads (1 to 5)
    "use_download_archive": True,       # Auto-skip already downloaded media in playlists
    "codec_preference": "auto",         # 'auto', 'compatibility' (H.264/AAC), 'quality' (AV1/VP9)
    "music_engine_provider": "ytm",     # 'ytm' (YouTube Music clean studio) or 'yt' (Standard YouTube)
    "prefer_no_watermark": True,        # Prefer clean unwatermarked streams (TikTok, Douyin, CapCut, etc.)
}


class ConfigManager:
    """Thread-safe configuration manager."""

    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self._config = self.load()

    def load(self) -> Dict[str, Any]:
        cfg = DEFAULT_CONFIG.copy()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        cfg.update(data)
            except Exception:
                pass
        return cfg

    def save(self) -> bool:
        try:
            temp_path = self.config_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4)
            temp_path.replace(self.config_path)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
        self.save()

    def update(self, mapping: Dict[str, Any]) -> None:
        self._config.update(mapping)
        self.save()

    @property
    def data(self) -> Dict[str, Any]:
        return self._config
