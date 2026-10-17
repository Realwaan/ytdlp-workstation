"""
Process Supervisor and Windows Zombie Process Reaper.
Tracks active subprocesses (yt-dlp, ffmpeg, ffprobe, aria2c) and ensures clean process tree
termination without leaving orphaned background processes consuming CPU or locking files.
"""

__all__ = ["ProcessSupervisor", "SUPERVISOR"]

import os
import sys
import time
import subprocess
import threading
from typing import Dict, List, Optional


class ProcessSupervisor:
    """Thread-safe supervisor for spawned CLI processes and process trees."""

    def __init__(self):
        self._lock = threading.Lock()
        # Maps job_id -> subprocess.Popen instance
        self._active_processes: Dict[str, subprocess.Popen] = {}
        # Track PIDs directly
        self._active_pids: Dict[str, int] = {}

    def register(self, job_id: str, proc: subprocess.Popen) -> None:
        """Register a running subprocess for tracking and supervision."""
        with self._lock:
            self._active_processes[job_id] = proc
            if hasattr(proc, "pid") and proc.pid:
                self._active_pids[job_id] = proc.pid

    def unregister(self, job_id: str) -> None:
        """Unregister a finished subprocess."""
        with self._lock:
            self._active_processes.pop(job_id, None)
            self._active_pids.pop(job_id, None)

    def is_running(self, job_id: str) -> bool:
        """Check if a registered job's process is currently running."""
        with self._lock:
            proc = self._active_processes.get(job_id)
            if not proc:
                return False
            return proc.poll() is None

    def get_pid(self, job_id: str) -> Optional[int]:
        """Get PID of a registered job."""
        with self._lock:
            return self._active_pids.get(job_id)

    def kill_job_process(self, job_id: str) -> bool:
        """
        Forcefully terminate a job's entire process tree (including child ffmpeg/aria2c).
        Uses Windows taskkill /F /T on Windows to eliminate zombie processes.
        """
        with self._lock:
            proc = self._active_processes.get(job_id)
            pid = self._active_pids.get(job_id)

        if not pid and proc and hasattr(proc, "pid"):
            pid = proc.pid

        if not pid:
            return False

        killed = self.kill_pid_tree(pid)

        if proc:
            try:
                proc.poll()
            except Exception:
                pass

        self.unregister(job_id)
        return killed

    @staticmethod
    def kill_pid_tree(pid: int) -> bool:
        """Kill a process and all of its descendants by PID."""
        if sys.platform == "win32":
            try:
                # /F = forcefully terminate, /T = terminate process tree (all child processes)
                res = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5.0
                )
                return res.returncode == 0
            except Exception:
                pass

        # Fallback for POSIX or if taskkill fails
        try:
            os.kill(pid, 9)
            return True
        except Exception:
            return False

    def reap_all(self) -> int:
        """Kill all active supervised processes on shutdown."""
        with self._lock:
            pids = list(self._active_pids.values())
            self._active_processes.clear()
            self._active_pids.clear()

        reaped = 0
        for pid in pids:
            if self.kill_pid_tree(pid):
                reaped += 1
        return reaped


# Global process supervisor instance
SUPERVISOR = ProcessSupervisor()
