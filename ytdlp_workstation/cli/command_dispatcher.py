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
from typing import Optional

from ..core.state import STATE, DownloadJob, AppState, resolve_state
from ..core.config import DEFAULT_DOWNLOAD_DIR, YTDLP_EXE
from ..core.presets import PRESETS
from ..queue.manager import QueueManager
from ..extractors.url_detector import is_valid_media_url, extract_media_url, GENERIC_URL_REGEX, clean_url
from ..extractors.referer import auto_detect_referer, KNOWN_STREAMING_DOMAINS
from ..extractors.spotify import is_spotify_url
from ..utils.system import sanitize_filename
from .console import CONSOLE
from .ui import Fore, Style, print_banner
from .input_reader import prompt_video_quality, inspect_and_pick_formats, ask_text
from .commands import (
    cmd_play,
    cmd_search,
    cmd_inspect,
    cmd_queue_status,
    cmd_archive_management,
    cmd_codec,
    enqueue_spotify_download,
    enqueue_media_url,
    handle_preset_shortcut,
)


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return resolve_state(state)


def select_preset_menu(state: Optional[AppState] = None):
    """Interactive preset selection menu."""
    state = _resolve_state(state)
    print(f"\n{Fore.CYAN}═══ SELECT DEFAULT QUALITY PRESET ═══{Style.RESET_ALL}")
    for pid, p in PRESETS.items():
        is_cur = " [ACTIVE]" if pid == state.config.get("preset", 1) else ""
        color = Fore.LIGHTGREEN_EX if is_cur else Fore.WHITE
        print(f"  {color}[{pid}] {p['name']}{is_cur}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTBLACK_EX}{p['desc']}{Style.RESET_ALL}")

    print(f"\n  {Fore.YELLOW}[0] Toggle 'Ask Quality on Each Download'{Style.RESET_ALL} (Currently: {'ON' if state.config.get('ask_quality_each_time', True) else 'OFF'})")
    choice = ask_text(f"\n{Fore.CYAN}Enter option (1-12, or 0 to toggle): {Style.RESET_ALL}", state).lower()
    if choice == "0":
        state.set_config("ask_quality_each_time", not state.config.get("ask_quality_each_time", True))
        print(f"{Fore.GREEN}[✓] 'Ask Quality on Each Download' updated.{Style.RESET_ALL}\n")
    elif choice in [str(i) for i in PRESETS.keys()]:
        state.set_config("preset", int(choice))
        print(f"{Fore.GREEN}[✓] Default preset set to #{choice}: {PRESETS[int(choice)]['name']}{Style.RESET_ALL}\n")


