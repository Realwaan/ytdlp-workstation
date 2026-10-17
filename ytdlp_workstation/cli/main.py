"""
Main application entrypoint and orchestrator for ytdlp-workstation.

Wires together the queue manager, REPL loop, clipboard watcher, and process
supervisor. Thin orchestrator — command handling lives in cli/command_dispatcher,
input handling in cli/repl, clipboard monitoring in cli/clipboard.
"""

__all__ = ["main"]

import os
import sys
import threading
from pathlib import Path
from typing import Optional

from ..core.state import STATE, DownloadJob, AppState
from ..core.config import DEFAULT_DOWNLOAD_DIR, CONFIG_FILE, YTDLP_EXE
from ..queue.manager import QueueManager
from ..engine.process_supervisor import SUPERVISOR
from ..utils.system import cleanup_orphaned_fragments, bootstrap_workstation_environment
from .ui import Fore, Style, print_banner, format_linux_bar
from .repl import run_repl


def main(state: Optional[AppState] = None):
    state = state or STATE

    if os.name == "nt":
        os.system("title YT-DLP Supercharged Workstation v2.0")

    bootstrap_workstation_environment()

    # Initialize Concurrent Queue Manager
    workers = state.config.get("max_concurrent_downloads", 2)
    queue_mgr = QueueManager(max_workers=workers, state=state)

    def _render_progress(job: DownloadJob):
        bar_text = format_linux_bar(
            job.display_title or job.saved_filename or job.url,
            job.progress_pct,
            job.downloaded_str,
            job.total_str,
            job.speed_str,
            job.eta_str,
            job.fragment_str,
            status=job.status,
        )
        sys.stdout.write(bar_text)
        sys.stdout.flush()

    queue_mgr.on_job_progress = _render_progress

    try:
        run_repl(queue_mgr, state=state)
    finally:
        state.stop_requested = True
        queue_mgr.stop_requested = True
        # Reap all supervised subprocesses (yt-dlp, ffmpeg, aria2c) to avoid
        # orphaned processes holding file locks on Windows.
        SUPERVISOR.reap_all()
        # Give worker threads a moment to notice stop_requested and exit.
        for t in queue_mgr._worker_threads:
            t.join(timeout=1.0)


if __name__ == "__main__":
    main()
