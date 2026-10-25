"""
Terminal UI: Cyber-styled banner, status dashboard, progress bar formatting, and queue status cards.
"""

import os
import re
import sys
import shutil
from pathlib import Path
from typing import Tuple

for _s in (getattr(sys, "__stdout__", None), getattr(sys, "__stderr__", None), sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

try:
    import colorama
    from colorama import Fore, Style, Back
    if hasattr(colorama, "just_fix_windows_console"):
        colorama.just_fix_windows_console()
    else:
        colorama.init()
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Style = Back = DummyColor()

from ..core.state import DownloadJob, AppState, resolve_state
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..core.presets import PRESETS
from ..utils.system import get_free_disk_space_gb
from typing import Optional
from .console import CONSOLE


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return resolve_state(state)


def clear_screen() -> None:
    """Clear the terminal without leaving stale live status lines behind."""
    with CONSOLE.suspend():
        os.system("cls" if os.name == "nt" else "clear")


def print_banner(active_workers: int = 1, state: Optional[AppState] = None):
    """Print the sleek, compact terminal banner (under 10 lines)."""
    state = _resolve_state(state)
    clear_screen()
    preset_info = PRESETS.get(state.config.get("preset", 1), PRESETS[1])
    clip_mode = state.config.get("clipboard_mode", "auto").upper()

    if clip_mode == "AUTO":
        clip_badge = f"{Fore.GREEN}AUTO{Style.RESET_ALL}"
    elif clip_mode == "PROMPT":
        clip_badge = f"{Fore.YELLOW}PROMPT{Style.RESET_ALL}"
    else:
        clip_badge = f"{Fore.RED}OFF{Style.RESET_ALL}"

    ask_quality = state.config.get("ask_quality_each_time", True)
    if ask_quality:
        quality_badge = f"{Fore.MAGENTA}PICK{Style.RESET_ALL}"
    else:
        p_name = preset_info.get("name", "Default")[:12]
        quality_badge = f"{Fore.GREEN}#{state.config.get('preset', 1)} {p_name}{Style.RESET_ALL}"

    archive_mode = state.config.get("use_download_archive", True)
    archive_badge = f"{Fore.GREEN}ON{Style.RESET_ALL}" if archive_mode else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    download_folder = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    free_gb = get_free_disk_space_gb(download_folder)
    disk_badge = f"{free_gb} GB Free" if free_gb >= 0.0 else "Available"

    engine_badge = f"{Fore.CYAN}16x TURBO (ARIA2C){Style.RESET_ALL}" if ARIA2C_EXE.exists() else f"{Fore.GREEN}NATIVE YT-DLP{Style.RESET_ALL}"
    active_site = getattr(state, "last_seen_website", None) or state.config.get("default_stream_referer", "https://movy.sx/")
    workers_cnt = state.config.get("max_concurrent_downloads", 2)

    banner = f"""{Fore.CYAN}  ⚡ YT-DLP WORKSTATION v2.0 {Fore.LIGHTBLACK_EX}──────────────────────────────────────────────────{Style.RESET_ALL}
  {Fore.WHITE}[●] Engine  :{Style.RESET_ALL} {engine_badge:<25} {Fore.WHITE}[●] Workers :{Style.RESET_ALL} {Fore.GREEN}{workers_cnt} Stream(s){Style.RESET_ALL}
  {Fore.WHITE}[●] Monitor :{Style.RESET_ALL} {clip_badge:<21} {Fore.WHITE}[●] Archive :{Style.RESET_ALL} {archive_badge}
  {Fore.WHITE}[●] Quality :{Style.RESET_ALL} {quality_badge:<25} {Fore.WHITE}[●] Referer :{Style.RESET_ALL} {Fore.GREEN}{active_site}{Style.RESET_ALL}
  {Fore.WHITE}[●] Folder  :{Style.RESET_ALL} {Fore.CYAN}{download_folder}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}({disk_badge}){Style.RESET_ALL}
  {Fore.LIGHTBLACK_EX}─────────────────────────────────────────────────────────────────────────────{Style.RESET_ALL}
  {Fore.LIGHTGREEN_EX}▶ Paste any link or type {Fore.YELLOW}help{Fore.LIGHTGREEN_EX} for categorized commands. Tab autocompletes.{Style.RESET_ALL}
"""
    print(banner)

    if state.update_available:
        print(f"{Back.YELLOW}{Fore.BLACK} ★ NEW YT-DLP RELEASE AVAILABLE: v{state.update_available} {Style.RESET_ALL} {Fore.YELLOW}Type 'u' or 'update' to upgrade!{Style.RESET_ALL}\n")


def print_help(topic: Optional[str] = None) -> None:
    """Display categorized on-demand help tables."""
    t = (topic or "").strip().lower()

    if not t or t in ("all", "overview"):
        print(f"""
{Fore.CYAN}═══ YT-DLP WORKSTATION HELP & COMMAND REFERENCE ═══{Style.RESET_ALL}
  Type {Fore.YELLOW}help <category>{Style.RESET_ALL} for detailed syntax & examples:
    {Fore.CYAN}help downloads{Style.RESET_ALL} : Video links, quality shortcuts, custom naming, clips, subs
    {Fore.CYAN}help audio{Style.RESET_ALL}     : Spotify integration, YouTube Music search, MP3/FLAC
    {Fore.CYAN}help streaming{Style.RESET_ALL} : Cloud streams (.m3u8), active site referers, fragment merger
    {Fore.CYAN}help queue{Style.RESET_ALL}     : Queue inspection, cancel (e.g. 'cancel 1', 'cancel all'), workers
    {Fore.CYAN}help media{Style.RESET_ALL}     : Open folder, play video ('play 1'), reveal in explorer, retry
    {Fore.CYAN}help settings{Style.RESET_ALL}  : Cookies, SponsorBlock, speed limits, download directory

  {Fore.YELLOW}COMMON QUICK COMMANDS:{Style.RESET_ALL}
    {Fore.CYAN}[URL]{Style.RESET_ALL}                   : Instant download (auto-detected quality or picker)
    {Fore.CYAN}1080p / 720p / 4k [URL]{Style.RESET_ALL} : Download directly in specific quality
    {Fore.CYAN}mp3 / m4a / flac [URL]{Style.RESET_ALL}  : Download as audio track
    {Fore.CYAN}queue{Style.RESET_ALL}                   : View active and pending downloads
    {Fore.CYAN}cancel <1..N | all>{Style.RESET_ALL}    : Cancel active or pending downloads
    {Fore.CYAN}play <1..N | song>{Style.RESET_ALL}     : Play downloaded video OR search music
    {Fore.CYAN}reveal <1..N>{Style.RESET_ALL}           : Highlight downloaded file in Windows Explorer
    {Fore.CYAN}retry <1..N>{Style.RESET_ALL}            : Re-enqueue failed download with fresh referer
    {Fore.CYAN}merge [movie name]{Style.RESET_ALL}      : Stitch & remux orphaned fragments into MP4
    {Fore.CYAN}cls{Style.RESET_ALL}                     : Clear screen & redraw compact banner
    {Fore.CYAN}q / quit{Style.RESET_ALL}                : Exit workstation
""")
        return

    if t in ("downloads", "download", "video"):
        print(f"""
{Fore.CYAN}═══ DOWNLOAD COMMANDS ═══{Style.RESET_ALL}
  {Fore.CYAN}[URL]{Style.RESET_ALL}                     : Paste URL directly to enqueue
  {Fore.CYAN}name <title> <URL>{Style.RESET_ALL}        : Download with custom movie/video filename
  {Fore.CYAN}1080p [URL]{Style.RESET_ALL}               : Full HD 1080p
  {Fore.CYAN}720p [URL]{Style.RESET_ALL}                : HD 720p
  {Fore.CYAN}4k [URL]{Style.RESET_ALL}                  : 4K Ultra HD
  {Fore.CYAN}trim <start>-<end> <URL>{Style.RESET_ALL}   : Download clip (e.g. {Fore.YELLOW}trim 01:15-02:30 URL{Style.RESET_ALL})
  {Fore.CYAN}items <range> <URL>{Style.RESET_ALL}        : Download playlist items (e.g. {Fore.YELLOW}items 1-5 URL{Style.RESET_ALL})
  {Fore.CYAN}subs [lang] <URL>{Style.RESET_ALL}          : Embed subtitles (e.g. {Fore.YELLOW}subs en URL{Style.RESET_ALL})
  {Fore.CYAN}f <URL>{Style.RESET_ALL}                    : Inspect and pick from all exact format codes (-F)
""")
    elif t in ("audio", "music", "spotify"):
        print(f"""
{Fore.CYAN}═══ AUDIO & MUSIC COMMANDS ═══{Style.RESET_ALL}
  {Fore.CYAN}spotify <URL>{Style.RESET_ALL}              : Download Spotify track, album, or playlist (320kbps MP3)
  {Fore.CYAN}play <song title>{Style.RESET_ALL}          : Search YouTube Music & instant download as 320k MP3
  {Fore.CYAN}mp3 [URL]{Style.RESET_ALL}                 : Extract audio as MP3 (320kbps)
  {Fore.CYAN}m4a [URL]{Style.RESET_ALL}                 : Extract audio as AAC (.m4a)
  {Fore.CYAN}flac [URL]{Style.RESET_ALL}                : Extract audio as Lossless FLAC
""")
    elif t in ("streaming", "stream", "hls", "m3u8", "cloud"):
        print(f"""
{Fore.CYAN}═══ CLOUD STREAMING COMMANDS ═══{Style.RESET_ALL}
  {Fore.CYAN}ref <site> <m3u8 URL>{Style.RESET_ALL}      : Download cloud stream with explicit referer
  {Fore.CYAN}site <name/url>{Style.RESET_ALL}            : Set active streaming site (e.g. {Fore.YELLOW}site cinejoy{Style.RESET_ALL} or {Fore.YELLOW}site movy{Style.RESET_ALL})
  {Fore.CYAN}merge [movie name]{Style.RESET_ALL}         : Stitch & remux orphaned *-Frag* files into an MP4 video
  {Fore.CYAN}name <title> <URL>{Style.RESET_ALL}         : Set title for generic streams (e.g. index-s1080p-v1-a1.m3u8)
""")
    elif t in ("queue", "worker", "workers"):
        print(f"""
{Fore.CYAN}═══ QUEUE & WORKER COMMANDS ═══{Style.RESET_ALL}
  {Fore.CYAN}queue{Style.RESET_ALL} / {Fore.CYAN}qstatus{Style.RESET_ALL}              : View active and pending downloads with 1-based indices
  {Fore.CYAN}cancel <1..N | id | all>{Style.RESET_ALL}   : Cancel specific job or all active/pending downloads
  {Fore.CYAN}pause{Style.RESET_ALL}                      : Pause processing pending queue
  {Fore.CYAN}resume{Style.RESET_ALL}                     : Resume processing pending queue
  {Fore.CYAN}clearqueue{Style.RESET_ALL}                 : Clear pending queue
  {Fore.CYAN}workers <1-5>{Style.RESET_ALL}               : Set max concurrent parallel downloads (e.g. {Fore.YELLOW}workers 3{Style.RESET_ALL})
""")
    elif t in ("media", "files"):
        print(f"""
{Fore.CYAN}═══ MEDIA ACTIONS ═══{Style.RESET_ALL}
  {Fore.CYAN}play <1..N | id>{Style.RESET_ALL}           : Open completed download in default media player
  {Fore.CYAN}reveal <1..N | id>{Style.RESET_ALL}         : Highlight downloaded file in Windows File Explorer
  {Fore.CYAN}retry <1..N | id>{Style.RESET_ALL}          : Re-enqueue failed job from history with fresh referer
  {Fore.CYAN}open{Style.RESET_ALL}                        : Open the downloads directory in File Explorer
  {Fore.CYAN}history [clear]{Style.RESET_ALL}             : View download history (or 'history clear' to reset)
""")
    elif t in ("settings", "config"):
        print(f"""
{Fore.CYAN}═══ SETTINGS & PREFERENCES ═══{Style.RESET_ALL}
  {Fore.CYAN}settings{Style.RESET_ALL} / {Fore.CYAN}s{Style.RESET_ALL}              : Interactive full settings menu
  {Fore.CYAN}preset{Style.RESET_ALL} / {Fore.CYAN}p{Style.RESET_ALL}                : Select default quality preset (1-12)
  {Fore.CYAN}qmode{Style.RESET_ALL}                     : Toggle 'Ask Quality on Each Download'
  {Fore.CYAN}clip{Style.RESET_ALL} / {Fore.CYAN}c{Style.RESET_ALL}                  : Toggle clipboard auto-monitoring (auto/prompt/off)
  {Fore.CYAN}sb [on/off]{Style.RESET_ALL}                : Toggle SponsorBlock (auto-skip sponsor segments)
  {Fore.CYAN}cookies <browser>{Style.RESET_ALL}         : Set browser cookies (chrome, edge, firefox, brave, off)
  {Fore.CYAN}limit <rate>{Style.RESET_ALL}              : Set speed limit (e.g. {Fore.YELLOW}limit 5M{Style.RESET_ALL} or {Fore.YELLOW}limit off{Style.RESET_ALL})
  {Fore.CYAN}dir{Style.RESET_ALL}                        : Change download destination folder
  {Fore.CYAN}update{Style.RESET_ALL} / {Fore.CYAN}u{Style.RESET_ALL}                : Update yt-dlp to the latest version
""")
    else:
        print(f"{Fore.YELLOW}[!] Unknown help topic '{topic}'. Available: downloads, audio, streaming, queue, media, settings.{Style.RESET_ALL}\n")


def parse_speed_to_bytes(speed_str: str) -> float:
    """Parse human readable speed string (e.g. '12.5MiB/s', '800KiB/s') to bytes/sec."""
    if not speed_str or speed_str in ("--", "N/A"):
        return 0.0
    clean = speed_str.lower().replace("/s", "").replace(" ", "").strip()
    match = re.match(r"^([0-9.]+)([a-z]*)$", clean)
    if not match:
        return 0.0
    try:
        val, unit = float(match.group(1)), match.group(2)
    except ValueError:
        return 0.0
    if "g" in unit:
        return val * (1024 ** 3)
    if "m" in unit:
        return val * (1024 ** 2)
    if "k" in unit:
        return val * 1024
    return val


def format_speed_bytes(bps: float) -> str:
    """Format bytes per second into human readable string."""
    if bps >= 1024 ** 3:
        return f"{bps / (1024 ** 3):.2f} GiB/s"
    if bps >= 1024 ** 2:
        return f"{bps / (1024 ** 2):.1f} MiB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KiB/s"
    return f"{bps:.0f} B/s"


def format_aggregate_status(active_jobs: list, pending_count: int, is_paused: bool = False) -> str:
    """Format an aggregate throughput line for multi-worker downloads."""
    total_bps = sum(parse_speed_to_bytes(getattr(j, "speed_str", "")) for j in active_jobs)
    speed_text = format_speed_bytes(total_bps) if total_bps > 0 else "--"
    status_text = "PAUSED" if is_paused else "RUNNING"
    status_color = Fore.YELLOW if is_paused else Fore.GREEN
    return (
        f"{Back.CYAN}{Fore.BLACK} ⚡ MULTI-WORKER {Style.RESET_ALL} "
        f"{Fore.WHITE}[{len(active_jobs)} Active]{Style.RESET_ALL} "
        f"Speed: {Fore.GREEN}{speed_text}{Style.RESET_ALL} | "
        f"Pending: {Fore.YELLOW}{pending_count}{Style.RESET_ALL} | "
        f"Queue: {status_color}{status_text}{Style.RESET_ALL}"
    )


def _short_title(title: str, limit: int = 22) -> str:
    clean = (title or "").replace("_", " ").replace("-", " ").strip()
    if not clean:
        return "Downloading"
    return clean[: limit - 3] + "..." if len(clean) > limit else clean


def format_linux_bar(title: str, pct: float, d_str: str, t_str: str, spd: str, eta: str, f_str: str = "", status: str = "") -> str:
    """Format Linux CLI / tqdm style progress bar."""
    if status == "STARTING":
        return f"\r{Fore.CYAN}{_short_title(title, 40)}:{Style.RESET_ALL} {Fore.YELLOW}[STARTING] Connecting & extracting stream info...{Style.RESET_ALL}\033[K"

    if status == "PROCESSING":
        return f"\r{Fore.CYAN}{_short_title(title, 40)}:{Style.RESET_ALL} {Fore.YELLOW}[PROCESSING] Merging video & audio (ffmpeg)...{Style.RESET_ALL}\033[K"

    if status == "COMPLETED":
        saved = ""
        if d_str:
            saved = d_str
        return f"\r{Fore.CYAN}{_short_title(title, 40)}:{Style.RESET_ALL} {Fore.GREEN}[✓] COMPLETE — {saved or 'saved'}{Style.RESET_ALL}\033[K"

    pct = max(0.0, min(100.0, pct))
    spd = spd.strip() if spd and spd != "NA" else "--"
    eta = eta.strip() if eta and eta != "NA" else "--:--"

    if d_str and t_str:
        size_str = f"{d_str}/{t_str}"
        if f_str and f_str != "NA/NA":
            size_str += f" (frag {f_str})"
    elif d_str:
        size_str = d_str
    elif f_str and f_str != "NA/NA":
        size_str = f"frag {f_str}"
    else:
        size_str = ""

    clean_title = _short_title(title)

    term_width = shutil.get_terminal_size((80, 20)).columns
    overhead = len(clean_title) + len(size_str) + len(eta) + len(spd) + 18
    bar_width = max(10, min(32, term_width - overhead))

    filled = int(bar_width * (pct / 100.0))
    filled = max(0, min(bar_width, filled))
    empty = bar_width - filled

    bar_gfx = f"{Fore.GREEN}{'█' * filled}{Fore.LIGHTBLACK_EX}{'░' * empty}{Style.RESET_ALL}"
    return f"\r{Fore.CYAN}{clean_title}:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{pct:5.1f}%{Style.RESET_ALL}|{bar_gfx}| {Fore.YELLOW}{size_str}{Style.RESET_ALL} {Fore.WHITE}[{Fore.LIGHTCYAN_EX}{eta}{Fore.WHITE}, {Fore.LIGHTMAGENTA_EX}{spd}{Fore.WHITE}]{Style.RESET_ALL}\033[K"


def job_label(job: DownloadJob) -> str:
    return job.display_title or job.saved_filename or job.url


def format_job_progress(job: DownloadJob) -> str:
    """Single status line for an active job (used by the live status region)."""
    return format_linux_bar(
        job_label(job),
        job.progress_pct,
        job.downloaded_str,
        job.total_str,
        job.speed_str,
        job.eta_str,
        job.fragment_str,
        status=job.status,
    ).replace("\r", "").replace("\033[K", "")


def format_job_started(job: DownloadJob, preset_name: str = "") -> str:
    quality = f" {Fore.LIGHTBLACK_EX}({preset_name}){Style.RESET_ALL}" if preset_name else ""
    return f"{Fore.YELLOW}[▶] Started{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {_short_title(job_label(job), 60)}{quality}"


def format_job_result(job: DownloadJob, success: bool) -> str:
    """Permanent one-line summary written when a job leaves the queue."""
    name = _short_title(job.saved_filename or job_label(job), 60)
    if success:
        size = f" ({job.saved_filesize_str})" if job.saved_filesize_str else ""
        return f"{Fore.GREEN}[✓] Done{Style.RESET_ALL}    {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {name}{Fore.LIGHTBLACK_EX}{size}{Style.RESET_ALL}"
    if job.status in ("CANCELLED", "CANCELLING"):
        return f"{Fore.LIGHTBLACK_EX}[-] Cancelled [{job.id}] {name}{Style.RESET_ALL}"
    reason = f" — {job.error_message[:80]}" if job.error_message else ""
    return f"{Fore.RED}[✗] Failed{Style.RESET_ALL}  {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {name}{Fore.RED}{reason}{Style.RESET_ALL}"


def print_download_card(job: DownloadJob, preset_name: str, effective_target: str):
    """Render a clean status card for an upcoming download."""
    print(f"\n{Fore.CYAN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Style.BRIGHT}{Fore.YELLOW}⚡ STARTING DOWNLOAD [ID: {job.id}]{Style.RESET_ALL}")
    if job.display_title:
        print(f"{Fore.CYAN}│ {Fore.WHITE}Title  :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{job.display_title}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}URL    :{Style.RESET_ALL} {Fore.LIGHTCYAN_EX}{job.url}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}Quality:{Style.RESET_ALL} {Fore.GREEN}{preset_name}{Style.RESET_ALL}")
    if job.referer:
        print(f"{Fore.CYAN}│ {Fore.WHITE}Referer:{Style.RESET_ALL} {Fore.YELLOW}{job.referer}{Style.RESET_ALL}")
    if job.download_section:
        print(f"{Fore.CYAN}│ {Fore.WHITE}Trim   :{Style.RESET_ALL} {Fore.YELLOW}{job.download_section}{Style.RESET_ALL}")
    if job.playlist_items:
        print(f"{Fore.CYAN}│ {Fore.WHITE}Tracks :{Style.RESET_ALL} {Fore.YELLOW}{job.playlist_items}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}Target :{Style.RESET_ALL} {effective_target}")
    print(f"{Fore.CYAN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}\n")
