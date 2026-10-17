"""
SQLite High-Performance Database Engine with Write-Ahead Logging (WAL).
Replaces fragile JSON and flat files for download archiving, job history, and channel subscriptions.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from .config import DATA_DIR

DB_PATH = DATA_DIR / "workstation.db"


class DatabaseEngine:
    """Thread-safe SQLite database manager for workstation state, archive, and subscriptions."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for high-concurrency performance
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Create database tables and indices if they do not exist."""
        with self._lock, self._get_connection() as conn:
            # 1. Download Archive Table (O(1) indexed duplicate checks)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_archive (
                    extractor TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (extractor, video_id)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_archive_id ON download_archive(video_id);")

            # 2. Download History & Jobs Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    preset TEXT,
                    status TEXT NOT NULL,
                    progress REAL DEFAULT 0.0,
                    size TEXT,
                    duration TEXT,
                    error TEXT,
                    target_dir TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON download_jobs(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON download_jobs(created_at);")

            # 3. Channel & Creator Subscriptions Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    check_interval_mins INTEGER DEFAULT 60,
                    last_checked_at TIMESTAMP,
                    preset_id INTEGER DEFAULT 1,
                    custom_folder TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 4. Webhooks Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    event_types TEXT DEFAULT 'all',
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    # --- Archive Operations ---

    def is_archived(self, video_id: str) -> bool:
        """Check if video_id exists in archive."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT 1 FROM download_archive WHERE video_id = ? LIMIT 1;", (video_id,))
            return cur.fetchone() is not None

    def add_archive_entry(self, extractor: str, video_id: str, title: Optional[str] = None) -> None:
        """Insert entry into archive."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO download_archive (extractor, video_id, title) VALUES (?, ?, ?);",
                (extractor, video_id, title or "")
            )
            conn.commit()

    def get_archive_count(self) -> int:
        """Return total count of archived media items."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) as cnt FROM download_archive;")
            row = cur.fetchone()
            return row["cnt"] if row else 0

    def clear_archive(self) -> None:
        """Clear all entries in download archive."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM download_archive;")
            conn.commit()

    # --- Job History Operations ---

    def log_job(self, job_dict: Dict[str, Any]) -> None:
        """Save or update download job entry."""
        import uuid
        job_id = job_dict.get("id") or str(uuid.uuid4())[:8]
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO download_jobs (id, url, title, preset, status, progress, size, duration, error, target_dir, finished_at)
                VALUES (:id, :url, :title, :preset, :status, :progress, :size, :duration, :error, :target_dir, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    status=excluded.status,
                    progress=excluded.progress,
                    size=excluded.size,
                    duration=excluded.duration,
                    error=excluded.error,
                    finished_at=CURRENT_TIMESTAMP;
            """, {
                "id": job_id,
                "url": job_dict.get("url", ""),
                "title": job_dict.get("title", ""),
                "preset": job_dict.get("preset", ""),
                "status": job_dict.get("status", "COMPLETED"),
                "progress": float(job_dict.get("progress", 100.0)),
                "size": job_dict.get("size", ""),
                "duration": job_dict.get("duration", ""),
                "error": job_dict.get("error", ""),
                "target_dir": job_dict.get("target_dir", "")
            })
            conn.commit()

    def get_history(self, limit: int = 50, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent download history with optional keyword search."""
        with self._lock, self._get_connection() as conn:
            if search:
                cur = conn.execute("""
                    SELECT * FROM download_jobs 
                    WHERE title LIKE ? OR url LIKE ? 
                    ORDER BY created_at DESC LIMIT ?;
                """, (f"%{search}%", f"%{search}%", limit))
            else:
                cur = conn.execute("""
                    SELECT * FROM download_jobs 
                    ORDER BY created_at DESC LIMIT ?;
                """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def clear_history(self) -> None:
        """Delete all history entries."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM download_jobs;")
            conn.commit()

    # --- Subscriptions Operations ---

    def add_subscription(self, url: str, title: Optional[str] = None, interval_mins: int = 60, preset_id: int = 1, folder: Optional[str] = None) -> int:
        """Register a new channel/creator subscription."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("""
                INSERT INTO subscriptions (url, title, check_interval_mins, preset_id, custom_folder)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    check_interval_mins=excluded.check_interval_mins,
                    preset_id=excluded.preset_id,
                    custom_folder=excluded.custom_folder,
                    enabled=1;
            """, (url, title or url, interval_mins, preset_id, folder or ""))
            conn.commit()
            return cur.lastrowid

    def list_subscriptions(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """List all subscriptions."""
        with self._lock, self._get_connection() as conn:
            query = "SELECT * FROM subscriptions"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY id ASC;"
            cur = conn.execute(query)
            return [dict(row) for row in cur.fetchall()]

    def update_subscription_check_time(self, sub_id: int, new_title: Optional[str] = None) -> None:
        """Record check timestamp for a subscription."""
        with self._lock, self._get_connection() as conn:
            if new_title:
                conn.execute("UPDATE subscriptions SET last_checked_at = CURRENT_TIMESTAMP, title = ? WHERE id = ?;", (new_title, sub_id))
            else:
                conn.execute("UPDATE subscriptions SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?;", (sub_id,))
            conn.commit()

    def remove_subscription(self, sub_id: int) -> bool:
        """Remove a subscription."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("DELETE FROM subscriptions WHERE id = ?;", (sub_id,))
            conn.commit()
            return cur.rowcount > 0

    def toggle_subscription(self, sub_id: int) -> bool:
        """Toggle active status of a subscription."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("UPDATE subscriptions SET enabled = 1 - enabled WHERE id = ?;", (sub_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_subscription(self, sub_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single subscription by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM subscriptions WHERE id = ?;", (sub_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    # --- Webhooks Operations ---

    def add_webhook(self, url: str, event_types: str = "all") -> int:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("INSERT INTO webhooks (url, event_types) VALUES (?, ?);", (url, event_types))
            conn.commit()
            return cur.lastrowid

    def list_webhooks(self) -> List[Dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM webhooks WHERE enabled = 1;")
            return [dict(row) for row in cur.fetchall()]

    def delete_webhook(self, webhook_id: int) -> bool:
        """Remove a webhook by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("DELETE FROM webhooks WHERE id = ?;", (webhook_id,))
            conn.commit()
            return cur.rowcount > 0

    # --- Database Maintenance & Stats ---

    def get_database_stats(self) -> Dict[str, Any]:
        """Return comprehensive counts and database file metrics."""
        with self._lock, self._get_connection() as conn:
            archived = conn.execute("SELECT COUNT(*) FROM download_archive;").fetchone()[0]
            jobs = conn.execute("SELECT COUNT(*) FROM download_jobs;").fetchone()[0]
            subs = conn.execute("SELECT COUNT(*) FROM subscriptions;").fetchone()[0]
            webhooks = conn.execute("SELECT COUNT(*) FROM webhooks;").fetchone()[0]

            file_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
            return {
                "db_path": str(self.db_path),
                "file_size_bytes": file_size_bytes,
                "file_size_mb": round(file_size_bytes / (1024 * 1024), 2),
                "archived_media_count": archived,
                "total_jobs_logged": jobs,
                "active_subscriptions": subs,
                "registered_webhooks": webhooks,
            }

    def vacuum(self) -> None:
        """Rebuild SQLite database file to reclaim unused space and optimize indices."""
        with self._lock, self._get_connection() as conn:
            conn.execute("VACUUM;")


# Global database instance
DB = DatabaseEngine()
