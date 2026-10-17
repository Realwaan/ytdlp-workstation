"""
Format and options builder for native yt_dlp.YoutubeDL and subprocess fallback.
Maps high-level presets and user settings into exact yt-dlp parameter dictionaries
and CLI flags. Shared resolution logic is centralized in _build_common_options
to avoid duplication between the two execution backends.
"""

__all__ = [
    "build_native_ytdlp_opts",
    "build_subprocess_command",
    "_build_common_options",
    "_resolve_preset",
    "_build_output_template",
    "_build_http_headers",
    "_build_subtitles_options",
]

import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from ..core.config import FFMPEG_EXE, YTDLP_EXE, ARIA2C_EXE, BASE_DIR, DEFAULT_DOWNLOAD_DIR
from ..core.presets import get_preset, resolve_format_sort
from ..core.state import DownloadJob
from ..extractors.referer import auto_detect_referer


def _resolve_preset(job: DownloadJob, config: Dict[str, Any]) -> Tuple[int, Dict[str, Any], str]:
    """Resolve the effective preset id, preset dict, and preset name for a job."""
    preset_id = job.preset_override or config.get("preset", 1)
    if job.force_audio:
        preset_id = 7
    elif job.force_video:
        preset_id = 1

    preset = get_preset(preset_id)
    preset_name = preset["name"]
    return preset_id, preset, preset_name


def _build_output_template(
    job: DownloadJob,
    config: Dict[str, Any],
    download_dir: Path,
) -> Any:
    """Resolve the output template (str or dict) for a job."""
    if job.custom_output_template:
        return job.custom_output_template
    return {
        "default": str(download_dir / "%(title)s [%(id)s].%(ext)s"),
        "playlist": str(download_dir / "%(playlist_title,playlist)s" / "%(playlist_index)s - %(title)s [%(id)s].%(ext)s"),
    }


