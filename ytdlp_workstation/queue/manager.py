"""
Multi-worker concurrent download queue manager.
Supports parallel downloads, job cancellation, priority reordering, and queue lifecycle controls.
"""

__all__ = ["QueueManager"]

import time
import threading
import collections
from pathlib import Path
from typing import Dict, List, Optional, Callable
from ..core.state import DownloadJob, STATE, AppState
from ..core.config import DEFAULT_DOWNLOAD_DIR
from ..core.presets import get_preset
from ..core.events import BUS, EventType
from ..engine.native_engine import execute_download_job
from ..engine.fragment_merger import find_fragment_groups, merge_fragment_group
from ..extractors.spotify import embed_cover_art_ffmpeg
from ..utils.notifications import play_sound, send_windows_toast


class QueueManager:
    """Thread-safe multi-worker concurrent download queue."""

    def __init__(self, max_workers: int = 2, state: Optional[AppState] = None):
        self.state = state or STATE
        self.max_workers = max(1, min(5, max_workers))
        self.lock = threading.Lock()
        self.pending_queue: collections.deque[DownloadJob] = collections.deque()
        self.active_jobs: Dict[str, DownloadJob] = {}
        self.completed_jobs: List[DownloadJob] = []
        self.is_paused = False
        self.stop_requested = False

        self.on_job_started: Optional[Callable[[DownloadJob, str], None]] = None
        self.on_job_progress: Optional[Callable[[DownloadJob], None]] = None
        self.on_job_finished: Optional[Callable[[DownloadJob, bool], None]] = None

        self._worker_threads: List[threading.Thread] = []
        self._ensure_workers()

    def _ensure_workers(self):
        """Spawn worker threads up to self.max_workers if not already running."""
        with self.lock:
            current_count = len(self._worker_threads)
            for idx in range(current_count, self.max_workers):
                t = threading.Thread(
                    target=self._worker_loop,
                    args=(idx,),
                    name=f"DownloadWorker-{idx + 1}",
                    daemon=True,
                )
                t.start()
                self._worker_threads.append(t)

    def _worker_loop(self, worker_idx: int = 0):
        while not self.stop_requested:
            job = None
            with self.lock:
                if (
                    not self.is_paused
                    and worker_idx < self.max_workers
                    and len(self.active_jobs) < self.max_workers
                    and self.pending_queue
                ):
                    job = self.pending_queue.popleft()
                    self.active_jobs[job.id] = job

            if job:
                BUS.publish(EventType.JOB_STARTED, {"job_id": job.id, "url": job.url})
                self._process_job(job)
                with self.lock:
                    if job.id in self.active_jobs:
                        del self.active_jobs[job.id]
                    self.completed_jobs.append(job)
            else:
                time.sleep(0.1)

    def _process_job(self, job: DownloadJob):
        """Execute job and invoke post-download lifecycle hooks."""
        config = self.state.config
        archive_path = self.state.history_manager.archive_path if config.get("use_download_archive", True) else None

        preset_id = job.preset_override or config.get("preset", 1)
        preset_name = get_preset(preset_id)["name"]
        effective_target = job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR)

        job.status = "STARTING"
        if self.on_job_started:
            self.on_job_started(job, preset_name)
        self._handle_progress(job)

        success = execute_download_job(
            job,
            config,
            archive_path=archive_path,
            on_progress=self._handle_progress
        )

        # Post-download folder check: if any *-Frag* files remain in the target directory,
        # automatically stitch and remux them into the final MP4 with live progress.
        if not job.is_cancelled.is_set():
            frag_groups = find_fragment_groups(Path(effective_target))
            if frag_groups:
                for base_name, frags in frag_groups.items():
                    merged_path = merge_fragment_group(
                        directory=Path(effective_target),
                        base_name=base_name,
                        frags=frags,
                        output_title=job.display_title,
                        job=job,
                        on_progress=self._handle_progress,
                    )
                    if merged_path and merged_path.exists():
                        job.saved_filename = merged_path.name
                        job. finish_time = time.time()
                        success = True

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

            entry = {
                "id": job.id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": job.url,
                "title": saved_name,
                "preset": preset_name,
                "status": "Success",
                "progress": 100.0,
                "duration": f"{duration}s",
                "size": job.saved_filesize_str,
                "target_dir": str(effective_target),
            }
            self.state.history_manager.add_entry(entry)
            BUS.publish(EventType.JOB_FINISHED, entry)
        else:
            was_cancelled = job.status in ("CANCELLED", "CANCELLING") or job.is_cancelled.is_set()
            if not was_cancelled:
                play_sound("error", enabled=config.get("sound_effects", True))
                send_windows_toast("Download Failed", job.error_message or "Unknown error", enabled=config.get("desktop_notifications", True))

            entry = {
                "id": job.id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": job.url,
                "title": job.display_title or job.saved_filename or "",
                "preset": preset_name,
                "status": "Cancelled" if was_cancelled else "Failed",
                "progress": job.progress_pct,
                "error": job.error_message,
                "target_dir": str(effective_target),
            }
            self.state.history_manager.add_entry(entry)
            BUS.publish(
                EventType.JOB_CANCELLED if was_cancelled else EventType.JOB_FAILED,
                entry,
            )

        if self.on_job_finished:
            self.on_job_finished(job, success)

    def _handle_progress(self, job: DownloadJob):
        BUS.publish(
            EventType.JOB_PROGRESS,
            {
                "job_id": job.id,
                "progress_pct": job.progress_pct,
                "speed_str": job.speed_str,
                "eta_str": job.eta_str,
                "status": job.status,
            },
        )
        if self.on_job_progress:
            self.on_job_progress(job)

    def enqueue(self, job: DownloadJob) -> str:
        """Enqueue a new download task."""
        with self.lock:
            self.pending_queue.append(job)
        BUS.publish(EventType.JOB_ENQUEUED, {"job_id": job.id, "url": job.url})
        return job.id

    def pause_queue(self):
        """Pause processing of pending tasks."""
        with self.lock:
            self.is_paused = True
        BUS.publish(EventType.JOB_PAUSED, {})

    def resume_queue(self):
        """Resume processing of pending tasks."""
        with self.lock:
            self.is_paused = False
        BUS.publish(EventType.JOB_RESUMED, {})

    def resolve_job(self, target: str) -> Optional[DownloadJob]:
        """Resolve a job by 1-based index (active followed by pending) or ID."""
        target = target.strip()
        with self.lock:
            ordered = list(self.active_jobs.values()) + list(self.pending_queue)
            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(ordered):
                    return ordered[idx - 1]
            for j in ordered:
                if j.id == target or j.id.startswith(target):
                    return j
        return None

    def cancel_job(self, target: str) -> bool:
        """Cancel a pending or active job by 1-based index or ID."""
        target = target.strip()
        with self.lock:
            ordered = list(self.active_jobs.values()) + list(self.pending_queue)
            target_job = None
            if target.isdigit():
                idx = int(target)
                if 1 <= idx <= len(ordered):
                    target_job = ordered[idx - 1]
            if not target_job:
                for j in ordered:
                    if j.id == target or j.id.startswith(target):
                        target_job = j
                        break
            if not target_job:
                return False

            if target_job in self.pending_queue:
                self.pending_queue.remove(target_job)
                target_job.status = "CANCELLED"
                self.completed_jobs.append(target_job)
                BUS.publish(EventType.JOB_CANCELLED, {"job_id": target_job.id, "url": target_job.url})
                return True

            if target_job.id in self.active_jobs:
                target_job.is_cancelled.set()
                target_job.status = "CANCELLING"
                BUS.publish(EventType.JOB_CANCELLED, {"job_id": target_job.id, "url": target_job.url})
                return True

        return False

    def cancel_all(self) -> int:
        """Cancel all pending and active jobs."""
        with self.lock:
            count = 0
            for job in list(self.pending_queue):
                self.pending_queue.remove(job)
                job.status = "CANCELLED"
                self.completed_jobs.append(job)
                BUS.publish(EventType.JOB_CANCELLED, {"job_id": job.id, "url": job.url})
                count += 1
            for job in list(self.active_jobs.values()):
                job.is_cancelled.set()
                job.status = "CANCELLING"
                BUS.publish(EventType.JOB_CANCELLED, {"job_id": job.id, "url": job.url})
                count += 1
            return count

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
        """Update worker concurrency cap and dynamically scale worker pool."""
        n = max(1, min(5, n))
        self.max_workers = n
        self.state.set_config("max_concurrent_downloads", n)
        self._ensure_workers()
