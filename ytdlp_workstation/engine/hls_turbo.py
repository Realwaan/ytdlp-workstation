"""
Tokio HTTP/2 HLS (`.m3u8`) Turbo Segment Engine wrapper.

Streams VOD unencrypted HLS segments concurrently over pooled HTTP/2 connections
directly into a single coalesced file (zero `*-Frag<N>` disk churn) via
`ytdlp_rust_core`, then remuxes into a fast-seeking `.mp4` container with FFmpeg.

Automatically returns `None` to delegate encrypted (`#EXT-X-KEY`), live, or
demuxed-audio (`#EXT-X-MEDIA:TYPE=AUDIO`) manifests transparently to `yt-dlp`.
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..core.config import DEFAULT_DOWNLOAD_DIR, FFMPEG_EXE
from ..core.state import DownloadJob
from ..extractors.title_detector import detect_stream_title, extract_resolution_tag
from ..utils.system import reset_console_title, sanitize_filename, set_console_title
from .format_builder import _build_http_headers, _resolve_preset
from .rust_accel import is_rust_enabled, rust_core

__all__ = [
    "PRESET_MAX_HEIGHT",
    "is_hls_turbo_candidate",
    "parse_m3u8_playlist",
    "run_hls_turbo_download",
]

PRESET_MAX_HEIGHT: Dict[int, Optional[int]] = {
    1: None,   # 4K / Best Available
    2: 1440,   # 2K Quad HD
    3: 1080,   # Full HD
    4: 720,    # HD
    5: 480,    # SD
    6: 360,    # Data Saver
}


def parse_m3u8_playlist(content: str, base_url: str) -> Optional[Any]:
    """Parse an `.m3u8` Master or Media playlist via `ytdlp_rust_core` if available."""
    if not content or not is_rust_enabled() or rust_core is None:
        return None
    if not hasattr(rust_core, "parse_m3u8_playlist"):
        return None
    return rust_core.parse_m3u8_playlist(content, base_url)


def is_hls_turbo_candidate(job: DownloadJob, config: Dict[str, Any]) -> bool:
    """Return True if `job` is eligible for direct Rust Tokio HTTP/2 HLS Turbo downloading."""
    if not is_rust_enabled() or rust_core is None or not hasattr(rust_core, "download_hls_stream"):
        return False
    if not config.get("rust_hls_turbo", True):
        return False

    raw_url = (job.url or "").strip()
    if not raw_url.startswith(("http://", "https://")):
        return False
    base_path = raw_url.split("?", 1)[0].split("#", 1)[0].lower()
    if not base_path.endswith(".m3u8"):
        return False

    # Delegate specialized post-processing jobs to yt-dlp
    if (
        job.download_section
        or job.custom_format_str
        or job.playlist_items
        or job.force_playlist
        or job.force_audio
        or job.force_subs
        or job.sub_lang
    ):
        return False

    preset_id, preset, _ = _resolve_preset(job, config)
    if preset.get("extract_audio") or preset_id not in PRESET_MAX_HEIGHT:
        return False

    if config.get("subtitles_mode", "off") != "off":
        return False
    if config.get("sponsorblock", False):
        return False
    if config.get("speed_limit", "none") not in ("none", "", None):
        return False
    if config.get("browser_cookies", "none") not in ("none", "", None):
        return False
    if config.get("cookies_file", "none") not in ("none", "", None):
        return False

    return True


def _resolve_hls_target_mp4(job: DownloadJob, download_dir: Path) -> Path:
    """Resolve collision-safe `.mp4` output path for an HLS job."""
    if job.custom_output_template and "%(" not in str(job.custom_output_template):
        p = Path(str(job.custom_output_template))
        return p if p.suffix else p.with_suffix(".mp4")

    if job.custom_output_template and "%(ext)s" in str(job.custom_output_template):
        rendered = str(job.custom_output_template).replace("%(ext)s", "mp4")
        if "%(" not in rendered:
            return Path(rendered)

    url_hash = hashlib.sha256(job.url.encode("utf-8")).hexdigest()[:8]
    res_tag = extract_resolution_tag(job.url)
    title = job.display_title or detect_stream_title(job.url) or f"HLS Stream {url_hash}"
    job.display_title = title

    clean_name = sanitize_filename(title)
    if clean_name.lower().endswith(".mp4"):
        clean_name = clean_name[:-4].strip()

    stem = (
        f"{clean_name} [{res_tag}]"
        if (res_tag and res_tag.lower() not in clean_name.lower())
        else clean_name
    )
    candidate = download_dir / f"{stem}.mp4"
    if candidate.exists():
        candidate = download_dir / f"{stem} [{url_hash}].mp4"
    return candidate


def run_hls_turbo_download(
    job: DownloadJob,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[DownloadJob], None]] = None,
    concurrency: int = 16,
) -> Optional[bool]:
    """
    Attempt to download `job.url` via the Rust Tokio HTTP/2 HLS Turbo engine.

    Returns:
      - `True` if downloaded and remuxed successfully
      - `False` if cancelled by the user
      - `None` if the manifest requires `yt-dlp` fallback (encrypted, live, separate audio, HTTP error)
    """
    if not is_rust_enabled() or rust_core is None or not hasattr(rust_core, "download_hls_stream"):
        return None

    if job.is_cancelled.is_set():
        job.status = "CANCELLED"
        return False

    preset_id, _, _ = _resolve_preset(job, config)
    max_height = PRESET_MAX_HEIGHT.get(preset_id)
    download_dir = Path(job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    headers = _build_http_headers(job, config)
    final_mp4 = _resolve_hls_target_mp4(job, download_dir)
    staging_file = final_mp4.with_suffix(".hls_part.ts")

    job.start_time = time.time()
    job.status = "DOWNLOADING"

    def _progress_hook(
        downloaded_bytes: int,
        est_total_bytes: int,
        speed_bps: float,
        eta_secs: int,
        completed_segs: int,
        total_segs: int,
    ) -> None:
        job.status = "DOWNLOADING"
        if total_segs > 0:
            job.progress_pct = round((completed_segs / total_segs) * 100.0, 1)
            job.fragment_str = f"{completed_segs}/{total_segs}"
        if est_total_bytes >= 1024 ** 3:
            job.downloaded_str = f"{downloaded_bytes / (1024 ** 3):.2f}GiB"
            job.total_str = f"{est_total_bytes / (1024 ** 3):.2f}GiB"
        else:
            job.downloaded_str = f"{downloaded_bytes / (1024 ** 2):.1f}MiB"
            job.total_str = f"{est_total_bytes / (1024 ** 2):.1f}MiB"

        if speed_bps >= 1024 ** 2:
            job.speed_str = f"{speed_bps / (1024 ** 2):.1f}MiB/s"
        elif speed_bps > 0:
            job.speed_str = f"{speed_bps / 1024:.0f}KiB/s"
        else:
            job.speed_str = "--"

        m, s = divmod(int(eta_secs), 60)
        h, m = divmod(m, 60)
        job.eta_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        set_console_title(f"[HLS {job.progress_pct:.1f}% - {job.speed_str} - ETA {job.eta_str}] YT-DLP Workstation")
        if on_progress:
            on_progress(job)

    try:
        status_str, written_bytes, _, _ = rust_core.download_hls_stream(
            job.url,
            str(staging_file),
            headers,
            max_height,
            concurrency,
            8,
            25.0,
            100,
            job.is_cancelled.is_set,
            _progress_hook,
        )
    except Exception:
        staging_file.unlink(missing_ok=True)
        return None

    if status_str == "cancelled" or job.is_cancelled.is_set():
        staging_file.unlink(missing_ok=True)
        job.status = "CANCELLED"
        reset_console_title()
        return False

    if status_str != "ok" or written_bytes == 0 or not staging_file.exists():
        staging_file.unlink(missing_ok=True)
        return None

    # Remux raw MPEG-TS / fMP4 stream into fast-seeking MP4 container via FFmpeg (-c copy)
    job.status = "PROCESSING"
    job.progress_pct = 100.0
    if on_progress:
        on_progress(job)

    ffmpeg_bin = str(FFMPEG_EXE) if FFMPEG_EXE.exists() else "ffmpeg"
    remuxed_ok = False
    try:
        res = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(staging_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(final_mp4),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode == 0 and final_mp4.exists() and final_mp4.stat().st_size > 0:
            remuxed_ok = True
            staging_file.unlink(missing_ok=True)
    except Exception:
        remuxed_ok = False

    if not remuxed_ok:
        # Keep raw stream directly as final_mp4 if FFmpeg isn't installed or stream is already fMP4
        staging_file.replace(final_mp4)

    try:
        sz = final_mp4.stat().st_size
        if sz >= 1024 ** 3:
            job.saved_filesize_str = f"{sz / (1024 ** 3):.2f} GB"
        elif sz >= 1024 ** 2:
            job.saved_filesize_str = f"{sz / (1024 ** 2):.1f} MB"
        elif sz > 0:
            job.saved_filesize_str = f"{sz / 1024:.0f} KB"
    except Exception:
        pass

    job.saved_filename = final_mp4.name
    job.output_path = str(final_mp4)
    job.finish_time = time.time()
    job.status = "COMPLETED"
    job.progress_pct = 100.0
    if on_progress:
        on_progress(job)
    reset_console_title()
    return True
