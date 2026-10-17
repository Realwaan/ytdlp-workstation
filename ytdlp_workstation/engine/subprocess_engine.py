"""
Subprocess execution engine for aria2c gigabit turbo and external downloader tasks.
"""

__all__ = ["run_subprocess_download"]

import sys
import time
import subprocess
from pathlib import Path
from typing import Callable, Optional
from ..core.state import DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..utils.system import cleanup_orphaned_fragments, set_console_title, reset_console_title
from .format_builder import build_subprocess_command
from .process_supervisor import SUPERVISOR


def run_subprocess_download(
    job: DownloadJob,
    config: dict,
    archive_path: Optional[Path] = None,
    on_progress: Optional[Callable[[DownloadJob], None]] = None
) -> bool:
    """Execute download using external yt-dlp CLI process (with aria2c multi-stream support)."""
    cmd, preset_name = build_subprocess_command(job, config, archive_path=archive_path)
    effective_target = job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR)

    job.start_time = time.time()
    job.status = "DOWNLOADING"
    captured_errors = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )
        SUPERVISOR.register(job.id, proc)

        for raw_line in proc.stdout:
            if job.is_cancelled.is_set():
                SUPERVISOR.kill_job_process(job.id)
                job.status = "CANCELLED"
                return False

            line = raw_line.strip()
            if not line:
                continue

            if "PROGRESS|P=" in line or ("P=" in line and "|D=" in line and "|S=" in line):
                parts = line.split("PROGRESS|")[-1].split("|")
                p_map = {}
                for seg in parts:
                    if "=" in seg:
                        k, v = seg.split("=", 1)
                        p_map[k.strip()] = v.strip()

                try:
                    pct_val = float(p_map.get("P", "0.0").replace("%", "").strip())
                except Exception:
                    pct_val = 0.0

                job.progress_pct = pct_val
                job.downloaded_str = p_map.get("D", "")
                job.total_str = p_map.get("T", "")
                job.speed_str = p_map.get("S", "--")
                job.eta_str = p_map.get("E", "--:--")
                job.fragment_str = p_map.get("F", "")

                set_console_title(f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")

                if on_progress:
                    on_progress(job)

            elif "[download] Destination:" in line:
                try:
                    dest = line.split("Destination:", 1)[1].strip()
                    job.saved_filename = Path(dest).name
                except Exception:
                    pass

            elif "ERROR:" in line:
                err_detail = line.replace("ERROR:", "").strip()
                if err_detail:
                    captured_errors.append(err_detail)

        proc.wait()
        success = (proc.returncode == 0)
        if not success and job.progress_pct >= 99.0:
            success = True

        if success:
            job.status = "COMPLETED"
        else:
            job.status = "FAILED"
            job.error_message = " | ".join(captured_errors[:2]) if captured_errors else f"Process exited with code {proc.returncode}"
            cleanup_orphaned_fragments(Path(effective_target))

        return success

    except Exception as e:
        job.status = "FAILED"
        job.error_message = str(e)
        cleanup_orphaned_fragments(Path(effective_target))
        return False
    finally:
        job.finish_time = time.time()
        reset_console_title()
