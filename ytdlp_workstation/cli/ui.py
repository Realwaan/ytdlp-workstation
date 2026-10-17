"""
Terminal UI: Cyber-styled banner, status dashboard, progress bar formatting, and queue status cards.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Tuple

try:
    import colorama
    from colorama import Fore, Style, Back
    colorama.init(autoreset=True)
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Style = Back = DummyColor()

from ..core.state import STATE, DownloadJob, AppState
from ..core.config import DEFAULT_DOWNLOAD_DIR, ARIA2C_EXE
from ..core.presets import PRESETS
from ..utils.system import get_free_disk_space_gb
from typing import Optional


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return state if state is not None else STATE


def print_banner(active_workers: int = 1, state: Optional[AppState] = None):
    """Print the cyber-styled terminal banner and status dashboard."""
    state = _resolve_state(state)
    os.system("cls" if os.name == "nt" else "clear")
    preset_info = PRESETS.get(state.config.get("preset", 1), PRESETS[1])
    clip_mode = state.config.get("clipboard_mode", "auto").upper()

    if clip_mode == "AUTO":
        clip_badge = f"{Back.GREEN}{Fore.BLACK} ACTIVE (AUTO-DETECT) {Style.RESET_ALL}"
    elif clip_mode == "PROMPT":
        clip_badge = f"{Back.YELLOW}{Fore.BLACK} ACTIVE (ASK FIRST) {Style.RESET_ALL}"
    else:
        clip_badge = f"{Back.RED}{Fore.WHITE} DISABLED {Style.RESET_ALL}"

    ask_quality = state.config.get("ask_quality_each_time", True)
    if ask_quality:
        quality_badge = f"{Back.MAGENTA}{Fore.WHITE} PICK ON DOWNLOAD {Style.RESET_ALL} {Fore.LIGHTMAGENTA_EX}(Single-key choices per link){Style.RESET_ALL}"
    else:
        quality_badge = f"{Back.BLUE}{Fore.WHITE} AUTO USE PRESET {Style.RESET_ALL} {Fore.GREEN}#{state.config.get('preset', 1)} ({preset_info['name']}){Style.RESET_ALL}"

    cookies_mode = state.config.get("browser_cookies", "none").upper()
    cookies_badge = f"{Fore.GREEN}{cookies_mode}{Style.RESET_ALL}" if cookies_mode != "NONE" else f"{Fore.LIGHTBLACK_EX}NONE{Style.RESET_ALL}"

    subs_mode = state.config.get("subtitles_mode", "off").upper()
    subs_badge = f"{Fore.GREEN}{subs_mode}{Style.RESET_ALL}" if subs_mode != "OFF" else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    speed_limit = state.config.get("speed_limit", "none").upper()
    speed_badge = f"{Fore.YELLOW}{speed_limit}{Style.RESET_ALL}" if speed_limit != "NONE" else f"{Fore.LIGHTBLACK_EX}UNLIMITED{Style.RESET_ALL}"

    sb_mode = state.config.get("sponsorblock", False)
    sb_badge = f"{Fore.GREEN}ON{Style.RESET_ALL}" if sb_mode else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    archive_mode = state.config.get("use_download_archive", True)
    archive_badge = f"{Fore.GREEN}ACTIVE (Skip Duplicates){Style.RESET_ALL}" if archive_mode else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    download_folder = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    free_gb = get_free_disk_space_gb(download_folder)
    if free_gb >= 10.0:
        disk_badge = f"{Fore.GREEN}{free_gb} GB Free{Style.RESET_ALL}"
    elif free_gb >= 0.0:
        disk_badge = f"{Fore.RED}⚠️ LOW: {free_gb} GB Free{Style.RESET_ALL}"
    else:
        disk_badge = f"{Fore.LIGHTBLACK_EX}Available{Style.RESET_ALL}"

    engine_badge = f"{Back.CYAN}{Fore.BLACK} 16x GIGABIT TURBO (ARIA2C + NATIVE MULTI-STREAM) {Style.RESET_ALL}" if ARIA2C_EXE.exists() else f"{Back.GREEN}{Fore.BLACK} NATIVE YOUTUBEDL ENGINE {Style.RESET_ALL}"
    active_site = getattr(state, "last_seen_website", None) or state.config.get("default_stream_referer", "https://movy.sx/")
    workers_cnt = state.config.get("max_concurrent_downloads", 2)

    banner = f"""{Fore.CYAN}
  ██╗   ██╗████████╗   ██████╗ ██╗     ██████╗ 
  ╚██╗ ██╔╝╚══██╔══╝   ██╔══██╗██║     ██╔══██╗
   ╚████╔╝    ██║█████╗██║  ██║██║     ██████╔╝
    ╚██╔╝     ██║╚════╝██║  ██║██║     ██╔═══╝ 
     ██║      ██║      ██████╔╝███████╗██║     
     ╚═╝      ╚═╝      ╚═════╝ ╚══════╝╚═╝     
   {Style.BRIGHT}{Fore.YELLOW}★ SUPERCHARGED DOWNLOAD WORKSTATION v2.0 ★{Style.RESET_ALL}
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
  {Fore.WHITE}[●] ENGINE SPEED       :{Style.RESET_ALL} {engine_badge}
  {Fore.WHITE}[●] PARALLEL WORKERS   :{Style.RESET_ALL} {Fore.GREEN}{workers_cnt} Concurrent Stream(s){Style.RESET_ALL}
  {Fore.WHITE}[●] CLIPBOARD MONITOR  :{Style.RESET_ALL} {clip_badge}
  {Fore.WHITE}[●] STREAMING DETECTOR :{Style.RESET_ALL} {Fore.GREEN}{active_site}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Auto-attaches referer){Style.RESET_ALL}
  {Fore.WHITE}[●] DOWNLOAD ARCHIVE   :{Style.RESET_ALL} {archive_badge}
  {Fore.WHITE}[●] QUALITY MODE       :{Style.RESET_ALL} {quality_badge}
  {Fore.WHITE}[●] BROWSER COOKIES    :{Style.RESET_ALL} {cookies_badge} (Bypasses login & age walls)
  {Fore.WHITE}[●] SUBTITLES          :{Style.RESET_ALL} {subs_badge} | {Fore.WHITE}SPEED LIMIT:{Style.RESET_ALL} {speed_badge} | {Fore.WHITE}SPONSORBLOCK:{Style.RESET_ALL} {sb_badge}
  {Fore.WHITE}[●] SAVE DIRECTORY     :{Style.RESET_ALL} {Fore.CYAN}{download_folder}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}({disk_badge}{Fore.LIGHTBLACK_EX}){Style.RESET_ALL}
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
  {Style.BRIGHT}{Fore.LIGHTWHITE_EX}HOW TO DOWNLOAD:{Style.RESET_ALL}
  {Fore.LIGHTGREEN_EX}▶ Just COPY any video OR Spotify link in your browser!{Style.RESET_ALL}
    Terminal detects it immediately and prompts for quality or downloads.
  {Fore.LIGHTBLACK_EX}──────────────────────────────────────────────────────────────────{Style.RESET_ALL}
  {Fore.LIGHTYELLOW_EX}POWER COMMANDS:{Style.RESET_ALL}
  {Fore.CYAN}[URL]{Style.RESET_ALL}                   : Paste URL directly to download
  {Fore.CYAN}play <song/video>{Style.RESET_ALL}       : Search YouTube Music & instant download as 320k MP3
  {Fore.CYAN}yt <query>{Style.RESET_ALL}                 : Search YouTube and pick from top 5 results
  {Fore.CYAN}info [URL]{Style.RESET_ALL}                 : Inspect video details, max resolution, audio & subs
  {Fore.CYAN}spotify [URL]{Style.RESET_ALL}           : Download Spotify track, album, or playlist (320kbps MP3)
  {Fore.CYAN}queue{Style.RESET_ALL} / {Fore.CYAN}qstatus{Style.RESET_ALL}            : View active parallel workers and pending jobs
  {Fore.CYAN}workers <1-5>{Style.RESET_ALL}             : Set max concurrent parallel downloads (e.g. workers 3)
  {Fore.CYAN}site <name/url>{Style.RESET_ALL}         : Switch active streaming site (e.g. {Fore.YELLOW}site cinejoy{Style.RESET_ALL} or {Fore.YELLOW}site movy{Style.RESET_ALL})
  {Fore.CYAN}trim <start>-<end> [URL]{Style.RESET_ALL} : Download specific time clip (e.g. {Fore.YELLOW}trim 01:15-02:30 URL{Style.RESET_ALL})
  {Fore.CYAN}items <range> [URL]{Style.RESET_ALL}      : Download playlist items (e.g. {Fore.YELLOW}items 1-5 URL{Style.RESET_ALL})
  {Fore.CYAN}1080p [URL]{Style.RESET_ALL}             : Download in 1080p Full HD
  {Fore.CYAN}720p [URL]{Style.RESET_ALL}              : Download in 720p HD
  {Fore.CYAN}4k [URL]{Style.RESET_ALL}                : Download in 4K / Best Quality
  {Fore.CYAN}mp3 [URL]{Style.RESET_ALL}               : Download as MP3 (320kbps)
  {Fore.CYAN}m4a [URL]{Style.RESET_ALL}               : Download as Original AAC Audio (.m4a)
  {Fore.CYAN}flac [URL]{Style.RESET_ALL}              : Download as Lossless Studio FLAC
  {Fore.CYAN}subs [lang] [URL]{Style.RESET_ALL}        : Embed subtitles (e.g. {Fore.YELLOW}subs en URL{Style.RESET_ALL} or {Fore.YELLOW}subs list URL{Style.RESET_ALL})
  {Fore.CYAN}sb [on/off]{Style.RESET_ALL}              : Toggle SponsorBlock (auto-skip sponsors/promos)
  {Fore.CYAN}ref [site] [URL]{Style.RESET_ALL}        : Cloud stream with Referer (or type 'ref' alone for guided)
  {Fore.CYAN}f [URL]{Style.RESET_ALL}                 : Inspect & pick from ALL exact format codes (-F)
  {Fore.CYAN}cookies <browser>{Style.RESET_ALL}       : Set cookies (chrome / edge / firefox / brave / off)
  {Fore.CYAN}limit <rate>{Style.RESET_ALL}            : Set speed limit (e.g. limit 5M, limit 10M, limit off)
  {Fore.CYAN}p{Style.RESET_ALL} or {Fore.CYAN}preset{Style.RESET_ALL}              : Choose default quality preset (1-12)
  {Fore.CYAN}qmode{Style.RESET_ALL}                   : Toggle Quality Picker (Pick Choices / Auto Preset)
  {Fore.CYAN}c{Style.RESET_ALL} or {Fore.CYAN}clip{Style.RESET_ALL}                : Toggle Clipboard Mode (Auto / Prompt / Off)
  {Fore.CYAN}o{Style.RESET_ALL} or {Fore.CYAN}open{Style.RESET_ALL}                : Open Downloads Folder in Explorer
  {Fore.CYAN}d{Style.RESET_ALL} or {Fore.CYAN}dir{Style.RESET_ALL}                 : Change Downloads Folder
  {Fore.CYAN}h{Style.RESET_ALL} or {Fore.CYAN}history{Style.RESET_ALL} [clear]     : View Download History (or 'h clear' to reset)
  {Fore.CYAN}s{Style.RESET_ALL} or {Fore.CYAN}settings{Style.RESET_ALL}            : Full Settings Menu
  {Fore.CYAN}u{Style.RESET_ALL} or {Fore.CYAN}update{Style.RESET_ALL}              : Update yt-dlp to latest version
  {Fore.CYAN}cls{Style.RESET_ALL}                    : Clear screen and refresh status
  {Fore.CYAN}q{Style.RESET_ALL} or {Fore.CYAN}exit{Style.RESET_ALL}                : Exit
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
"""
    print(banner)

    if state.update_available:
        print(f"{Back.YELLOW}{Fore.BLACK} ★ NEW YT-DLP RELEASE AVAILABLE: v{state.update_available} {Style.RESET_ALL} {Fore.YELLOW}Type 'u' or 'update' to upgrade!{Style.RESET_ALL}\n")


def format_linux_bar(title: str, pct: float, d_str: str, t_str: str, spd: str, eta: str, f_str: str = "") -> str:
    """Format Linux CLI / tqdm style progress bar."""
    pct = max(0.0, min(100.0, pct))
    spd = spd.strip() if spd and spd != "NA" else "--"
    eta = eta.strip() if eta and eta != "NA" else "--:--"

    if d_str and t_str:
        size_str = f"{d_str}/{t_str}"
    elif d_str:
        size_str = d_str
    elif f_str and f_str != "NA/NA":
        size_str = f"frag {f_str}"
    else:
        size_str = ""

    clean_title = title.replace("_", " ").replace("-", " ").strip()
    if len(clean_title) > 22:
        clean_title = clean_title[:19] + "..."
    elif not clean_title:
        clean_title = "Downloading"

    term_width = shutil.get_terminal_size((80, 20)).columns
    overhead = len(clean_title) + len(size_str) + len(eta) + len(spd) + 18
    bar_width = max(10, min(32, term_width - overhead))

    filled = int(bar_width * (pct / 100.0))
    filled = max(0, min(bar_width, filled))
    empty = bar_width - filled

    bar_gfx = f"{Fore.GREEN}{'█' * filled}{Fore.LIGHTBLACK_EX}{'░' * empty}{Style.RESET_ALL}"
    return f"\r{Fore.CYAN}{clean_title}:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{pct:5.1f}%{Style.RESET_ALL}|{bar_gfx}| {Fore.YELLOW}{size_str}{Style.RESET_ALL} {Fore.WHITE}[{Fore.LIGHTCYAN_EX}{eta}{Fore.WHITE}, {Fore.LIGHTMAGENTA_EX}{spd}{Fore.WHITE}]{Style.RESET_ALL}\033[K"


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
