"""
Native Python yt-dlp execution engine using YoutubeDL class and structured progress hooks.
Eliminates fragile stdout scraping and process startup overhead.
"""

__all__ = ["execute_download_job", "HAS_YTDLP_MODULE"]

import time
from pathlib import Path
from typing import Callable, Optional
from ..core.state import DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..utils.system import cleanup_orphaned_fragments, set_console_title, reset_console_title
from .format_builder import build_native_ytdlp_opts
from .fragment_merger import find_fragment_groups, merge_fragment_group
from .subprocess_engine import run_subprocess_download

try:
    import yt_dlp
    HAS_YTDLP_MODULE = True
except ImportError:
    HAS_YTDLP_MODULE = False


class _CancelledError(Exception):
    """Raised inside yt-dlp progress hook when job.is_cancelled is set."""


def execute_download_job(
    job: DownloadJob,
    config: dict,
    archive_path: Optional[Path] = None,
    on_progress: Optional[Callable[[DownloadJob], None]] = None
) -> bool:
    """
    Main download execution entry point.
    Uses native yt_dlp.YoutubeDL with progress hooks, or subprocess engine if aria2c turbo is enabled.
    """
    if job.is_cancelled.is_set():
        job.status = "CANCELLED"
        return False

    # If aria2c is available and configured, use subprocess engine for multi-connection socket saturation
    if ARIA2C_EXE.exists():
        return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)

    if not HAS_YTDLP_MODULE:
        return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)

    opts, preset_name = build_native_ytdlp_opts(job, config, archive_path=archive_path)
    effective_target = job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR)

    job.start_time = time.time()
    job.status = "DOWNLOADING"

    def _native_hook(d: dict):
        if job.is_cancelled.is_set():
            job.status = "CANCELLED"
            raise _CancelledError("Download cancelled by user")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta")

            if total > 0:
                job.progress_pct = round((downloaded / total) * 100.0, 1)
                # Format size strings
                if total >= 1024**3:
                    job.total_str = f"{total / (1024**3):.2f}GiB"
                    job.downloaded_str = f"{downloaded / (1024**3):.2f}GiB"
                else:
                    job.total_str = f"{total / (1024**2):.1f}MiB"
                    job.downloaded_str = f"{downloaded / (1024**2):.1f}MiB"
            else:
                job.progress_pct = 0.0

            if speed:
                if speed >= 1024**2:
                    job.speed_str = f"{speed / (1024**2):.1f}MiB/s"
                else:
                    job.speed_str = f"{speed / 1024:.0f}KiB/s"
            else:
                job.speed_str = "--"

            if eta is not None:
                m, s = divmod(int(eta), 60)
                h, m = divmod(m, 60)
                job.eta_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            else:
                job.eta_str = "--:--"

            frag_idx = d.get("fragment_index")
            frag_cnt = d.get("fragment_count")
            if frag_idx and frag_cnt:
                job.fragment_str = f"{frag_idx}/{frag_cnt}"

            filename = d.get("filename")
            if filename:
                job.saved_filename = Path(filename).name

            set_console_title(f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")

            if on_progress:
                on_progress(job)

        elif status == "finished":
            job.status = "PROCESSING"
            job.progress_pct = 100.0
            filename = d.get("filename")
            if filename:
                job.saved_filename = Path(filename).name

            if on_progress:
                on_progress(job)

    opts["progress_hooks"] = [_native_hook]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ret_code = ydl.download([job.url])
            if job.is_cancelled.is_set():
                job.status = "CANCELLED"
                cleanup_orphaned_fragments(Path(effective_target))
                return False

            success = (ret_code == 0)

            frag_groups = find_fragment_groups(Path(effective_target))
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

            if success:
                job.status = "COMPLETED"
                job.progress_pct = 100.0
                if on_progress:
                    on_progress(job)
            else:
                job.status = "FAILED"
                job.error_message = f"yt-dlp returned error code {ret_code}"

            return success

    except _CancelledError:
        job.status = "CANCELLED"
        cleanup_orphaned_fragments(Path(effective_target))
        return False
    except Exception as e:
        if job.is_cancelled.is_set():
            job.status = "CANCELLED"
            cleanup_orphaned_fragments(Path(effective_target))
            return False
        # Fall back to subprocess engine if native mode hit an edge case
        try:
            return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)
        except Exception as sub_e:
            job.status = "FAILED"
            job.error_message = str(sub_e)
            cleanup_orphaned_fragments(Path(effective_target))
            return False
    finally:
        job.finish_time = time.time()
        reset_console_title()
