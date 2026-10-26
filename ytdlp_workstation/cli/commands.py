"""
Terminal CLI power command handlers and dispatcher.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..core.state import DownloadJob, AppState, resolve_state
from ..core.config import YTDLP_EXE, DEFAULT_DOWNLOAD_DIR
from ..core.presets import PRESETS, QUALITY_SHORTCUT_MAP
from ..extractors.url_detector import is_valid_media_url, extract_media_url, GENERIC_URL_REGEX
from ..extractors.referer import auto_detect_referer, KNOWN_STREAMING_DOMAINS
from ..extractors.title_detector import detect_stream_title
from ..extractors.spotify import is_spotify_url, resolve_spotify_url, build_music_search_query
from ..extractors.no_watermark import resolve_no_watermark_media
from ..extractors.web_sniffer import sniff_web_media
from ..engine.watermark_remover import clean_video
from ..utils.system import sanitize_filename, open_file_or_folder, reveal_in_file_manager
from .ui import Fore, Style, print_banner
from .input_reader import read_single_choice, prompt_video_quality, inspect_and_pick_formats, ask_text


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return resolve_state(state)


def enqueue_spotify_download(url: str, queue_mgr, state: Optional[AppState] = None) -> bool:
    """Resolve Spotify track, album, or playlist and queue for high-fidelity 320kbps download."""
    state = _resolve_state(state)
    print(f"\n{Fore.CYAN}[⚡] Resolving Spotify metadata...{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}{url}{Style.RESET_ALL}")
    data = resolve_spotify_url(url)
    if not data or not data.get("tracks"):
        print(f"{Fore.RED}[!] Could not resolve Spotify media from URL.{Style.RESET_ALL}\n")
        return False

    ent_type = data["type"].capitalize()
    ent_title = data["title"]
    ent_artist = data["artist"]
    tracks = data["tracks"]
    total = len(tracks)
    thumbnail = data.get("thumbnail", "")

    download_dir = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    target_folder = download_dir
    if data["type"] in ("album", "playlist") and total > 1:
        folder_label = f"{sanitize_filename(ent_artist)} - {sanitize_filename(ent_title)}" if ent_artist and data["type"] == "album" else sanitize_filename(ent_title)
        target_folder = download_dir / folder_label
        target_folder.mkdir(parents=True, exist_ok=True)

    print(f"{Fore.GREEN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Style.BRIGHT}{Fore.WHITE}🎵 SPOTIFY STUDIO ENGINE v2.0{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Type   :{Style.RESET_ALL} {Fore.YELLOW}{ent_type}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Title  :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{ent_title}{Style.RESET_ALL}")
    if ent_artist:
        print(f"{Fore.GREEN}│ {Fore.WHITE}Artist :{Style.RESET_ALL} {Fore.LIGHTCYAN_EX}{ent_artist}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Tracks :{Style.RESET_ALL} {Fore.WHITE}{total} track(s){Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Quality:{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}High-Fidelity 320kbps MP3 + ID3 Tags + Album Art{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Save In:{Style.RESET_ALL} {Fore.CYAN}{target_folder}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}\n")

    provider = state.config.get("music_engine_provider", "ytm")

    for idx, t in enumerate(tracks, 1):
        t_title = t["title"]
        t_artist = t["artist"]
        t_album = t.get("album") or ent_title

        search_query = build_music_search_query(t_artist, t_title, provider=provider)

        if total == 1:
            out_tmpl = str(target_folder / f"{sanitize_filename(t_artist)} - {sanitize_filename(t_title)}.%(ext)s")
            disp = f"{t_artist} - {t_title}"
        else:
            out_tmpl = str(target_folder / f"{idx:02d} - {sanitize_filename(t_title)}.%(ext)s")
            disp = f"[{idx:02d}/{total:02d}] {t_artist} - {t_title}"

        job = DownloadJob(
            url=search_query,
            display_title=disp,
            preset_override=7,
            force_audio=True,
            target_dir=str(target_folder),
            custom_output_template=out_tmpl,
            extra_metadata={
                "artist": t_artist,
                "title": t_title,
                "album": t_album,
                "track_number": str(idx),
                "track_count": str(total)
            },
            spotify_thumbnail=thumbnail
        )
        queue_mgr.enqueue(job)

    if total > 1:
        print(f"{Fore.GREEN}[✓] Queued {total} tracks into folder:{Style.RESET_ALL} {Fore.CYAN}{target_folder.name}{Style.RESET_ALL}\n")
    else:
        print(f"{Fore.GREEN}[✓] Queued track for 320kbps studio download!{Style.RESET_ALL}\n")
    return True


def enqueue_media_url(url: str, queue_mgr, state: Optional[AppState] = None, referer: Optional[str] = None, **job_kwargs) -> bool:
    """Queue a media URL, asking for quality first when the user wants that.

    Must run on the main thread (it may prompt). Returns True if queued.
    """
    state = _resolve_state(state)
    target_url = url
    if state.config.get("prefer_no_watermark", True) and "custom_format_str" not in job_kwargs:
        try:
            detected_nowm = resolve_no_watermark_media(url)
        except Exception:
            detected_nowm = None
        if detected_nowm and detected_nowm.direct_url:
            target_url = detected_nowm.direct_url
            if detected_nowm.referer:
                referer = detected_nowm.referer
            if not job_kwargs.get("display_title") and detected_nowm.title:
                job_kwargs["display_title"] = detected_nowm.title
            print(f"{Fore.GREEN}[💧] Auto-detected clean unwatermarked stream for {detected_nowm.platform}!{Style.RESET_ALL}")

    if referer is None:
        referer = auto_detect_referer(target_url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
    job = DownloadJob(url=target_url, referer=referer, **job_kwargs)
    if not job.display_title and (referer or ".m3u8" in target_url.lower() or "/vd/" in target_url.lower()):
        detected = detect_stream_title(target_url, last_seen_website=state.last_seen_website)
        if detected:
            job.display_title = detected
            print(f"{Fore.GREEN}[🎬] Auto-detected Movie Title:{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{detected}{Style.RESET_ALL}")
    wants_prompt = state.config.get("ask_quality_each_time", True)
    if wants_prompt and job.preset_override is None and not job.custom_format_str:
        preset_id, custom_fmt = prompt_video_quality(target_url, referer=referer, state=state, job=job)
        if preset_id is None and custom_fmt is None:
            return False
        job.preset_override = preset_id
        job.custom_format_str = custom_fmt
    queue_mgr.enqueue(job)
    title_note = f"{Fore.LIGHTGREEN_EX}{job.display_title}{Style.RESET_ALL} — " if job.display_title else ""
    ref_note = f" {Fore.LIGHTBLACK_EX}(referer: {referer}){Style.RESET_ALL}" if referer else ""
    print(f"{Fore.GREEN}[+] Queued{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {title_note}{target_url}{ref_note}\n")
    return True


def cmd_queue_status(queue_mgr):
    """Display real-time concurrent queue status with 1-based index numbers."""
    info = queue_mgr.list_jobs()
    active = info["active"]
    pending = info["pending"]
    completed = info["completed"]

    print(f"\n{Fore.CYAN}═══ 🚀 CONCURRENT DOWNLOAD QUEUE STATUS ═══{Style.RESET_ALL}")
    print(f"Workers: {Fore.GREEN}{len(active)} active / {queue_mgr.max_workers} max parallel{Style.RESET_ALL} | Status: {Fore.YELLOW if queue_mgr.is_paused else Fore.GREEN}{'PAUSED' if queue_mgr.is_paused else 'RUNNING'}{Style.RESET_ALL}")

    current_idx = 1
    if active:
        print(f"\n{Fore.YELLOW}[Active Downloads]{Style.RESET_ALL}")
        for j in active:
            name = j.display_title or j.saved_filename or j.url[:45]
            print(f"  {Fore.GREEN}[{current_idx}]{Style.RESET_ALL} {Fore.CYAN}[{j.id[:8]}]{Style.RESET_ALL} {Fore.WHITE}{name}{Style.RESET_ALL} - {Fore.GREEN}{j.progress_pct:.1f}%{Style.RESET_ALL} [{j.speed_str}, ETA: {j.eta_str}]")
            current_idx += 1

    if pending:
        print(f"\n{Fore.LIGHTBLACK_EX}[Pending Tasks ({len(pending)})]{Style.RESET_ALL}")
        for j in pending[:10]:
            name = j.display_title or j.url[:50]
            print(f"  {Fore.YELLOW}[{current_idx}]{Style.RESET_ALL} {Fore.LIGHTCYAN_EX}[{j.id[:8]}]{Style.RESET_ALL} {name}")
            current_idx += 1
        if len(pending) > 10:
            print(f"  ...and {len(pending) - 10} more.")

    if not active and not pending:
        print(f"{Fore.LIGHTBLACK_EX}Queue is currently empty.{Style.RESET_ALL}")

    print(f"\n{Fore.LIGHTBLACK_EX}Commands: 'cancel <1..N | id | all>', 'pause', 'resume', 'workers <1-5>', 'clearqueue'{Style.RESET_ALL}\n")


def resolve_media_file_by_target(target: str, state: AppState) -> Optional[Path]:
    """Find a downloaded file by 1-based index (1 = latest) or job ID/name."""
    target = (target or "1").strip().strip("\"'")
    download_dir = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))

    # 1. Check history entries (most recent first)
    entries = [e for e in state.history_manager.get_entries(limit=50) if e.get("status") == "Success"]
    matched_entry = None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(entries):
            matched_entry = entries[idx - 1]
    else:
        for e in entries:
            eid = str(e.get("id", ""))
            efn = str(e.get("saved_filename", "") or e.get("title", ""))
            if target == eid or eid.startswith(target) or target.lower() in efn.lower():
                matched_entry = e
                break

    if matched_entry:
        fn = matched_entry.get("saved_filename") or matched_entry.get("title")
        if fn:
            p = download_dir / fn
            if p.exists():
                return p
            p2 = Path(fn)
            if p2.exists():
                return p2

    # 2. Fallback to scanning download directory by modification time
    if download_dir.exists():
        media_files = sorted(
            [f for f in download_dir.glob("*.*") if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".flac", ".wav", ".ts")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if target.isdigit():
            idx = int(target)
            if 1 <= idx <= len(media_files):
                return media_files[idx - 1]
        elif not target and media_files:
            return media_files[0]
        else:
            for mf in media_files:
                if target.lower() in mf.name.lower():
                    return mf

    return None


def cmd_play(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Play downloaded media if index/id given; otherwise search YouTube Music."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    arg = parts[1].strip().strip("\"'") if len(parts) > 1 else ""

    # If argument is a digit index (e.g. 'play 1') or matches a completed file/ID, open media
    if arg:
        media_file = resolve_media_file_by_target(arg, state)
        if media_file and media_file.exists():
            print(f"\n{Fore.GREEN}[▶] Launching media player:{Style.RESET_ALL} {Fore.WHITE}{media_file.name}{Style.RESET_ALL}\n")
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(media_file))
                else:
                    open_file_or_folder(media_file)
            except Exception as e:
                print(f"{Fore.RED}[!] Could not launch player: {e}{Style.RESET_ALL}\n")
            return

    # If it starts with watch or view without song text, try latest file
    first_word = parts[0].lower()
    if first_word in ("watch", "view") and not arg:
        media_file = resolve_media_file_by_target("1", state)
        if media_file and media_file.exists():
            print(f"\n{Fore.GREEN}[▶] Launching media player:{Style.RESET_ALL} {Fore.WHITE}{media_file.name}{Style.RESET_ALL}\n")
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(media_file))
                else:
                    open_file_or_folder(media_file)
            except Exception as e:
                print(f"{Fore.RED}[!] Could not launch player: {e}{Style.RESET_ALL}\n")
            return

    # Otherwise YouTube Music instant search
    query = arg
    if not query:
        print(f"\n{Fore.CYAN}═══ 🎵 Instant Music Search ═══{Style.RESET_ALL}")
        query = ask_text(f"{Fore.WHITE}Enter artist or song title >>> {Style.RESET_ALL}", state).strip("\"'")

    if not query:
        print(f"{Fore.LIGHTBLACK_EX}[!] Cancelled.{Style.RESET_ALL}\n")
        return

    provider = state.config.get("music_engine_provider", "ytm")
    prefix = "ytmsearch1:" if provider == "ytm" else "ytsearch1:"
    search_target = f"{prefix}{query} Audio"

    print(f"\n{Fore.GREEN}[🔍] Searching & downloading top track:{Style.RESET_ALL} {Fore.CYAN}{query}{Style.RESET_ALL}")
    job = DownloadJob(
        url=search_target,
        preset_override=7,
        force_audio=True,
        display_title=f"🎵 {query.title()}"
    )
    queue_mgr.enqueue(job)
    print(f"{Fore.LIGHTBLACK_EX}    Queued top match as 320kbps MP3 with album artwork.{Style.RESET_ALL}\n")


def cmd_reveal(raw: str, state: Optional[AppState] = None):
    """Open Windows File Explorer with the downloaded file selected."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    target = parts[1].strip().strip("\"'") if len(parts) > 1 else "1"

    download_dir = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    media_file = resolve_media_file_by_target(target, state)

    if media_file and media_file.exists():
        print(f"\n{Fore.GREEN}[📂] Revealing in Explorer:{Style.RESET_ALL} {Fore.WHITE}{media_file.name}{Style.RESET_ALL}\n")
        try:
            if not reveal_in_file_manager(media_file):
                if hasattr(os, "startfile"):
                    os.startfile(str(download_dir))
                else:
                    open_file_or_folder(download_dir)
        except Exception:
            if hasattr(os, "startfile"):
                os.startfile(str(download_dir))
            else:
                open_file_or_folder(download_dir)
    else:
        print(f"\n{Fore.YELLOW}[!] File not found. Opening downloads folder...{Style.RESET_ALL}\n")
        download_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(download_dir))
        else:
            open_file_or_folder(download_dir)