def toggle_settings_menu(state: Optional[AppState] = None):
    """Full settings configuration menu."""
    state = _resolve_state(state)
    print(f"\n{Fore.CYAN}═══ WORKSTATION SETTINGS ═══{Style.RESET_ALL}")
    print(f"  [1] Ask Quality on Each Download              : {'ON' if state.config.get('ask_quality_each_time', True) else 'OFF'}")
    print(f"  [2] Browser Cookies                           : {state.config.get('browser_cookies', 'none').upper()}")
    print(f"  [3] Subtitles Mode                            : {state.config.get('subtitles_mode', 'off').upper()}")
    print(f"  [4] Speed Limit                               : {state.config.get('speed_limit', 'none').upper()}")
    print(f"  [5] Desktop Notifications                     : {'ON' if state.config.get('desktop_notifications', True) else 'OFF'}")
    print(f"  [6] Sound Effects (Chimes)                    : {'ON' if state.config.get('sound_effects', True) else 'OFF'}")
    print(f"  [7] SponsorBlock                              : {'ON' if state.config.get('sponsorblock', False) else 'OFF'}")
    print(f"  [8] Download Archive (Duplicate Blocker)      : {'ON' if state.config.get('use_download_archive', True) else 'OFF'}")
    print(f"  [9] Max Parallel Concurrent Workers           : {state.config.get('max_concurrent_downloads', 2)}")
    print(f"  [a] Codec Preference                          : {state.config.get('codec_preference', 'auto').upper()}")
    print(f"  [b] Back\n")

    choice = ask_text(f"{Fore.CYAN}Enter setting number to toggle/change: {Style.RESET_ALL}", state).lower()
    if choice == "1":
        state.set_config("ask_quality_each_time", not state.config.get("ask_quality_each_time", True))
    elif choice == "2":
        b = ask_text("Enter browser name (chrome, edge, firefox, brave, or off): ", state).lower()
        state.set_config("browser_cookies", "none" if b in ("off", "none", "") else b)
    elif choice == "3":
        modes = ["off", "en", "all"]
        cur = state.config.get("subtitles_mode", "off")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "en"
        state.set_config("subtitles_mode", nxt)
    elif choice == "4":
        lim = ask_text("Enter limit (e.g. 5M, 10M, or off): ", state).lower()
        state.set_config("speed_limit", "none" if lim in ("off", "none", "0", "") else lim)
    elif choice == "5":
        state.set_config("desktop_notifications", not state.config.get("desktop_notifications", True))
    elif choice == "6":
        state.set_config("sound_effects", not state.config.get("sound_effects", True))
    elif choice == "7":
        state.set_config("sponsorblock", not state.config.get("sponsorblock", False))
    elif choice == "8":
        state.set_config("use_download_archive", not state.config.get("use_download_archive", True))
    elif choice == "9":
        w = ask_text("Enter worker count (1-5): ", state)
        if w.isdigit() and 1 <= int(w) <= 5:
            state.set_config("max_concurrent_downloads", int(w))
    elif choice == "a":
        cmd_codec("codec", state=state)
    print(f"{Fore.GREEN}[✓] Settings saved.{Style.RESET_ALL}\n")


