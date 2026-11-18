"""
Native Python yt-dlp execution engine using YoutubeDL class and structured progress hooks.
Eliminates fragile stdout scraping and process startup overhead.
"""

__all__ = ["execute_download_job", "HAS_YTDLP_MODULE"]

import time
import importlib.util
from pathlib import Path
from typing import Callable, Optional
from ..core.state import DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..utils.system import cleanup_orphaned_fragments, set_console_title, reset_console_title
from .format_builder import build_native_ytdlp_opts
from .fragment_merger import find_fragment_groups, merge_fragment_group
from .hls_turbo import is_hls_turbo_candidate, run_hls_turbo_download
from .subprocess_engine import run_subprocess_download
from . import fragment_registry

# Importing yt_dlp costs ~0.5s of startup. It is only needed when the native
# in-process backend actually runs (never while bin/aria2c.exe exists), so the
# module is resolved lazily on first use via _load_yt_dlp() / module __getattr__.
HAS_YTDLP_MODULE = importlib.util.find_spec("yt_dlp") is not None


def _load_yt_dlp():
    mod = globals().get("yt_dlp")
    if mod is None:
        import yt_dlp as mod  # noqa: WPS433 (deliberate lazy import)
        globals()["yt_dlp"] = mod
    return mod


def __getattr__(name):
    # PEP 562: keeps `native_engine.yt_dlp` (used by tests' patch targets) working.
    if name == "yt_dlp":
        if not HAS_YTDLP_MODULE:
            raise AttributeError(name)
        return _load_yt_dlp()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _CancelledError(Exception):
    """Raised inside yt-dlp progress hook when job.is_cancelled is set."""


class _CaptureLogger:
    """Minimal yt-dlp logger that records messages so archive-skip notices can be detected."""

    def __init__(self):
        self.messages = []

    def debug(self, msg):
        self.messages.append(msg)

    def info(self, msg):
        self.messages.append(msg)

    def warning(self, msg):
        self.messages.append(msg)

    def error(self, msg):
        self.messages.append(msg)


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

    # Direct HLS (.m3u8) Tokio HTTP/2 Turbo fast-path (skips creating thousands of -Frag files on disk;
    # automatically returns None and falls through to yt-dlp for encrypted, live, or multi-audio streams).
    if (
        getattr(run_subprocess_download, "__module__", "") == "ytdlp_workstation.engine.subprocess_engine"
        and is_hls_turbo_candidate(job, config)
    ):
        hls_result = run_hls_turbo_download(job, config, on_progress=on_progress)
        if hls_result is not None:
            return hls_result

    # If aria2c is available and configured, use subprocess engine for multi-connection socket saturation
    if ARIA2C_EXE.exists():
        return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)

    if not HAS_YTDLP_MODULE:
        return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)

    opts, preset_name = build_native_ytdlp_opts(job, config, archive_path=archive_path)
    effective_target = job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR)

    job.start_time = time.time()
    job.status = "DOWNLOADING"
    capture_logger = _CaptureLogger()
    opts["logger"] = capture_logger

    def _pp_hook(d: dict):
        # Fires after each postprocessor (incl. final MoveFiles) — captures the
        # real output filepath so the queue never needs to scan the folder.
        if d.get("status") == "finished":
            info = d.get("info_dict") or {}
            fp = info.get("filepath") or info.get("filename")
            if fp:
                p = Path(fp)
                job.saved_filename = p.name
                try:
                    if p.exists():
                        b = p.stat().st_size
                        if b >= 1024**3:
                            job.saved_filesize_str = f"{b / (1024**3):.2f} GB"
                        elif b >= 1024**2:
                            job.saved_filesize_str = f"{b / (1024**2):.1f} MB"
                        elif b > 0:
                            job.saved_filesize_str = f"{b / 1024:.0f} KB"
                except Exception:
                    pass

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
            tmp_name = d.get("tmpfilename") or filename
            if tmp_name:
                fragment_registry.claim(job.id, tmp_name)

            set_console_title(f"[{job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")

            if on_progress:
                on_progress(job)

        elif status == "finished":
            job.status = "PROCESSING"
            job.progress_pct = 100.0
            filename = d.get("filename")
            if filename:
                job.saved_filename = Path(filename).name
                job.output_path = str(filename)

            if on_progress:
                on_progress(job)

    opts["progress_hooks"] = [_native_hook]
    opts["postprocessor_hooks"] = [_pp_hook]

    try:
        with _load_yt_dlp().YoutubeDL(opts) as ydl:
            ret_code = ydl.download([job.url])
            if job.is_cancelled.is_set():
                job.status = "CANCELLED"
                cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
                return False

            success = (ret_code == 0)

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

            if success:
                job.status = "COMPLETED"
                job.progress_pct = 100.0
                # Detect "already downloaded" archive skips logged by yt-dlp
                if any("has already been recorded in the archive" in str(m) for m in capture_logger.messages):
                    job.was_archive_skipped = True
                if on_progress:
                    on_progress(job)
            else:
                job.status = "FAILED"
                job.error_message = f"yt-dlp returned error code {ret_code}"

            return success

    except _CancelledError:
        job.status = "CANCELLED"
        cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
        return False
    except Exception as e:
        if job.is_cancelled.is_set():
            job.status = "CANCELLED"
            cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
            return False
        # Fall back to subprocess engine if native mode hit an edge case
        try:
            return run_subprocess_download(job, config, archive_path=archive_path, on_progress=on_progress)
        except Exception as sub_e:
            job.status = "FAILED"
            job.error_message = str(sub_e)
            cleanup_orphaned_fragments(Path(effective_target), for_job=job.id)
            return False
    finally:
        job.finish_time = time.time()
        fragment_registry.release(job.id)
        reset_console_title()