def cmd_retry(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Re-enqueue a failed download from history, refreshing streaming referer if needed."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    target = parts[1].strip().strip("\"'") if len(parts) > 1 else "1"

    entries = [e for e in state.history_manager.get_entries(limit=50) if e.get("status") == "Failed"]
    if not entries:
        print(f"\n{Fore.YELLOW}[!] No failed downloads found in recent history.{Style.RESET_ALL}\n")
        return

    matched = None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(entries):
            matched = entries[idx - 1]
    else:
        for e in entries:
            eid = str(e.get("id", ""))
            eurl = str(e.get("url", ""))
            etit = str(e.get("title", ""))
            if target == eid or eid.startswith(target) or target in eurl or target in etit:
                matched = e
                break

    if not matched:
        print(f"\n{Fore.RED}[!] Could not find failed job matching '{target}'. (Found {len(entries)} failed tasks in history){Style.RESET_ALL}\n")
        return

    url = matched.get("url")
    if not url:
        print(f"\n{Fore.RED}[!] History entry does not contain a valid URL.{Style.RESET_ALL}\n")
        return

    fresh_ref = auto_detect_referer(url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
    title = matched.get("title")

    new_job = DownloadJob(
        url=url,
        referer=fresh_ref,
        display_title=title,
    )
    queue_mgr.enqueue(new_job)
    print(f"\n{Fore.GREEN}[✓] Re-enqueued failed task #{str(matched.get('id', ''))[:8]}:{Style.RESET_ALL}")
    print(f"    Title  : {Fore.WHITE}{title or url}{Style.RESET_ALL}")
    print(f"    Referer: {Fore.GREEN}{fresh_ref}{Style.RESET_ALL}\n")


def cmd_search(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Search YouTube and interactively pick from top 5 results."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ 🔎 Search YouTube Videos ═══{Style.RESET_ALL}")
        query = ask_text(f"{Fore.WHITE}Search query >>> {Style.RESET_ALL}", state).strip("\"'")

    if not query:
        return

    print(f"\n{Fore.CYAN}[🔍] Searching YouTube for:{Style.RESET_ALL} {Fore.WHITE}\"{query}\"...{Style.RESET_ALL}")
    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--dump-json",
        "--flat-playlist",
        "--default-search", "ytsearch5",
        query
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
        items = []
        for line in res.stdout.strip().split("\n"):
            if line.strip():
                try:
                    items.append(json.loads(line.strip()))
                except Exception:
                    pass

        if not items:
            print(f"{Fore.RED}[!] No results found for \"{query}\".{Style.RESET_ALL}\n")
            return

        print(f"\n{Fore.CYAN}═══ 🔎 RESULTS FOR: {Fore.WHITE}\"{query}\"{Fore.CYAN} ═══{Style.RESET_ALL}")
        valid_keys = {"s"}
        for idx, it in enumerate(items, 1):
            t = it.get("title", "Unknown Title")
            d_sec = it.get("duration")
            if d_sec:
                m, s = divmod(int(d_sec), 60)
                h, m = divmod(m, 60)
                dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            else:
                dur_str = "--:--"
            ch = it.get("channel") or it.get("uploader") or "Unknown"
            valid_keys.add(str(idx))
            print(f"  {Fore.LIGHTGREEN_EX}[{idx}]{Style.RESET_ALL} {Fore.WHITE}{t[:65]}{Style.RESET_ALL}")
            print(f"      {Fore.LIGHTBLACK_EX}Duration: {dur_str} | Channel: {ch}{Style.RESET_ALL}")

        valid_keys.add("a")
        print(f"\n  {Fore.YELLOW}[a] Download ALL {len(items)} results{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}[s] Skip / Cancel{Style.RESET_ALL}\n")

        choice = read_single_choice(valid_keys, default_val="s", state=state, prompt=f"{Fore.LIGHTWHITE_EX}Pick a result: {Style.RESET_ALL}")
        if choice == "s":
            print(f"{Fore.LIGHTBLACK_EX}[!] Search cancelled.{Style.RESET_ALL}\n")
            return

        if choice == "a":
            for it in items:
                v_id = it.get("id") or it.get("url")
                v_url = f"https://www.youtube.com/watch?v={v_id}" if len(str(v_id)) == 11 else str(v_id)
                queue_mgr.enqueue(DownloadJob(url=v_url, display_title=it.get("title")))
            print(f"{Fore.GREEN}[+] Queued all {len(items)} videos!{Style.RESET_ALL}\n")
        elif choice.isdigit() and 1 <= int(choice) <= len(items):
            pick = items[int(choice) - 1]
            v_id = pick.get("id") or pick.get("url")
            v_url = f"https://www.youtube.com/watch?v={v_id}" if len(str(v_id)) == 11 else str(v_id)
            queue_mgr.enqueue(DownloadJob(url=v_url, display_title=pick.get("title")))
            print(f"{Fore.GREEN}[+] Queued:{Style.RESET_ALL} {pick.get('title')}\n")

    except Exception as e:
        print(f"{Fore.RED}[!] Search error: {e}{Style.RESET_ALL}\n")


def cmd_inspect(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Inspect video metadata, available resolutions, audio streams, and subs."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        url_in = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ ℹ️ Media Information Inspector ═══{Style.RESET_ALL}")
        url_in = ask_text(f"{Fore.WHITE}Paste Media URL >>> {Style.RESET_ALL}", state).strip("\"'")

    if not url_in or not is_valid_media_url(url_in):
        print(f"{Fore.RED}[!] Invalid media URL.{Style.RESET_ALL}\n")
        return

    url = extract_media_url(url_in) or url_in
    auto_ref = auto_detect_referer(url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
    print(f"\n{Fore.CYAN}[*] Fetching metadata for:{Style.RESET_ALL} {Fore.WHITE}{url}...{Style.RESET_ALL}")

    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--dump-single-json",
        "--no-playlist",
    ]
    if auto_ref:
        cmd.extend(["--referer", auto_ref])
    cmd.append(url)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        if res.returncode != 0 or not res.stdout.strip():
            print(f"{Fore.RED}[!] Could not retrieve video info. ({res.stderr.strip()[:100]}){Style.RESET_ALL}\n")
            return

        info = json.loads(res.stdout)
        title = info.get("title", "Unknown")
        uploader = info.get("uploader") or info.get("channel") or "Unknown"
        duration_sec = info.get("duration")
        if duration_sec:
            m, s = divmod(int(duration_sec), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        else:
            dur_str = "--:--"

        views = f"{info.get('view_count'):,}" if info.get("view_count") else "N/A"
        up_date = info.get("upload_date")
        date_str = f"{up_date[:4]}-{up_date[4:6]}-{up_date[6:]}" if up_date and len(up_date) == 8 else "N/A"

        formats = info.get("formats", [])
        heights = sorted(list({f.get("height") for f in formats if f.get("height")}), reverse=True)
        res_tags = []
        for h in heights[:6]:
            if h >= 2160:
                res_tags.append("4K (2160p)")
            elif h >= 1440:
                res_tags.append("2K (1440p)")
            elif h >= 1080:
                res_tags.append("1080p")
            elif h >= 720:
                res_tags.append("720p")
            elif h >= 480:
                res_tags.append("480p")
            elif h >= 360:
                res_tags.append("360p")
        res_str = ", ".join(res_tags) if res_tags else "Direct Stream"

        acodecs = sorted(list({f.get("acodec") for f in formats if f.get("acodec") and f.get("acodec") != "none"}))
        clean_audio = [a.split(".")[0] for a in acodecs]
        audio_str = ", ".join(sorted(list(set(clean_audio)))) if clean_audio else "Standard Audio"

        sub_keys = list(info.get("subtitles", {}).keys())
        sub_str = ", ".join(sub_keys[:6]) + ("..." if len(sub_keys) > 6 else "") if sub_keys else "None available"

        print(f"\n{Fore.CYAN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Style.BRIGHT}{Fore.YELLOW}ℹ️  MEDIA SPECIFICATIONS{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Title    :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{title[:58]}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Channel  :{Style.RESET_ALL} {Fore.CYAN}{uploader}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Duration :{Style.RESET_ALL} {dur_str}  |  {Fore.WHITE}Views:{Style.RESET_ALL} {views}  |  {Fore.WHITE}Date:{Style.RESET_ALL} {date_str}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Formats  :{Style.RESET_ALL} {Fore.LIGHTMAGENTA_EX}{res_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Audio    :{Style.RESET_ALL} {Fore.LIGHTBLUE_EX}{audio_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Subs     :{Style.RESET_ALL} {Fore.YELLOW}{sub_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}")

        choice = read_single_choice(
            {"1", "2", "3", "s"}, default_val="s", state=state,
            prompt=f"{Fore.WHITE}Quick Action:{Style.RESET_ALL} [1] Best Video [2] 1080p [3] MP3 Audio [s] Skip: ",
        )
        if choice == "1":
            queue_mgr.enqueue(DownloadJob(url=url, referer=auto_ref, preset_override=1))
            print(f"{Fore.GREEN}[+] Queued in Best Available Quality!{Style.RESET_ALL}\n")
        elif choice == "2":
            queue_mgr.enqueue(DownloadJob(url=url, referer=auto_ref, preset_override=3))
            print(f"{Fore.GREEN}[+] Queued in 1080p Full HD!{Style.RESET_ALL}\n")
        elif choice == "3":
            queue_mgr.enqueue(DownloadJob(url=url, referer=auto_ref, preset_override=7, force_audio=True))
            print(f"{Fore.GREEN}[+] Queued as 320kbps MP3 Audio!{Style.RESET_ALL}\n")

    except Exception as e:
        print(f"{Fore.RED}[!] Inspector error: {e}{Style.RESET_ALL}\n")


def cmd_archive_management(raw: str, state: Optional[AppState] = None):
    """View or manage download archive."""
    state = _resolve_state(state)
    parts = raw.split()
    archive_file = state.history_manager.archive_file
    if len(parts) > 1 and parts[1].lower() in ("clear", "reset"):
        try:
            if archive_file.exists():
                archive_file.unlink()
            state.history_manager._archive_cache.clear()
            print(f"\n{Fore.GREEN}[✓] Download archive cleared!{Style.RESET_ALL}\n")
        except Exception as e:
            print(f"{Fore.RED}[!] Could not clear archive: {e}{Style.RESET_ALL}\n")
        return

    print(f"\n{Fore.CYAN}═══ 💾 DOWNLOAD ARCHIVE TRACKER ═══{Style.RESET_ALL}")
    print(f"File: {Fore.YELLOW}{archive_file}{Style.RESET_ALL}")
    count = len(state.history_manager._archive_cache)
    print(f"Total Archived Video IDs: {Fore.GREEN}{count} items{Style.RESET_ALL}")
    status = "ACTIVE (Duplicate downloads are instantly skipped)" if state.config.get("use_download_archive", True) else "OFF"
    print(f"Status: {Fore.GREEN if state.config.get('use_download_archive', True) else Fore.RED}{status}{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLACK_EX}Commands: 'archive toggle' to enable/disable, 'archive clear' to reset.{Style.RESET_ALL}\n")
    if len(parts) > 1 and parts[1].lower() == "toggle":
        cur = state.config.get("use_download_archive", True)
        state.set_config("use_download_archive", not cur)
        print(f"{Fore.GREEN}[✓] Archive duplicate skipping is now: {'ON' if not cur else 'OFF'}{Style.RESET_ALL}\n")


def cmd_codec(raw: str, state: Optional[AppState] = None):
    """Switch codec preference: codec [auto/compat/quality]."""
    state = _resolve_state(state)
    parts = raw.split()
    if len(parts) > 1:
        val = parts[1].lower()
        if val in ("compat", "compatibility", "h264", "mp4"):
            state.set_config("codec_preference", "compatibility")
            print(f"\n{Fore.GREEN}[✓] Codec preference set to: COMPATIBILITY (Forces H.264 + AAC for TV/editor compatibility){Style.RESET_ALL}\n")
        elif val in ("quality", "av1", "vp9"):
            state.set_config("codec_preference", "quality")
            print(f"\n{Fore.GREEN}[✓] Codec preference set to: MAXIMUM QUALITY (Prefers AV1/VP9 next-gen video){Style.RESET_ALL}\n")
        else:
            state.set_config("codec_preference", "auto")
            print(f"\n{Fore.GREEN}[✓] Codec preference set to: AUTO (Default yt-dlp format resolution){Style.RESET_ALL}\n")
    else:
        cur = state.config.get("codec_preference", "auto").upper()
        print(f"\n{Fore.CYAN}Current Codec Preference: {Fore.GREEN}{cur}{Style.RESET_ALL}")
        print("Options: 'codec compat' (H.264/AAC for smart TVs), 'codec quality' (AV1/VP9), 'codec auto'\n")


def handle_preset_shortcut(keyword: str, arg: str, queue_mgr, state: Optional[AppState] = None) -> bool:
    """Handle resolution and audio shortcut commands (1080p, 720p, mp3, flac, etc.)."""
    state = _resolve_state(state)
    if keyword not in QUALITY_SHORTCUT_MAP:
        return False
    if not arg or not is_valid_media_url(arg):
        print(f"{Fore.RED}[!] Usage: {keyword} <URL>{Style.RESET_ALL}")
        return True

    preset_id, force_audio, label = QUALITY_SHORTCUT_MAP[keyword]
    url = extract_media_url(arg)
    auto_ref = auto_detect_referer(url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
    job = DownloadJob(
        url=url,
        referer=auto_ref,
        preset_override=preset_id,
        force_audio=force_audio
    )
    queue_mgr.enqueue(job)
    print(f"{Fore.GREEN}[+] Queued in {label}:{Style.RESET_ALL} {url}")
    return True


def cmd_nowm(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Download clean unwatermarked video from TikTok, Douyin, CapCut, or sniff arbitrary web page."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        url_in = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ 💧 Clean / No-Watermark Downloader ═══{Style.RESET_ALL}")
        url_in = ask_text(f"{Fore.WHITE}Paste video or page URL >>> {Style.RESET_ALL}", state).strip("\"'")

    if not url_in:
        return

    url = extract_media_url(url_in) or url_in
    print(f"\n{Fore.CYAN}[🔍] Resolving unwatermarked media stream for:{Style.RESET_ALL} {Fore.WHITE}{url}{Style.RESET_ALL}")

    media = resolve_no_watermark_media(url)
    if media and media.direct_url:
        print(f"{Fore.GREEN}[✓] Successfully extracted unwatermarked stream! ({media.platform}){Style.RESET_ALL}")
        if media.title:
            print(f"    {Fore.WHITE}Title: {Fore.LIGHTGREEN_EX}{media.title}{Style.RESET_ALL}")
        job = DownloadJob(
            url=media.direct_url,
            referer=media.referer or url,
            display_title=media.title,
        )
        queue_mgr.enqueue(job)
        print(f"{Fore.GREEN}[+] Queued clean direct stream:{Style.RESET_ALL} {media.direct_url[:80]}...\n")
        return

    # Fallback to web sniffer
    print(f"{Fore.YELLOW}[*] Direct mobile unwatermarker returned no match. Sniffing web player...{Style.RESET_ALL}")
    streams = sniff_web_media(url)
    if streams:
        print(f"{Fore.GREEN}[✓] Found {len(streams)} embedded stream(s) on page!{Style.RESET_ALL}")
        for idx, s in enumerate(streams[:5], 1):
            print(f"  [{idx}] {s.stream_type.upper()}: {s.url[:70]}...")
        top_stream = streams[0]
        job = DownloadJob(
            url=top_stream.url,
            referer=top_stream.referer or url,
            display_title=top_stream.title,
        )
        queue_mgr.enqueue(job)
        print(f"{Fore.GREEN}[+] Queued best sniffed stream!{Style.RESET_ALL}\n")
        return

    # Standard enqueue with prefer_no_watermark format injection
    print(f"{Fore.LIGHTCYAN_EX}[*] Queuing URL with active yt-dlp unwatermarked format selectors...{Style.RESET_ALL}")
    enqueue_media_url(url, queue_mgr, state=state)


def cmd_sniff(raw: str, queue_mgr, state: Optional[AppState] = None):
    """Sniff arbitrary web pages for hidden video streams (.m3u8, .mpd, .mp4)."""
    state = _resolve_state(state)
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        url_in = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ 🌐 Universal Web Video Sniffer ═══{Style.RESET_ALL}")
        url_in = ask_text(f"{Fore.WHITE}Enter webpage URL to sniff >>> {Style.RESET_ALL}", state).strip("\"'")

    if not url_in:
        return

    url = extract_media_url(url_in) or url_in
    print(f"\n{Fore.CYAN}[🔎] Sniffing webpage for embedded media streams...{Style.RESET_ALL}")
    streams = sniff_web_media(url)
    if not streams:
        print(f"{Fore.RED}[!] No video streams or player configs found on page.{Style.RESET_ALL}\n")
        return

    print(f"\n{Fore.GREEN}═══ 🎬 FOUND {len(streams)} STREAM(S) ═══{Style.RESET_ALL}")
    valid_keys = {"s"}
    for idx, s in enumerate(streams[:8], 1):
        valid_keys.add(str(idx))
        tit = s.title or "Embedded Video"
        print(f"  {Fore.LIGHTGREEN_EX}[{idx}]{Style.RESET_ALL} {Fore.WHITE}{tit[:60]}{Style.RESET_ALL}")
        print(f"      {Fore.CYAN}{s.stream_type.upper()}{Style.RESET_ALL} | {Fore.LIGHTBLACK_EX}{s.url[:70]}...{Style.RESET_ALL}")

    print(f"\n  {Fore.YELLOW}[s] Skip / Cancel{Style.RESET_ALL}\n")
    choice = read_single_choice(valid_keys, default_val="1", state=state, prompt=f"{Fore.WHITE}Select stream to download: {Style.RESET_ALL}")
    if choice == "s":
        print(f"{Fore.LIGHTBLACK_EX}[!] Sniffer cancelled.{Style.RESET_ALL}\n")
        return

    chosen = streams[int(choice) - 1]
    job = DownloadJob(
        url=chosen.url,
        referer=chosen.referer or url,
        display_title=chosen.title,
    )
    queue_mgr.enqueue(job)
    print(f"\n{Fore.GREEN}[+] Queued sniffed stream:{Style.RESET_ALL} {chosen.url}\n")


def cmd_clean(raw: str, state: Optional[AppState] = None):
    """Remove burned-in watermark or crop bottom watermark bar from a video file."""
    state = _resolve_state(state)
    parts = raw.split()
    target = parts[1].strip("\"'") if len(parts) > 1 else "1"
    mode = parts[2].lower() if len(parts) > 2 else ""

    media_file = resolve_media_file_by_target(target, state)
    if not media_file or not media_file.exists():
        if Path(target).exists():
            media_file = Path(target)
        else:
            print(f"\n{Fore.RED}[!] Could not find target video: {target}{Style.RESET_ALL}\n")
            return

    if not mode:
        print(f"\n{Fore.CYAN}═══ 🧼 Video Watermark Cleanup ═══{Style.RESET_ALL}")
        print(f"File: {Fore.GREEN}{media_file.name}{Style.RESET_ALL}")
        print("  [1] Delogo (blur/interpolate corner watermark logo)")
        print("  [2] Crop (crop away bottom watermark banner, e.g. 60px)")
        choice = read_single_choice({"1", "2", "s"}, default_val="1", state=state, prompt=f"{Fore.WHITE}Choose mode: {Style.RESET_ALL}")
        if choice == "s":
            return
        mode = "delogo" if choice == "1" else "crop"

    print(f"\n{Fore.CYAN}[⚡] Processing video with FFmpeg ({mode})...{Style.RESET_ALL}")
    out = clean_video(media_file, mode=mode)
    if out and out.exists():
        sz_mb = out.stat().st_size / (1024 * 1024)
        print(f"{Fore.GREEN}[✓] Watermark cleanup completed!{Style.RESET_ALL}")
        print(f"    Saved: {Fore.LIGHTGREEN_EX}{out.name}{Style.RESET_ALL} ({sz_mb:.1f} MB)\n")
    else:
        print(f"{Fore.RED}[!] Cleanup failed. Check that FFmpeg is available and file is not locked.{Style.RESET_ALL}\n")

