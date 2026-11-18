"""
Subprocess execution engine for aria2c gigabit turbo and external downloader tasks.
"""

__all__ = ["run_subprocess_download"]

import re
import sys
import time
import threading
import subprocess
from pathlib import Path
from typing import Callable, Optional
from ..core.state import DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..utils.system import cleanup_orphaned_fragments, set_console_title, reset_console_title
from .format_builder import build_subprocess_command
from .fragment_merger import find_fragment_groups, merge_fragment_group
from .process_supervisor import SUPERVISOR
from .rust_accel import is_rust_enabled, rust_core
from . import fragment_registry

_ARIA2_RE = re.compile(
    r"\[#[0-9a-fA-F]+\s+([^\s/]+)/([^\s(]+)\((\d+(?:\.\d+)?)%\).*?DL:([^\s\]]+)(?:\s+ETA:([^\s\]]+))?"
)
# Final-output lines printed by yt-dlp after merging / audio extraction / dedupe.
_MERGER_RE = re.compile(r'\[Merger\] Merging formats into "(.+)"')
_EXTRACT_RE = re.compile(r"\[ExtractAudio\] Destination: (.+)")
_ALREADY_RE = re.compile(r"\[download\] (.+) has already been downloaded")


def _set_output(job: DownloadJob, path_str: str) -> None:
    path_str = path_str.strip().strip('"')
    if path_str:
        job.output_path = path_str
        job.saved_filename = Path(path_str).name


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
    stall_timeout = float(config.get("stall_timeout", 300) or 0)
    watchdog_stop = threading.Event()

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

        last_activity = time.time()

        def _stall_watchdog():
            """Kill the process tree when it produces no output for stall_timeout seconds."""
            while not watchdog_stop.is_set():
                watchdog_stop.wait(1.0)
                if watchdog_stop.is_set():
                    return
                if proc.poll() is not None:
                    return
                if stall_timeout > 0 and (time.time() - last_activity) > stall_timeout:
                    captured_errors.append(
                        f"No output for {int(stall_timeout)}s - process stalled and was killed"
                    )
                    SUPERVISOR.kill_job_process(job.id)
                    return

        watchdog_t = threading.Thread(target=_stall_watchdog, name=f"Watchdog-{job.id}", daemon=True)
        watchdog_t.start()

        for raw_line in proc.stdout:
            last_activity = time.time()
            if job.is_cancelled.is_set():
                SUPERVISOR.kill_job_process(job.id)
                job.status = "CANCELLED"
                return False

            line = raw_line.strip()
            if not line:
                continue

            if is_rust_enabled() and rust_core is not None and hasattr(rust_core, "parse_progress_line"):
                ev = rust_core.parse_progress_line(line)
                if ev is not None:
                    kind, pct, dl_s, tot_s, spd_s, eta_s, extra = ev
                    if kind == "progress":
                        job.status = "PROCESSING" if pct >= 100.0 else "DOWNLOADING"
                        job.progress_pct = pct
                        job.downloaded_str = dl_s
                        job.total_str = tot_s
                        job.speed_str = spd_s
                        job.eta_str = eta_s
                        job.fragment_str = extra
                        set_console_title(
                            f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation"
                        )
                        if on_progress:
                            on_progress(job)
                    elif kind == "aria2c":
                        job.status = "DOWNLOADING"
                        job.downloaded_str = dl_s
                        job.total_str = tot_s
                        job.progress_pct = pct
                        job.speed_str = spd_s
                        job.eta_str = eta_s
                        set_console_title(
                            f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation"
                        )
                        if on_progress:
                            on_progress(job)
                    elif kind == "postprocess":
                        job.status = "PROCESSING"
                        job.progress_pct = 100.0
                        if extra:
                            _set_output(job, extra)
                        if on_progress:
                            on_progress(job)
                    elif kind == "destination":
                        if extra:
                            fragment_registry.claim(job.id, extra)
                            _set_output(job, extra)
                    elif kind == "archive_skip":
                        job.was_archive_skipped = True
                        if extra:
                            _set_output(job, extra)
                    elif kind == "error":
                        if extra:
                            captured_errors.append(extra)
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

                job.status = "DOWNLOADING"
                job.progress_pct = pct_val
                job.downloaded_str = p_map.get("D", "")
                job.total_str = p_map.get("T", "")
                job.speed_str = p_map.get("S", "--")
                job.eta_str = p_map.get("E", "--:--")
                job.fragment_str = p_map.get("F", "")

                if pct_val >= 100.0 and job.status != "PROCESSING":
                    job.status = "PROCESSING"

                set_console_title(f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")

                if on_progress:
                    on_progress(job)

            elif "[#" in line and "%" in line and "DL:" in line:
                m = _ARIA2_RE.search(line)
                if m:
                    job.status = "DOWNLOADING"
                    job.downloaded_str = m.group(1)
                    job.total_str = m.group(2)
                    try:
                        job.progress_pct = float(m.group(3))
                    except Exception:
                        pass
                    job.speed_str = f"{m.group(4)}/s"
                    job.eta_str = m.group(5) or "--:--"
                    set_console_title(f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")
                    if on_progress:
                        on_progress(job)

            elif "[Merger]" in line or "[ExtractAudio]" in line:
                job.status = "PROCESSING"
                job.progress_pct = 100.0
                m = _MERGER_RE.search(line) or _EXTRACT_RE.search(line)
                if m:
                    _set_output(job, m.group(1))
                if on_progress:
                    on_progress(job)

            elif "[download] Destination:" in line:
                try:
                    dest = line.split("Destination:", 1)[1].strip()
                    fragment_registry.claim(job.id, dest)
                    _set_output(job, dest)
                except Exception:
                    pass

            elif "has already been downloaded" in line or "has already been recorded in the archive" in line:
                job.was_archive_skipped = True
                m = _ALREADY_RE.search(line)
                if m:
                    _set_output(job, m.group(1))

            elif "ERROR:" in line:
                err_detail = line.replace("ERROR:", "").strip()
                if err_detail:
                    captured_errors.append(err_detail)

        proc.wait()
        watchdog_stop.set()

        # Cancelled while yt-dlp was silent (merging, ffmpeg post-processing):
        # QueueManager.cancel_job kills the process tree, which ends stdout here.
        if job.is_cancelled.is_set():
            job.status = "CANCELLED"
            cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
            return False

        success = (proc.returncode == 0)

        # Always check the download folder after yt-dlp finishes: if *-Frag<N> files remain
        # (and the job was not cancelled), automatically stitch and remux them into a single MP4.
        frag_groups = find_fragment_groups(Path(effective_target), for_job=job.id)
        if frag_groups and not job.is_cancelled.is_set():
            for base_name, frags in frag_groups.items():
                merged_path = merge_fragment_group(
                    directory=Path(effective_target),
                    base_name=base_name,
                    frags=frags,
                    output_title=job.display_title,
                    job=job,
                    on_progress=on_progress,
                )
                if merged_path and merged_path.exists():
                    job.saved_filename = merged_path.name
                    success = True
        elif not success and not frag_groups and job.progress_pct >= 99.0:
            success = True

        if success:
            job.status = "COMPLETED"
            job.progress_pct = 100.0
            if on_progress:
                on_progress(job)
        else:
            job.status = "FAILED"
            job.error_message = " | ".join(captured_errors[:2]) if captured_errors else f"Process exited with code {proc.returncode}"
            cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)

        return success

    except Exception as e:
        job.status = "FAILED"
        job.error_message = str(e)
        cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
        return False
    finally:
        watchdog_stop.set()
        job.finish_time = time.time()
        # Forget the finished PID: otherwise reap_all() at exit runs `taskkill /T`
        # on stale PIDs that Windows may already have reused for unrelated processes.
        SUPERVISOR.unregister(job.id)
        fragment_registry.release(job.id)
        reset_console_title()
