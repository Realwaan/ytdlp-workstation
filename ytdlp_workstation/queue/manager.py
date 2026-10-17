"""
Multi-worker concurrent download queue manager.
Supports parallel downloads, job cancellation, priority reordering, and queue lifecycle controls.
"""

import time
import threading
import collections
from pathlib import Path
from typing import Dict, List, Optional, Callable
from ..core.state import DownloadJob, STATE
from ..core.config import DEFAULT_DOWNLOAD_DIR
from ..core.presets import get_preset
from ..engine.native_engine import execute_download_job
from ..extractors.spotify import embed_cover_art_ffmpeg
from ..utils.notifications import play_sound, send_windows_toast


class QueueManager:
    """Thread-safe multi-worker concurrent download queue."""

    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self.lock = threading.Lock()
        self.pending_queue: collections.deque[DownloadJob] = collections.deque()
        self.active_jobs: Dict[str, DownloadJob] = {}
        self.completed_jobs: List[DownloadJob] = []
        self.is_paused = False
        self.stop_requested = False

        self.on_job_progress: Optional[Callable[[DownloadJob], None]] = None
        self.on_job_finished: Optional[Callable[[DownloadJob, bool], None]] = None

        self._worker_threads: List[threading.Thread] = []
        self._start_workers()

    def _start_workers(self):
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"DownloadWorker-{i+1}", daemon=True)
            t.start()
            self._worker_threads.append(t)

    def _worker_loop(self):
        while not self.stop_requested:
            job = None
            with self.lock:
                if not self.is_paused and self.pending_queue:
                    job = self.pending_queue.popleft()
                    self.active_jobs[job.id] = job

            if job:
                self._process_job(job)
                with self.lock:
                    if job.id in self.active_jobs:
                        del self.active_jobs[job.id]
                    self.completed_jobs.append(job)
            else:
                time.sleep(0.1)

    def _process_job(self, job: DownloadJob):
        """Execute job and invoke post-download lifecycle hooks."""
        config = STATE.config
        archive_path = STATE.history_manager.archive_path if config.get("use_download_archive", True) else None

        preset_id = job.preset_override or config.get("preset", 1)
        preset_name = get_preset(preset_id)["name"]
        effective_target = job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR)

        success = execute_download_job(
            job,
            config,
            archive_path=archive_path,
            on_progress=self._handle_progress
        )

        duration = round(job.finish_time - job.start_time, 1) if job.finish_time and job.start_time else 0.0

        if success:
            # Embed Spotify cover artwork if provided
            if job.spotify_thumbnail:
                try:
                    mp3_target = None
                    if job.custom_output_template and job.custom_output_template.endswith(".%(ext)s"):
                        cand = Path(job.custom_output_template.replace(".%(ext)s", ".mp3"))
                        if cand.exists():
                            mp3_target = cand
                    if not mp3_target:
                        recent = sorted(Path(effective_target).glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
                        if recent and (time.time() - recent[0].stat().st_mtime) < 60:
                            mp3_target = recent[0]
                    if mp3_target and mp3_target.exists():
                        embed_cover_art_ffmpeg(mp3_target, job.spotify_thumbnail)
                except Exception:
                    pass

            # Detect saved filename and size
            saved_name = job.saved_filename or job.display_title or Path(job.url).stem
            try:
                recent_files = sorted(
                    [p for p in Path(effective_target).glob("*") if p.is_file() and not p.name.endswith(".part")],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if recent_files and (time.time() - recent_files[0].stat().st_mtime) < 120:
                    saved_name = recent_files[0].name
                    b = recent_files[0].stat().st_size
                    if b >= 1024**3:
                        job.saved_filesize_str = f"{b / (1024**3):.2f} GB"
                    elif b >= 1024**2:
                        job.saved_filesize_str = f"{b / (1024**2):.1f} MB"
                    elif b > 0:
                        job.saved_filesize_str = f"{b / 1024:.0f} KB"
            except Exception:
                pass

            job.saved_filename = saved_name
            play_sound("success", enabled=config.get("sound_effects", True))
            send_windows_toast("Download Complete!", f"{saved_name} ({duration}s)", enabled=config.get("desktop_notifications", True))

            STATE.history_manager.add_entry({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": job.url,
                "title": saved_name,
                "preset": preset_name,
                "status": "Success",
                "duration": f"{duration}s",
                "size": job.saved_filesize_str
            })
        else:
            play_sound("error", enabled=config.get("sound_effects", True))
            send_windows_toast("Download Failed", job.error_message or "Unknown error", enabled=config.get("desktop_notifications", True))

            STATE.history_manager.add_entry({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": job.url,
                "preset": preset_name,
                "status": "Failed",
                "error": job.error_message
            })

        if self.on_job_finished:
            self.on_job_finished(job, success)

    def _handle_progress(self, job: DownloadJob):
        if self.on_job_progress:
            self.on_job_progress(job)

    def enqueue(self, job: DownloadJob) -> str:
        """Enqueue a new download task."""
        with self.lock:
            self.pending_queue.append(job)
        return job.id

    def pause_queue(self):
        """Pause processing of pending tasks."""
        with self.lock:
            self.is_paused = True

    def resume_queue(self):
        """Resume processing of pending tasks."""
        with self.lock:
            self.is_paused = False

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job by ID."""
        with self.lock:
            for job in list(self.pending_queue):
                if job.id == job_id:
                    self.pending_queue.remove(job)
                    job.status = "CANCELLED"
                    self.completed_jobs.append(job)
                    return True
        return False

    def list_jobs(self) -> Dict[str, List[DownloadJob]]:
        """Return snapshot of active, pending, and recent completed jobs."""
        with self.lock:
            return {
                "active": list(self.active_jobs.values()),
                "pending": list(self.pending_queue),
                "completed": self.completed_jobs[-15:]
            }

    def clear_pending(self) -> int:
        """Clear all pending unstarted jobs from queue."""
        with self.lock:
            count = len(self.pending_queue)
            self.pending_queue.clear()
            return count

    def set_max_workers(self, n: int):
        """Update worker concurrency cap."""
        n = max(1, min(5, n))
        self.max_workers = n
        STATE.set_config("max_concurrent_downloads", n)
