"""
Download history and native yt-dlp download archive manager.
Maintains history.json for user inspection and archive.txt for instant duplicate skipping.

Uses `RustArchiveIndex` from `ytdlp_rust_core` when compiled so large `archive.txt`
files are indexed directly in native Rust heap memory with zero Python string allocations.
"""

__all__ = ["HistoryManager"]

import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Set, Optional
from .config import HISTORY_FILE, ARCHIVE_FILE
from .database import DB
from ..engine.rust_accel import is_rust_enabled, rust_core


class HistoryManager:
    """Thread-safe download history and archive tracker with dual SQLite & JSON persistence."""

    def __init__(self, history_file: Path = HISTORY_FILE, archive_file: Path = ARCHIVE_FILE):
        self.history_file = history_file
        self.archive_file = archive_file
        self.lock = threading.Lock()
        self._history: List[Dict[str, Any]] = self._load_history()
        self._rust_archive: Optional[Any] = None

        if (
            is_rust_enabled()
            and rust_core is not None
            and hasattr(rust_core, "RustArchiveIndex")
        ):
            self._rust_archive = rust_core.RustArchiveIndex(str(self.archive_file), True)
            self._archive_cache: Any = self._rust_archive
            self._archive_index: Dict[str, str] = {}
        else:
            self._archive_cache = self._load_archive_cache()
            # O(1) index: video_id (everything after the first space) -> full entry string
            self._archive_index = self._build_archive_index(self._archive_cache)

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
            raw_entries = (
                self._rust_archive.entries()
                if self._rust_archive is not None
                else list(self._archive_cache)
            )
            for raw_entry in raw_entries:
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
        cache: Set[str] = set()
        had_generic = False
        if self.archive_file.exists():
            try:
                with open(self.archive_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if line.startswith("generic "):
                                had_generic = True
                                continue
                            cache.add(line)
                if had_generic:
                    with open(self.archive_file, "w", encoding="utf-8") as f:
                        for item in sorted(cache):
                            f.write(item + "\n")
            except Exception:
                pass
        return cache

    @staticmethod
    def _build_archive_index(cache: Set[str]) -> Dict[str, str]:
        """Build video_id -> entry string map for O(1) duplicate checks."""
        index: Dict[str, str] = {}
        for entry in cache:
            parts = entry.split(maxsplit=1)
            video_id = parts[1] if len(parts) == 2 else parts[0]
            index[video_id] = entry
        return index

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

    def get_archive_count(self) -> int:
        """Return total number of archived items."""
        with self.lock:
            return len(self._archive_cache)

    def clear_archive(self) -> None:
        """Clear archive.txt, in-memory indices, and SQLite archive table."""
        with self.lock:
            if self._rust_archive is not None:
                self._rust_archive.clear()
            else:
                self._archive_cache.clear()
                self._archive_index.clear()
            if self.archive_file.exists():
                try:
                    self.archive_file.unlink()
                except Exception:
                    pass
        try:
            DB.clear_archive()
        except Exception:
            pass

    def is_archived(self, video_id: str) -> bool:
        """Check if an ID exists in the download archive (O(1) index lookup)."""
        video_id = video_id.strip()
        if not video_id:
            return False
        if self._rust_archive is not None:
            return bool(self._rust_archive.is_archived(video_id))
        with self.lock:
            return video_id in self._archive_index

    def add_archive_entry(self, extractor: str, video_id: str, title: Optional[str] = None) -> None:
        """Record entry in archive.txt and SQLite database."""
        with self.lock:
            if self._rust_archive is not None:
                added_line = self._rust_archive.add_entry(extractor, video_id)
                if added_line is not None:
                    try:
                        with open(self.archive_file, "a", encoding="utf-8") as f:
                            f.write(added_line + "\n")
                    except Exception:
                        pass
            else:
                entry_str = f"{extractor} {video_id}".strip()
                if entry_str not in self._archive_cache:
                    self._archive_cache.add(entry_str)
                    self._archive_index[video_id.strip()] = entry_str
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
