"""
CLI command dispatcher.

Handles parsing and execution of user-entered commands at the terminal prompt.
Extracted from cli/main.py to reduce the god-module surface and make each
command group independently testable.
"""

__all__ = [
    "handle_user_command",
    "select_preset_menu",
    "toggle_settings_menu",
]

import os
import subprocess
import urllib.parse
from pathlib import Path

from ..core.state import STATE, DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, YTDLP_EXE
from ..core.presets import PRESETS
from ..queue.manager import QueueManager
from ..extractors.url_detector import is_valid_media_url, extract_media_url, GENERIC_URL_REGEX, clean_url
from ..extractors.referer import auto_detect_referer, KNOWN_STREAMING_DOMAINS
from ..extractors.spotify import is_spotify_url
from ..utils.system import sanitize_filename
from .ui import Fore, Style, print_banner
from .input_reader import prompt_video_quality
from .commands import (
    cmd_play,
    cmd_search,
    cmd_inspect,
    cmd_queue_status,
    cmd_archive_management,
    cmd_codec,
    enqueue_spotify_download,
    handle_preset_shortcut,
)


def select_preset_menu():
    """Interactive preset selection menu."""
    print(f"\n{Fore.CYAN}═══ SELECT DEFAULT QUALITY PRESET ═══{Style.RESET_ALL}")
    for pid, p in PRESETS.items():
        is_cur = " [ACTIVE]" if pid == STATE.config.get("preset", 1) else ""
        color = Fore.LIGHTGREEN_EX if is_cur else Fore.WHITE
        print(f"  {color}[{pid}] {p['name']}{is_cur}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTBLACK_EX}{p['desc']}{Style.RESET_ALL}")

    print(f"\n  {Fore.YELLOW}[0] Toggle 'Ask Quality on Each Download'{Style.RESET_ALL} (Currently: {'ON' if STATE.config.get('ask_quality_each_time', True) else 'OFF'})")
    choice = input(f"\n{Fore.CYAN}Enter option (1-12, or 0 to toggle): {Style.RESET_ALL}").strip().lower()
    if choice == "0":
        STATE.set_config("ask_quality_each_time", not STATE.config.get("ask_quality_each_time", True))
        print(f"{Fore.GREEN}[✓] 'Ask Quality on Each Download' updated.{Style.RESET_ALL}\n")
    elif choice in [str(i) for i in PRESETS.keys()]:
        STATE.set_config("preset", int(choice))
        print(f"{Fore.GREEN}[✓] Default preset set to #{choice}: {PRESETS[int(choice)]['name']}{Style.RESET_ALL}\n")


def toggle_settings_menu():
    """Full settings configuration menu."""
    print(f"\n{Fore.CYAN}═══ WORKSTATION SETTINGS ═══{Style.RESET_ALL}")
    print(f"  [1] Ask Quality on Each Download              : {'ON' if STATE.config.get('ask_quality_each_time', True) else 'OFF'}")
    print(f"  [2] Browser Cookies                           : {STATE.config.get('browser_cookies', 'none').upper()}")
    print(f"  [3] Subtitles Mode                            : {STATE.config.get('subtitles_mode', 'off').upper()}")
    print(f"  [4] Speed Limit                               : {STATE.config.get('speed_limit', 'none').upper()}")
    print(f"  [5] Desktop Notifications                     : {'ON' if STATE.config.get('desktop_notifications', True) else 'OFF'}")
    print(f"  [6] Sound Effects (Chimes)                    : {'ON' if STATE.config.get('sound_effects', True) else 'OFF'}")
    print(f"  [7] SponsorBlock                              : {'ON' if STATE.config.get('sponsorblock', False) else 'OFF'}")
    print(f"  [8] Download Archive (Duplicate Blocker)      : {'ON' if STATE.config.get('use_download_archive', True) else 'OFF'}")
    print(f"  [9] Max Parallel Concurrent Workers           : {STATE.config.get('max_concurrent_downloads', 2)}")
    print(f"  [a] Codec Preference                          : {STATE.config.get('codec_preference', 'auto').upper()}")
    print(f"  [b] Back\n")

    choice = input(f"{Fore.CYAN}Enter setting number to toggle/change: {Style.RESET_ALL}").strip().lower()
    if choice == "1":
        STATE.set_config("ask_quality_each_time", not STATE.config.get("ask_quality_each_time", True))
    elif choice == "2":
        b = input("Enter browser name (chrome, edge, firefox, brave, or off): ").strip().lower()
        STATE.set_config("browser_cookies", "none" if b in ("off", "none", "") else b)
    elif choice == "3":
        modes = ["off", "en", "all"]
        cur = STATE.config.get("subtitles_mode", "off")
        nxt = modes[(modes.index(cur) + 1) % len(modes)]
        STATE.set_config("subtitles_mode", nxt)
    elif choice == "4":
        lim = input("Enter limit (e.g. 5M, 10M, or off): ").strip().lower()
        STATE.set_config("speed_limit", "none" if lim in ("off", "none", "0", "") else lim)
    elif choice == "5":
        STATE.set_config("desktop_notifications", not STATE.config.get("desktop_notifications", True))
    elif choice == "6":
        STATE.set_config("sound_effects", not STATE.config.get("sound_effects", True))
    elif choice == "7":
        STATE.set_config("sponsorblock", not STATE.config.get("sponsorblock", False))
    elif choice == "8":
        STATE.set_config("use_download_archive", not STATE.config.get("use_download_archive", True))
    elif choice == "9":
        w = input("Enter worker count (1-5): ").strip()
        if w.isdigit() and 1 <= int(w) <= 5:
            STATE.set_config("max_concurrent_downloads", int(w))
    elif choice == "a":
        cmd_codec("codec")
    print(f"{Fore.GREEN}[✓] Settings saved.{Style.RESET_ALL}\n")


