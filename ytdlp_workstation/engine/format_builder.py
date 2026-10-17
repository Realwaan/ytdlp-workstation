"""
Format and options builder for native yt_dlp.YoutubeDL and subprocess fallback.
Maps high-level presets and user settings into exact yt-dlp parameter dictionaries and CLI flags.
"""

import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from ..core.config import FFMPEG_EXE, BASE_DIR, DEFAULT_DOWNLOAD_DIR
from ..core.presets import get_preset, resolve_format_sort
from ..core.state import DownloadJob


def build_native_ytdlp_opts(job: DownloadJob, config: Dict[str, Any], archive_path: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
    """
    Construct native Python parameter dictionary for yt_dlp.YoutubeDL.
    """
    preset_id = job.preset_override or config.get("preset", 1)
    if job.force_audio:
        preset_id = 7
    elif job.force_video:
        preset_id = 1

    preset = get_preset(preset_id)
    preset_name = preset["name"]
    download_dir = Path(job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    # Output template configuration
    if job.custom_output_template:
        outtmpl = job.custom_output_template
    else:
        outtmpl = {
            "default": str(download_dir / "%(title)s [%(id)s].%(ext)s"),
            "playlist": str(download_dir / "%(playlist_title,playlist)s" / "%(playlist_index)s - %(title)s [%(id)s].%(ext)s")
        }

    opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
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
        "postprocessors": []
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
        preset_name = f"Custom: {job.custom_format_str}"
    else:
        # Standard preset format
        if preset["extract_audio"]:
            opts["format"] = preset["format"]
            opts["postprocessors"].append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": preset["audio_format"],
                "preferredquality": "0" if preset["audio_format"] == "mp3" else None
            })
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
        else:
            opts["format"] = preset["format"]
            if preset["merge_format"]:
                opts["merge_output_format"] = preset["merge_format"]
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
            opts["postprocessors"].append({"key": "EmbedThumbnail"})

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
        # Convert 5M to bytes
        try:
            m = 1024 * 1024 if "m" in limit.lower() else (1024 if "k" in limit.lower() else 1)
            num = float("".join([c for c in limit if c.isdigit() or c == "."]))
            opts["ratelimit"] = int(num * m)
        except Exception:
            pass

    # Referer & HTTP Headers
    http_headers = {}
    if job.referer:
        http_headers["Referer"] = job.referer
    if job.headers:
        for h in job.headers:
            if ":" in h:
                k, v = h.split(":", 1)
                http_headers[k.strip()] = v.strip()
    if http_headers:
        opts["http_headers"] = http_headers

    # Subtitles handling
    subs_mode = config.get("subtitles_mode", "off")
    if (subs_mode != "off" or job.force_subs or job.sub_lang) and not preset.get("extract_audio"):
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        lang = job.sub_lang if job.sub_lang else ("en.*" if subs_mode == "en" else "all")
        opts["subtitleslangs"] = [lang]
        opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    # SponsorBlock
    if config.get("sponsorblock", False):
        opts["postprocessors"].append({
            "key": "SponsorBlock",
            "categories": ["sponsor", "selfpromo"]
        })
        opts["postprocessors"].append({
            "key": "ModifyChapters",
            "remove_sponsor_segments": ["sponsor", "selfpromo"]
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
            "add_metadata": True
        })

    return opts, preset_name


def build_subprocess_command(job: DownloadJob, config: Dict[str, Any], archive_path: Optional[Path] = None) -> Tuple[List[str], str]:
    """
    Construct CLI command arguments for yt-dlp.exe fallback / aria2c multi-stream.
    """
    preset_id = job.preset_override or config.get("preset", 1)
    if job.force_audio:
        preset_id = 7
    elif job.force_video:
        preset_id = 1

    preset = get_preset(preset_id)
    preset_name = preset["name"]
    download_dir = Path(job.target_dir or config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    ytdlp_bin = str(BASE_DIR / "yt-dlp.exe") if (BASE_DIR / "yt-dlp.exe").exists() else "yt-dlp"

    cmd = [
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
        "download:PROGRESS|P=%(progress._percent_str)s|D=%(progress._downloaded_bytes_str)s|T=%(progress._total_bytes_str,progress._total_bytes_estimate_str)s|S=%(progress._speed_str)s|E=%(progress._eta_str)s|F=%(progress.fragment_index)s/%(progress.fragment_count)s"
    ]

    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])

    aria2c_exe = BASE_DIR / "aria2c.exe"
    if aria2c_exe.exists():
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader", "dash,m3u8:native",
            "--downloader-args", "aria2c:-s 16 -x 16 -k 1M -j 16"
        ])

    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])

    if config.get("use_download_archive", True) and archive_path:
        cmd.extend(["--download-archive", str(archive_path)])

    codec_pref = config.get("codec_preference", "auto")
    fmt_sort = resolve_format_sort(codec_pref)
    if fmt_sort:
        cmd.extend(["--format-sort", fmt_sort])

    cookies = config.get("browser_cookies", "none")
    if cookies != "none":
        cmd.extend(["--cookies-from-browser", cookies])

    cookie_file = config.get("cookies_file", "none")
    if cookie_file != "none" and Path(cookie_file).exists():
        cmd.extend(["--cookies", str(Path(cookie_file).resolve())])

    limit = config.get("speed_limit", "none")
    if limit != "none":
        cmd.extend(["--limit-rate", limit])

    if job.referer:
        cmd.extend(["--referer", job.referer])
    if job.headers:
        for h in job.headers:
            cmd.extend(["--add-header", h])

    if job.custom_output_template:
        cmd.extend(["-o", job.custom_output_template])
    else:
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

    if job.custom_format_str:
        cmd.extend(["-f", job.custom_format_str])
        cmd.extend(["--merge-output-format", "mp4", "--embed-thumbnail", "--embed-metadata"])
        preset_name = f"Custom: {job.custom_format_str}"
    else:
        preset_name = preset["name"]
        if preset["extract_audio"]:
            cmd.extend(["-x", "--audio-format", preset["audio_format"]])
        else:
            if preset["format"]:
                cmd.extend(["-f", preset["format"]])
            if preset["merge_format"]:
                cmd.extend(["--merge-output-format", preset["merge_format"]])
        if preset.get("extra_args"):
            cmd.extend(preset["extra_args"])

    subs_mode = config.get("subtitles_mode", "off")
    if (subs_mode != "off" or job.force_subs or job.sub_lang) and not preset.get("extract_audio"):
        lang = job.sub_lang if job.sub_lang else ("en.*" if subs_mode == "en" else "all")
        cmd.extend(["--write-auto-subs", "--write-subs", "--sub-langs", lang, "--embed-subs"])

    if config.get("sponsorblock", False):
        cmd.extend(["--sponsorblock-remove", "sponsor,selfpromo"])

    cmd.append(job.url)
    return cmd, preset_name
