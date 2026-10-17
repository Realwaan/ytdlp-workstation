"""
Download history and native yt-dlp download archive manager.
Maintains history.json for user inspection and archive.txt for instant duplicate skipping.
"""

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Set
from .config import HISTORY_FILE, ARCHIVE_FILE


class HistoryManager:
    """Thread-safe download history and archive tracker."""

    def __init__(self, history_file: Path = HISTORY_FILE, archive_file: Path = ARCHIVE_FILE):
        self.history_file = history_file
        self.archive_file = archive_file
        self.lock = threading.Lock()
        self._history: List[Dict[str, Any]] = self._load_history()
        self._archive_cache: Set[str] = self._load_archive_cache()

    def _load_history(self) -> List[Dict[str, Any]]:
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _load_archive_cache(self) -> Set[str]:
        cache = set()
        if self.archive_file.exists():
            try:
                with open(self.archive_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            cache.add(line)
            except Exception:
                pass
        return cache

    def save_history(self) -> bool:
        with self.lock:
            try:
                trimmed = self._history[-250:]
                temp_file = self.history_file.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(trimmed, f, indent=2)
                temp_file.replace(self.history_file)
                return True
            except Exception:
                return False

    def add_entry(self, entry: Dict[str, Any]) -> None:
        with self.lock:
            self._history.append(entry)
        self.save_history()

    def get_entries(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.lock:
            return self._history[-limit:]

    def clear_history(self) -> None:
        with self.lock:
            self._history.clear()
        self.save_history()

    def is_archived(self, video_id: str) -> bool:
        """Check if an ID exists in the download archive (case-insensitive substring match)."""
        video_id = video_id.strip()
        with self.lock:
            for item in self._archive_cache:
                if video_id in item:
                    return True
        return False

    def add_archive_entry(self, extractor: str, video_id: str) -> None:
        """Manually record entry in archive.txt and memory cache."""
        entry_str = f"{extractor} {video_id}".strip()
        with self.lock:
            if entry_str not in self._archive_cache:
                self._archive_cache.add(entry_str)
                try:
                    with open(self.archive_file, "a", encoding="utf-8") as f:
                        f.write(entry_str + "\n")
                except Exception:
                    pass

    @property
    def archive_path(self) -> Path:
        return self.archive_file