def _build_http_headers(job: DownloadJob, config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Build HTTP headers dict from job referer and custom headers."""
    headers: Dict[str, str] = {}
    referer = job.referer
    if not referer:
        default_ref = (config or {}).get("default_stream_referer", "https://movy.sx/")
        referer = auto_detect_referer(job.url, default_referer=default_ref)
        if referer:
            job.referer = referer
    if referer:
        headers["Referer"] = referer
    if job.headers:
        for h in job.headers:
            if ":" in h:
                k, v = h.split(":", 1)
                headers[k.strip()] = v.strip()
    return headers


def _build_subtitles_options(
    job: DownloadJob,
    config: Dict[str, Any],
    preset: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build subtitle-related options if subtitles are enabled and not audio-only."""
    subs_mode = config.get("subtitles_mode", "off")
    if (subs_mode == "off" and not job.force_subs and not job.sub_lang) or preset.get("extract_audio"):
        return None
    lang = job.sub_lang if job.sub_lang else ("en.*" if subs_mode == "en" else "all")
    return {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [lang],
        "embed_subs": True,
    }


def _build_common_options(
    job: DownloadJob,
    config: Dict[str, Any],
    archive_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Build the complete set of resolved download options shared by both
    native and subprocess backends. Returns a dict mirroring yt-dlp native
    opts keys plus extra metadata keys used by the subprocess renderer.
    """
    _preset_id, preset, preset_name = _resolve_preset(job, config)
    download_dir = Path(job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    opts: Dict[str, Any] = {
        "outtmpl": _build_output_template(job, config, download_dir),
        "windowsfilenames": True,
        "updatetime": False,
        "nopart": True,
        "continuedl": False,
        "skip_unavailable_fragments": True,
        "concurrent_fragment_downloads": 16,
        "buffersize": 16 * 1024 * 1024,
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 20,
        "fragment_retries": 25,
        "file_access_retries": 25,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "writethumbnail": True,
        "postprocessors": [],
        "_preset_name": preset_name,
        "_preset": preset,
    }

    # FFmpeg location
    if FFMPEG_EXE.exists():
        opts["ffmpeg_location"] = str(FFMPEG_EXE.parent)

    # Download archive integration (instant duplicate skipping)
    if config.get("use_download_archive", True) and archive_path:
        opts["download_archive"] = str(archive_path)

    # Codec format sort preference
    codec_pref = config.get("codec_preference", "auto")
    fmt_sort = resolve_format_sort(codec_pref)
    if fmt_sort:
        opts["format_sort"] = fmt_sort.split(",")

    # Custom format override
    if job.custom_format_str:
        opts["format"] = job.custom_format_str
        opts["merge_output_format"] = "mp4"
        opts["_preset_name"] = f"Custom: {job.custom_format_str}"
    else:
        if preset["extract_audio"]:
            opts["format"] = preset["format"]
            opts["postprocessors"].append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": preset["audio_format"],
                "preferredquality": "0" if preset["audio_format"] == "mp3" else None,
            })
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
        else:
            opts["format"] = preset["format"]
            if preset["merge_format"]:
                opts["merge_output_format"] = preset["merge_format"]
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
            if preset.get("extra_args"):
                opts["_extra_args"] = list(preset["extra_args"])

    # Browser cookies
    cookies = config.get("browser_cookies", "none")
    if cookies and cookies != "none":
        opts["cookiesfrombrowser"] = (cookies, None, None, None)

    # Netscape cookies.txt file
    cookie_file = config.get("cookies_file", "none")
    if cookie_file and cookie_file != "none" and Path(cookie_file).exists():
        opts["cookiefile"] = str(Path(cookie_file).resolve())

    # Speed limit
    limit = config.get("speed_limit", "none")
    if limit and limit != "none":
        try:
            m = 1024 * 1024 if "m" in limit.lower() else (1024 if "k" in limit.lower() else 1)
            num = float("".join([c for c in limit if c.isdigit() or c == "."]))
            opts["ratelimit"] = int(num * m)
        except Exception:
            pass

    # Referer & HTTP Headers
    http_headers = _build_http_headers(job, config)
    if http_headers:
        opts["http_headers"] = http_headers

    # Subtitles handling
    subs_opts = _build_subtitles_options(job, config, preset)
    if subs_opts:
        opts.update(subs_opts)
        opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    # SponsorBlock
    if config.get("sponsorblock", False):
        opts["postprocessors"].append({
            "key": "SponsorBlock",
            "categories": ["sponsor", "selfpromo"],
        })
        opts["postprocessors"].append({
            "key": "ModifyChapters",
            "remove_sponsor_segments": ["sponsor", "selfpromo"],
        })

    # Playlist selective items
    if job.playlist_items:
        opts["playlist_items"] = job.playlist_items
        opts["noplaylist"] = False
    elif not job.force_playlist:
        if "playlist?list=" not in job.url:
            opts["noplaylist"] = True

    # Extra metadata tags
    if job.extra_metadata:
        opts["postprocessors"].append({
            "key": "FFmpegMetadata",
            "add_metadata": True,
        })

    # Download section (clip/trim)
    if job.download_section:
        opts["download_sections"] = f"*{job.download_section}"
        opts["force_keyframes_at_cuts"] = True

    return opts


def build_native_ytdlp_opts(
    job: DownloadJob,
    config: Dict[str, Any],
    archive_path: Optional[Path] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Construct native Python parameter dictionary for yt_dlp.YoutubeDL.
    """
    opts = _build_common_options(job, config, archive_path=archive_path)
    preset_name = opts.pop("_preset_name", "Unknown")
    opts.pop("_preset", None)
    opts.pop("_extra_args", None)

    return opts, preset_name


def build_subprocess_command(
    job: DownloadJob,
    config: Dict[str, Any],
    archive_path: Optional[Path] = None,
) -> Tuple[List[str], str]:
    """
    Construct CLI command arguments for yt-dlp.exe fallback / aria2c multi-stream.
    """
    opts = _build_common_options(job, config, archive_path=archive_path)
    preset_name = opts.pop("_preset_name", "Unknown")
    preset = opts.pop("_preset", {})
    extra_args = opts.pop("_extra_args", [])

    ytdlp_bin = str(YTDLP_EXE) if YTDLP_EXE.exists() else "yt-dlp"

    cmd: List[str] = [
        ytdlp_bin,
        "--windows-filenames",
        "--no-mtime",
        "--no-part",
        "--no-continue",
        "--skip-unavailable-fragments",
        "-N", "16",
        "--buffer-size", "16M",
        "--http-chunk-size", "10M",
        "--retries", "20",
        "--fragment-retries", "25",
        "--file-access-retries", "25",
        "--retry-sleep", "fragment:exp=1:20",
        "--retry-sleep", "file_access:exp=1:10",
        "--fixup", "warn",
        "--newline",
        "--progress-template",
        "download:PROGRESS|P=%(progress._percent_str)s|D=%(progress._downloaded_bytes_str)s|T=%(progress._total_bytes_str,progress._total_bytes_estimate_str)s|S=%(progress._speed_str)s|E=%(progress._eta_str)s|F=%(progress.fragment_index)s/%(progress.fragment_count)s",
    ]

    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])

    if ARIA2C_EXE.exists():
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader", "dash,m3u8:native",
            "--downloader-args", "aria2c:-s 16 -x 16 -k 1M -j 16",
        ])

    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])

    if opts.get("download_archive"):
        cmd.extend(["--download-archive", str(opts["download_archive"])])

    if opts.get("format_sort"):
        cmd.extend(["--format-sort", ",".join(opts["format_sort"])])

    if opts.get("cookiesfrombrowser"):
        cmd.extend(["--cookies-from-browser", str(opts["cookiesfrombrowser"][0])])

    if opts.get("cookiefile"):
        cmd.extend(["--cookies", opts["cookiefile"]])

    if opts.get("ratelimit") is not None:
        # Native backend stores bytes; subprocess backend accepts human-readable (e.g. "5M")
        raw_limit = config.get("speed_limit", "none")
        if raw_limit and raw_limit != "none":
            cmd.extend(["--limit-rate", raw_limit])

    if opts.get("http_headers"):
        for k, v in opts["http_headers"].items():
            cmd.extend(["--add-header", f"{k}:{v}"])

    if job.custom_format_str:
        cmd.extend(["-o", opts["outtmpl"]])
        cmd.extend(["-f", job.custom_format_str])
        cmd.extend(["--merge-output-format", "mp4", "--embed-thumbnail", "--embed-metadata"])
    else:
        if job.custom_output_template:
            cmd.extend(["-o", job.custom_output_template])
        else:
            download_dir = Path(job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
            out_single = str(download_dir / "%(title)s [%(id)s].%(ext)s")
            out_playlist = str(download_dir / "%(playlist_title,playlist)s" / "%(playlist_index)s - %(title)s [%(id)s].%(ext)s")
            cmd.extend(["-o", f"playlist:{out_playlist}", "-o", out_single])

        if job.download_section:
            cmd.extend(["--download-sections", f"*{job.download_section}", "--force-keyframes-at-cuts"])

        if job.playlist_items:
            cmd.extend(["--playlist-items", job.playlist_items, "--yes-playlist"])
        elif not job.force_playlist:
            if "playlist?list=" not in job.url:
                cmd.append("--no-playlist")
        else:
            cmd.append("--yes-playlist")

        if preset.get("extract_audio"):
            cmd.extend(["-x", "--audio-format", preset.get("audio_format", "mp3")])
        else:
            if preset.get("format"):
                cmd.extend(["-f", preset["format"]])
            if preset.get("merge_format"):
                cmd.extend(["--merge-output-format", preset["merge_format"]])
        if extra_args:
            cmd.extend(extra_args)

    if opts.get("writesubtitles"):
        lang = opts.get("subtitleslangs", ["all"])[0]
        cmd.extend(["--write-auto-subs", "--write-subs", "--sub-langs", lang, "--embed-subs"])

    if config.get("sponsorblock", False):
        cmd.extend(["--sponsorblock-remove", "sponsor,selfpromo"])

    cmd.append(job.url)
    return cmd, preset_name