def handle_user_command(user_input: str, queue_mgr: QueueManager, state: Optional[AppState] = None):
    """Process an entered line from the terminal prompt."""
    state = _resolve_state(state)
    raw = user_input.strip()
    if not raw:
        return

    cmd_lower = raw.lower()

    if cmd_lower in ("q", "exit", "quit"):
        print(f"{Fore.YELLOW}Exiting YT-DLP Workstation. Goodbye!{Style.RESET_ALL}")
        state.stop_requested = True
        return

    if cmd_lower in ("cls", "clear", "?", "help"):
        print_banner(active_workers=queue_mgr.max_workers, state=state)
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
        cmd_play(raw, queue_mgr, state=state)
    elif first_word in ("yt", "search", "find"):
        cmd_search(raw, queue_mgr, state=state)
    elif first_word in ("info", "inspect", "details"):
        cmd_inspect(raw, queue_mgr, state=state)
    elif first_word == "spotify":
        if arg_part:
            enqueue_spotify_download(arg_part.strip("\"'"), queue_mgr, state=state)
        else:
            s_url = ask_text("Spotify URL >>> ", state).strip("\"'")
            if s_url:
                enqueue_spotify_download(s_url, queue_mgr, state=state)
    elif first_word in ("archive", "arch"):
        cmd_archive_management(raw, state=state)
    elif first_word == "codec":
        cmd_codec(raw, state=state)
    elif first_word in ("site", "website"):
        if arg_part:
            key = arg_part.strip().lower()
            if key in KNOWN_STREAMING_DOMAINS:
                new_site = KNOWN_STREAMING_DOMAINS[key]
            else:
                new_site = arg_part if arg_part.startswith(("http://", "https://")) else f"https://{arg_part}/"
                if not new_site.endswith("/"):
                    new_site += "/"
            state.last_seen_website = new_site
            state.set_config("default_stream_referer", new_site)
            print(f"{Fore.GREEN}[✓] Active streaming site set to: {new_site}{Style.RESET_ALL}\n")
        else:
            print(f"Current Auto-Referer: {state.last_seen_website}")
    elif first_word in ("ref", "referer"):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            r_url, s_url = tokens[1], tokens[2]
            queue_mgr.enqueue(DownloadJob(url=s_url, referer=r_url))
            print(f"{Fore.GREEN}[+] Queued with Referer [{r_url}]: {s_url}{Style.RESET_ALL}\n")
        elif len(tokens) == 2:
            s_url = tokens[1]
            queue_mgr.enqueue(DownloadJob(url=s_url, referer=state.last_seen_website))
            print(f"{Fore.GREEN}[+] Queued with Referer [{state.last_seen_website}]: {s_url}{Style.RESET_ALL}\n")
        else:
            ref_in = ask_text("Referer URL >>> ", state)
            str_in = ask_text("Stream URL (.m3u8) >>> ", state)
            if str_in:
                queue_mgr.enqueue(DownloadJob(url=str_in, referer=ref_in or state.last_seen_website))
                print(f"{Fore.GREEN}[+] Queued!{Style.RESET_ALL}\n")
    elif first_word in ("trim", "clip") and any(ch.isdigit() for ch in arg_part):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            u = extract_media_url(tokens[2]) or tokens[2]
            auto_ref = auto_detect_referer(u, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
            queue_mgr.enqueue(DownloadJob(url=u, referer=auto_ref, download_section=tokens[1]))
            print(f"{Fore.GREEN}[+] Queued clip [{tokens[1]}]: {tokens[2]}{Style.RESET_ALL}\n")
    elif first_word in ("items", "range"):
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            u = extract_media_url(tokens[2]) or tokens[2]
            auto_ref = auto_detect_referer(u, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
            queue_mgr.enqueue(DownloadJob(url=u, referer=auto_ref, playlist_items=tokens[1]))
            print(f"{Fore.GREEN}[+] Queued playlist items [{tokens[1]}]: {tokens[2]}{Style.RESET_ALL}\n")
    elif first_word == "subs":
        tokens = raw.split(maxsplit=2)
        if len(tokens) >= 3:
            lang, u = tokens[1], extract_media_url(tokens[2]) or tokens[2]
            auto_ref = auto_detect_referer(u, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
            queue_mgr.enqueue(DownloadJob(url=u, referer=auto_ref, force_subs=True, sub_lang=lang))
            print(f"{Fore.GREEN}[+] Queued with subtitles [{lang}]: {u}{Style.RESET_ALL}\n")
        elif len(tokens) == 2 and is_valid_media_url(tokens[1]):
            u = extract_media_url(tokens[1]) or tokens[1]
            auto_ref = auto_detect_referer(u, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
            queue_mgr.enqueue(DownloadJob(url=u, referer=auto_ref, force_subs=True, sub_lang="en"))
            print(f"{Fore.GREEN}[+] Queued with English subtitles: {u}{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}[!] Usage: subs [lang] <URL>{Style.RESET_ALL}\n")
    elif first_word == "f":
        u_in = arg_part.strip().strip("\"'") if arg_part else ask_text("Media URL >>> ", state).strip("\"'")
        if u_in:
            u = extract_media_url(u_in) or u_in
            auto_ref = auto_detect_referer(u, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
            custom_fmt = inspect_and_pick_formats(u, referer=auto_ref, state=state)
            if custom_fmt:
                queue_mgr.enqueue(DownloadJob(url=u, referer=auto_ref, custom_format_str=custom_fmt))
                print(f"{Fore.GREEN}[+] Queued format [{custom_fmt}]: {u}{Style.RESET_ALL}\n")
    elif first_word == "cookies":
        b = arg_part.strip().lower() if arg_part else ask_text("Enter browser (chrome, edge, firefox, brave, or off): ", state).lower()
        val = "none" if b in ("off", "none", "") else b
        state.set_config("browser_cookies", val)
        print(f"{Fore.GREEN}[✓] Browser cookies set to: {val.upper()}{Style.RESET_ALL}\n")
    elif first_word == "limit":
        lim = arg_part.strip().lower() if arg_part else ask_text("Enter speed limit (e.g. 5M, 10M, or off): ", state).lower()
        val = "none" if lim in ("off", "none", "0", "") else lim
        state.set_config("speed_limit", val)
        print(f"{Fore.GREEN}[✓] Speed limit set to: {val.upper()}{Style.RESET_ALL}\n")
    elif first_word == "qmode":
        cur = state.config.get("ask_quality_each_time", True)
        state.set_config("ask_quality_each_time", not cur)
        print(f"{Fore.GREEN}[✓] Ask Quality on Each Download is now: {'ON' if not cur else 'OFF'}{Style.RESET_ALL}\n")
    elif first_word in ("c", "clip"):
        modes = ["auto", "prompt", "off"]
        cur = state.config.get("clipboard_mode", "auto")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "auto"
        state.set_config("clipboard_mode", nxt)
        print(f"{Fore.GREEN}[✓] Clipboard mode set to: {nxt.upper()}{Style.RESET_ALL}\n")
    elif handle_preset_shortcut(first_word, arg_part, queue_mgr, state=state):
        pass
    elif first_word == "sb":
        if arg_part.strip().lower() in ("on", "true", "1"):
            new_val = True
        elif arg_part.strip().lower() in ("off", "false", "0"):
            new_val = False
        else:
            new_val = not state.config.get("sponsorblock", False)
        state.set_config("sponsorblock", new_val)
        print(f"{Fore.GREEN}[✓] SponsorBlock is now: {'ON' if new_val else 'OFF'}{Style.RESET_ALL}\n")
    elif first_word in ("p", "preset"):
        select_preset_menu(state=state)
    elif first_word in ("s", "settings"):
        toggle_settings_menu(state=state)
    elif first_word in ("h", "history"):
        if arg_part == "clear":
            state.history_manager.clear_history()
            print(f"{Fore.GREEN}[✓] History cleared.{Style.RESET_ALL}\n")
        else:
            entries = state.history_manager.get_entries(limit=15)
            print(f"\n{Fore.CYAN}═══ RECENT DOWNLOAD HISTORY ═══{Style.RESET_ALL}")
            for it in entries:
                print(f"  [{it.get('timestamp')}] {it.get('status')} - {it.get('title') or it.get('url')} ({it.get('duration', '')})")
            print("")
    elif first_word in ("o", "open"):
        folder = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))
    elif first_word in ("d", "dir"):
        new_d = ask_text(f"New folder path (current: {state.config.get('download_dir')}): ", state)
        if new_d:
            Path(new_d).mkdir(parents=True, exist_ok=True)
            state.set_config("download_dir", str(Path(new_d).resolve()))
            print(f"{Fore.GREEN}[✓] Download folder updated.{Style.RESET_ALL}\n")
    elif first_word in ("u", "update"):
        ytdlp_cmd = str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp")
        with CONSOLE.suspend():
            subprocess.run([ytdlp_cmd, "-U"])
    elif is_spotify_url(raw):
        enqueue_spotify_download(raw.strip("\"'"), queue_mgr, state=state)
    elif is_valid_media_url(raw) or GENERIC_URL_REGEX.search(raw):
        m_url = extract_media_url(raw) or raw
        auto_ref = auto_detect_referer(m_url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
        if auto_ref:
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Cloud Stream! Attached Referer:{Style.RESET_ALL} {Fore.CYAN}{auto_ref}{Style.RESET_ALL}")
        job = DownloadJob(url=m_url, referer=auto_ref)
        if state.config.get("ask_quality_each_time", True):
            chosen_preset, custom_fmt = prompt_video_quality(m_url, referer=auto_ref, state=state)
            if chosen_preset is not None or custom_fmt is not None:
                job.preset_override = chosen_preset
                job.custom_format_str = custom_fmt
                queue_mgr.enqueue(job)
                ref_note = f" {Fore.LIGHTBLACK_EX}(referer: {auto_ref}){Style.RESET_ALL}" if auto_ref else ""
                print(f"{Fore.GREEN}[+] Queued{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {m_url}{ref_note}\n")
        else:
            queue_mgr.enqueue(job)
            ref_note = f" {Fore.LIGHTBLACK_EX}(referer: {auto_ref}){Style.RESET_ALL}" if auto_ref else ""
            print(f"{Fore.GREEN}[+] Queued{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {m_url}{ref_note}\n")
    else:
        print(f"{Fore.RED}[!] Unrecognized command or invalid URL. Type 'help' for command list.{Style.RESET_ALL}\n")
