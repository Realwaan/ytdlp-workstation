"""
Channel & Creator Subscription Scheduler.

Periodically monitors saved YouTube/Bilibili/Twitch channel subscriptions
for new uploads and automatically enqueues them into QueueManager.
"""

from __future__ import annotations

import os
import sys
import json
import time
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..core.state import DownloadJob, AppState, resolve_state
from ..core.config import YTDLP_EXE, DEFAULT_DOWNLOAD_DIR
from ..core.database import DB, DatabaseEngine
from ..core.events import BUS, EventType
from .manager import QueueManager


class SubscriptionScheduler:
    """Background service that periodically checks channel subscriptions for new media."""

    def __init__(
        self,
        queue_mgr: QueueManager,
        state: Optional[AppState] = None,
        db: Optional[DatabaseEngine] = None,
        poll_interval_seconds: float = 30.0,
    ):
        self.queue_mgr = queue_mgr
        self.state = resolve_state(state)
        self.db = db or DB
        self.poll_interval = poll_interval_seconds
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background subscription checker daemon thread."""
        if self._thread is None or not self._thread.is_alive():
            self.stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="SubscriptionScheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the background scheduler."""
        self.stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        """Periodic background evaluation loop."""
        while not self.stop_event.is_set():
            try:
                enabled_subs = self.db.list_subscriptions(enabled_only=True)
                now = datetime.datetime.now()

                for sub in enabled_subs:
                    if self.stop_event.is_set():
                        break

                    is_due = False
                    last_chk_str = sub.get("last_checked_at")
                    interval_mins = max(5, int(sub.get("check_interval_mins", 60)))

                    if not last_chk_str:
                        is_due = True
                    else:
                        try:
                            # Standard SQLite timestamp format: YYYY-MM-DD HH:MM:SS
                            last_dt = datetime.datetime.fromisoformat(str(last_chk_str).replace("Z", ""))
                            if (now - last_dt).total_seconds() >= interval_mins * 60:
                                is_due = True
                        except Exception:
                            is_due = True

                    if is_due:
                        self.check_subscription(sub)

            except Exception:
                pass

            # Sleep in short increments for responsive shutdown
            for _ in range(int(self.poll_interval)):
                if self.stop_event.is_set():
                    break
                time.sleep(1.0)

    def check_subscription(self, sub: Dict[str, Any], max_entries: int = 5) -> int:
        """
        Inspect subscription URL for new uploads using yt-dlp metadata extraction.
        Returns the number of new media items enqueued.
        """
        sub_id = sub.get("id")
        channel_url = sub.get("url")
        if not channel_url:
            return 0

        cmd = [
            str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
            "--flat-playlist",
            "--dump-json",
            "--playlist-end", str(max_entries),
            "--no-warnings",
            "--ignore-errors",
            channel_url,
        ]

        channel_title = None
        new_jobs_count = 0

        try:
            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45.0,
                creationflags=creation_flags,
            )

            if proc.returncode != 0 and not proc.stdout:
                return 0

            download_dir = Path(self.state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
            custom_folder = sub.get("custom_folder")
            target_dir = str(download_dir / custom_folder) if custom_folder else str(download_dir)

            for raw_line in proc.stdout.splitlines():
                raw_line = raw_line.strip()
                if not raw_line or not raw_line.startswith("{"):
                    continue

                try:
                    entry = json.loads(raw_line)
                except Exception:
                    continue

                vid_id = entry.get("id")
                if not vid_id:
                    continue

                vid_title = entry.get("title") or "Subscription Video"
                c_cand = entry.get("channel") or entry.get("uploader") or entry.get("playlist_title")
                if c_cand and not channel_title:
                    channel_title = c_cand

                # If this video ID is already recorded in the SQLite archive, skip it
                if self.db.is_archived(vid_id):
                    continue

                # Construct media URL
                entry_url = entry.get("url") or ""
                if not entry_url.startswith("http"):
                    entry_url = f"https://www.youtube.com/watch?v={vid_id}"

                job = DownloadJob(
                    url=entry_url,
                    display_title=vid_title,
                    preset_override=sub.get("preset_id", 1),
                    target_dir=target_dir,
                )
                self.queue_mgr.enqueue(job)
                self.db.add_archive_entry("subscription", vid_id, vid_title)

                BUS.publish(
                    EventType.SUBSCRIPTION_FOUND_NEW,
                    {
                        "sub_id": sub_id,
                        "video_id": vid_id,
                        "title": vid_title,
                        "channel": channel_title or sub.get("title"),
                    },
                )
                new_jobs_count += 1

        except Exception:
            pass

        # Update last checked timestamp and channel title if discovered
        if sub_id:
            self.db.update_subscription_check_time(sub_id, new_title=channel_title)
            BUS.publish(
                EventType.SUBSCRIPTION_CHECKED,
                {"sub_id": sub_id, "new_jobs": new_jobs_count},
            )

        return new_jobs_count

    def check_all(self) -> int:
        """Manually trigger immediate check across all enabled subscriptions."""
        enabled_subs = self.db.list_subscriptions(enabled_only=True)
        total_new = 0
        for sub in enabled_subs:
            total_new += self.check_subscription(sub)
        return total_new
