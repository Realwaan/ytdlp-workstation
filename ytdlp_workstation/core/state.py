"""
Global application state and job definitions.
Provides thread-safe coordination across background watchers, the queue engine, and terminal CLI.
"""

__all__ = ["DownloadJob", "AppState", "STATE", "resolve_state"]

import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set
from .config import ConfigManager, DEFAULT_CONFIG
from .history import HistoryManager


@dataclass
class DownloadJob:
    """Represents a discrete media download task."""
    url: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    display_title: Optional[str] = None
    preset_override: Optional[int] = None
    custom_format_str: Optional[str] = None
    force_audio: bool = False
    force_video: bool = False
    force_playlist: bool = False
    download_section: Optional[str] = None
    playlist_items: Optional[str] = None
    force_subs: bool = False
    sub_lang: Optional[str] = None
    referer: Optional[str] = None
    headers: Optional[list] = None
    target_dir: Optional[str] = None
    custom_output_template: Optional[str] = None
    extra_metadata: Optional[Dict[str, str]] = None
    spotify_thumbnail: Optional[str] = None
    needs_quality_prompt: bool = False

    # Cancellation token (threading.Event) set when job is cancelled mid-download
    is_cancelled: threading.Event = field(default_factory=threading.Event, compare=False, repr=False)

    # Dynamic execution state
    status: str = "QUEUED"  # QUEUED, DOWNLOADING, COMPLETED, FAILED, CANCELLED, PAUSED
    progress_pct: float = 0.0
    speed_str: str = "--"
    eta_str: str = "--:--"
    downloaded_str: str = ""
    total_str: str = ""
    fragment_str: str = ""
    error_message: str = ""
    start_time: float = 0.0
    finish_time: float = 0.0
    saved_filename: str = ""
    saved_filesize_str: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class AppState:
    """Thread-safe application state holder."""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.history_manager = HistoryManager()
        self.lock = threading.Lock()
        self.stop_requested = False
        self.update_available: Optional[str] = None
        self.last_seen_website = self.config.get("default_stream_referer", "https://movy.sx/")

        self.pending_prompt_url: Optional[str] = None
        self.pending_prompt_ref: Optional[str] = None

        self.seen_clipboard: Set[str] = set()

        # Seed seen_clipboard from history so app doesn't re-prompt old links on startup
        for item in self.history_manager.get_entries(limit=100):
            if "url" in item:
                self.seen_clipboard.add(item["url"].strip())

    @property
    def config(self) -> Dict[str, Any]:
        return self.config_manager.data

    def set_config(self, key: str, value: Any) -> None:
        self.config_manager.set(key, value)

    def save_config(self) -> None:
        self.config_manager.save()


STATE = AppState()


def resolve_state(state: Optional["AppState"] = None) -> "AppState":
    """Return the injected state, falling back to the global singleton."""
    return state if state is not None else STATE
