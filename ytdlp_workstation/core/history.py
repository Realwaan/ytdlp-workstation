"""
Download history and native yt-dlp download archive manager.
Maintains history.json for user inspection and archive.txt for instant duplicate skipping.
"""

__all__ = ["HistoryManager"]

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
from .config import HISTORY_FILE, ARCHIVE_FILE
from .database import DB


class HistoryManager:
    """Thread-safe download history and archive tracker with dual SQLite & JSON persistence."""

    def __init__(self, history_file: Path = HISTORY_FILE, archive_file: Path = ARCHIVE_FILE):
        self.history_file = history_file
        self.archive_file = archive_file
        self.lock = threading.Lock()
        self._history: List[Dict[str, Any]] = self._load_history()
        self._archive_cache: Set[str] = self._load_archive_cache()
        # Only seed SQLite from files on first-ever initialization to avoid duplicate rows.
        if not DB.get_history(limit=1):
            self._seed_db_from_files()

    def _seed_db_from_files(self) -> None:
        """Seed SQLite archive and history from text/json files on first initialization."""
        try:
            for item in self._history:
                entry = dict(item)
                entry.setdefault("id", entry.get("url", str(abs(hash(str(item))))))
                DB.log_job(entry)
            for raw_entry in self._archive_cache:
                parts = raw_entry.split(maxsplit=1)
                if len(parts) == 2:
                    DB.add_archive_entry(parts[0], parts[1])
                elif len(parts) == 1:
                    DB.add_archive_entry("media", parts[0])
        except Exception:
            pass

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
        try:
            DB.log_job(entry)
        except Exception:
            pass

    def get_entries(self, limit: int = 20, search: Optional[str] = None) -> List[Dict[str, Any]]:
        # Prefer in-memory history (this session's additions) over the shared
        # global SQLite DB so each HistoryManager instance is isolated.
        with self.lock:
            if self._history:
                return self._history[-limit:]
        try:
            db_entries = DB.get_history(limit=limit, search=search)
            if db_entries:
                return db_entries
        except Exception:
            pass
        with self.lock:
            return self._history[-limit:]

    def clear_history(self) -> None:
        with self.lock:
            self._history.clear()
        self.save_history()
        try:
            DB.clear_history()
        except Exception:
            pass

    def is_archived(self, video_id: str) -> bool:
        """Check if an ID exists in the download archive (memory cache loaded from archive.txt)."""
        video_id = video_id.strip()
        with self.lock:
            for item in self._archive_cache:
                if video_id in item:
                    return True
        return False

    def add_archive_entry(self, extractor: str, video_id: str, title: Optional[str] = None) -> None:
        """Record entry in archive.txt and SQLite database."""
        entry_str = f"{extractor} {video_id}".strip()
        with self.lock:
            if entry_str not in self._archive_cache:
                self._archive_cache.add(entry_str)
                try:
                    with open(self.archive_file, "a", encoding="utf-8") as f:
                        f.write(entry_str + "\n")
                except Exception:
                    pass
        try:
            DB.add_archive_entry(extractor, video_id, title)
        except Exception:
            pass

    @property
    def archive_path(self) -> Path:
        return self.archive_file