def handle_user_command(user_input: str, queue_mgr: QueueManager):
    """Process an entered line from the terminal prompt."""
    raw = user_input.strip()
    if not raw:
        return

    cmd_lower = raw.lower()

    if cmd_lower in ("q", "exit", "quit"):
        print(f"{Fore.YELLOW}Exiting YT-DLP Workstation. Goodbye!{Style.RESET_ALL}")
        STATE.stop_requested = True
        return

    if cmd_lower in ("cls", "clear", "?", "help"):
        print_banner(active_workers=queue_mgr.max_workers)
        return

    if cmd_lower in ("queue", "qstatus"):
        cmd_queue_status(queue_mgr)
        return

    if cmd_lower == "pause":
        queue_mgr.pause_queue()
        print(f"\n{Fore.YELLOW}[✓] Download queue paused.{Style.RESET_ALL}\n")
        return

    if cmd_lower == "resume":
        queue_mgr.resume_queue()
        print(f"\n{Fore.GREEN}[✓] Download queue resumed.{Style.RESET_ALL}\n")
        return

    if cmd_lower == "clearqueue":
        cnt = queue_mgr.clear_pending()
        print(f"\n{Fore.GREEN}[✓] Cleared {cnt} pending jobs from queue.{Style.RESET_ALL}\n")
        return

    first_word = raw.split()[0].lower() if " " in raw else raw.lower()
    arg_part = raw.split(maxsplit=1)[1] if " " in raw else ""

    if first_word == "cancel" and arg_part:
        if queue_mgr.cancel_job(arg_part.strip()):
            print(f"\n{Fore.GREEN}[✓] Cancelled job {arg_part.strip()}{Style.RESET_ALL}\n")
        else:
            print(f"\n{Fore.RED}[!] Could not find pending job ID: {arg_part.strip()}{Style.RESET_ALL}\n")
        return

    if first_word in ("workers", "threads") and arg_part:
        if arg_part.isdigit():
            queue_mgr.set_max_workers(int(arg_part))
            print(f"\n{Fore.GREEN}[✓] Parallel worker concurrency set to: {arg_part}{Style.RESET_ALL}\n")
        return

    if first_word in ("play", "song", "music"):
        cmd_play(raw, queue_mgr)
    elif first_word in ("yt", "search", "find"):
        cmd_search(raw, queue_mgr)
    elif first_word in ("info", "inspect", "details"):
        cmd_inspect(raw, queue_mgr)
    elif first_word == "spotify":
        if arg_part:
            enqueue_spotify_download(arg_part.strip("\"'"), queue_mgr)
        else:
            s_url = input("Spotify URL >>> ").strip().strip("\"'")
            if s_url:
                enqueue_spotify_download(s_url, queue_mgr)
    elif first_word in ("archive", "arch"):
        cmd_archive_management(raw)
    elif first_word == "codec":
        cmd_codec(raw)
    elif first_word in ("site", "website"):
        if arg_part:
            new_site = arg_part if arg_part.startswith(("http://", "https://")) else f"https://{arg_part}/"
            if not new_site.endswith("/"):
                new_site += "/"
            STATE.last_seen_website = new_site
            STATE.set_config("default_stream_referer", new_site)
            print(f"{Fore.GREEN}[✓] Active streaming site set to: {new_site}{Style.RESET_ALL}\n")
        else:
            print(f"Current Auto-Referer: {STATE.last_seen_website}")
    elif first_word in ("ref", "referer"):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            r_url, s_url = tokens[1], tokens[2]
            queue_mgr.enqueue(DownloadJob(url=s_url, referer=r_url))
            print(f"{Fore.GREEN}[+] Queued with Referer [{r_url}]: {s_url}{Style.RESET_ALL}\n")
        elif len(tokens) == 2:
            s_url = tokens[1]
            queue_mgr.enqueue(DownloadJob(url=s_url, referer=STATE.last_seen_website))
            print(f"{Fore.GREEN}[+] Queued with Referer [{STATE.last_seen_website}]: {s_url}{Style.RESET_ALL}\n")
        else:
            ref_in = input("Referer URL >>> ").strip()
            str_in = input("Stream URL (.m3u8) >>> ").strip()
            if str_in:
                queue_mgr.enqueue(DownloadJob(url=str_in, referer=ref_in or STATE.last_seen_website))
                print(f"{Fore.GREEN}[+] Queued!{Style.RESET_ALL}\n")
    elif first_word in ("trim", "clip") and any(ch.isdigit() for ch in arg_part):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            queue_mgr.enqueue(DownloadJob(url=extract_media_url(tokens[2]) or tokens[2], download_section=tokens[1]))
            print(f"{Fore.GREEN}[+] Queued clip [{tokens[1]}]: {tokens[2]}{Style.RESET_ALL}\n")
    elif first_word in ("items", "range"):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            queue_mgr.enqueue(DownloadJob(url=extract_media_url(tokens[2]) or tokens[2], playlist_items=tokens[1]))
            print(f"{Fore.GREEN}[+] Queued playlist items [{tokens[1]}]: {tokens[2]}{Style.RESET_ALL}\n")
    elif handle_preset_shortcut(first_word, arg_part, queue_mgr):
        pass
    elif first_word == "sb":
        cur = STATE.config.get("sponsorblock", False)
        STATE.set_config("sponsorblock", not cur)
        print(f"{Fore.GREEN}[✓] SponsorBlock is now: {'ON' if not cur else 'OFF'}{Style.RESET_ALL}\n")
    elif first_word in ("p", "preset"):
        select_preset_menu()
    elif first_word in ("s", "settings"):
        toggle_settings_menu()
    elif first_word in ("h", "history"):
        if arg_part == "clear":
            STATE.history_manager.clear_history()
            print(f"{Fore.GREEN}[✓] History cleared.{Style.RESET_ALL}\n")
        else:
            entries = STATE.history_manager.get_entries(limit=15)
            print(f"\n{Fore.CYAN}═══ RECENT DOWNLOAD HISTORY ═══{Style.RESET_ALL}")
            for it in entries:
                print(f"  [{it.get('timestamp')}] {it.get('status')} - {it.get('title') or it.get('url')} ({it.get('duration', '')})")
            print("")
    elif first_word in ("o", "open"):
        folder = Path(STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))
    elif first_word in ("d", "dir"):
        new_d = input(f"New folder path (current: {STATE.config.get('download_dir')}): ").strip()
        if new_d:
            Path(new_d).mkdir(parents=True, exist_ok=True)
            STATE.set_config("download_dir", str(Path(new_d).resolve()))
            print(f"{Fore.GREEN}[✓] Download folder updated.{Style.RESET_ALL}\n")
    elif first_word in ("u", "update"):
        ytdlp_cmd = str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp")
        subprocess.run([ytdlp_cmd, "-U"])
    elif is_spotify_url(raw):
        enqueue_spotify_download(raw.strip("\"'"), queue_mgr)
    elif is_valid_media_url(raw) or GENERIC_URL_REGEX.search(raw):
        m_url = extract_media_url(raw) or raw
        job = DownloadJob(url=m_url)
        if STATE.config.get("ask_quality_each_time", True):
            chosen_preset, custom_fmt = prompt_video_quality(m_url)
            if chosen_preset is not None or custom_fmt is not None:
                job.preset_override = chosen_preset
                job.custom_format_str = custom_fmt
                queue_mgr.enqueue(job)
        else:
            queue_mgr.enqueue(job)
    else:
        print(f"{Fore.RED}[!] Unrecognized command or invalid URL. Type 'help' for command list.{Style.RESET_ALL}\n")
