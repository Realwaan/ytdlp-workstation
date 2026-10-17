"""
Main application runner and interactive terminal loop for ytdlp-workstation.
"""

import sys
import os
import time
import shutil
import urllib.parse
import threading
import subprocess
from pathlib import Path

from ..core.state import STATE, DownloadJob
from ..core.config import DEFAULT_DOWNLOAD_DIR, CONFIG_FILE, YTDLP_EXE
from ..core.presets import PRESETS
from ..queue.manager import QueueManager
from ..extractors.url_detector import is_valid_media_url, extract_media_url, GENERIC_URL_REGEX, clean_url
from ..extractors.referer import auto_detect_referer, KNOWN_STREAMING_DOMAINS
from ..extractors.spotify import is_spotify_url
from ..utils.clipboard import get_clipboard_text
from ..utils.notifications import play_sound
from ..utils.system import cleanup_orphaned_fragments, bootstrap_workstation_environment
from .ui import Fore, Style, print_banner, format_linux_bar
from .input_reader import (
    HAS_MSVCRT,
    COMMAND_HISTORY,
    read_single_choice,
    prompt_video_quality,
    inspect_and_pick_formats,
    TerminalLineReader
)
from .commands import (
    cmd_play,
    cmd_search,
    cmd_inspect,
    cmd_queue_status,
    cmd_archive_management,
    cmd_codec,
    enqueue_spotify_download,
    handle_preset_shortcut
)

if HAS_MSVCRT:
    import msvcrt


def check_for_updates_background():
    """Background check for newer yt-dlp release."""
    def _check():
        try:
            cmd = [str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"), "--version"]
            cur_ver = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
            import json
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                latest_ver = data.get("tag_name", "").lstrip("v")
                if latest_ver and latest_ver != cur_ver:
                    STATE.update_available = latest_ver
        except Exception:
            pass

    threading.Thread(target=_check, daemon=True).start()


def clipboard_watcher_thread(queue_mgr: QueueManager):
    """Background thread that monitors system clipboard."""
    last_text = ""
    try:
        last_text = get_clipboard_text().strip()
    except Exception:
        pass

    while not STATE.stop_requested:
        time.sleep(0.4)
        clip_mode = STATE.config.get("clipboard_mode", "auto")
        if clip_mode == "off":
            continue

        try:
            current_text = get_clipboard_text()
        except Exception:
            continue

        if not current_text or not isinstance(current_text, str):
            continue

        current_text = current_text.strip()
        if current_text == last_text:
            continue

        last_text = current_text
        lower_txt = current_text.lower()

        # Check if copied text is a streaming website URL
        matched_site = None
        for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
            if s_domain in lower_txt:
                matched_site = s_url
                break
        if not matched_site and any(k in lower_txt for k in ("movie", "watch", "stream", "series", "anime")) and lower_txt.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(current_text)
            if parsed.netloc:
                matched_site = f"{parsed.scheme}://{parsed.netloc}/"

        if matched_site and not any(ext in lower_txt for ext in (".mp4", ".m3u8", ".webm", ".mkv", ".mpd", ".ts")):
            if STATE.last_seen_website != matched_site:
                STATE.last_seen_website = matched_site
                STATE.set_config("default_stream_referer", matched_site)
                play_sound("notice", enabled=STATE.config.get("sound_effects", True))
                print(f"\n{Fore.GREEN}[⚡] Auto-detected Active Streaming Site:{Style.RESET_ALL} {Fore.CYAN}{matched_site}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Stream links will auto-use this referer){Style.RESET_ALL}\n")
            continue

        # Check if copied text is Spotify
        if is_spotify_url(current_text):
            m_url = extract_media_url(current_text) or current_text
            clean = clean_url(m_url)
            with STATE.lock:
                if clean in STATE.seen_clipboard:
                    continue
                STATE.seen_clipboard.add(clean)
            play_sound("notice", enabled=STATE.config.get("sound_effects", True))
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Spotify link on Clipboard!{Style.RESET_ALL} {Fore.CYAN}{m_url}{Style.RESET_ALL}")
            if clip_mode == "auto":
                enqueue_spotify_download(m_url, queue_mgr)
            elif clip_mode == "prompt":
                with STATE.lock:
                    STATE.pending_prompt_url = m_url
                    STATE.pending_prompt_ref = None
            continue

        # Check media URL
        if not is_valid_media_url(current_text, media_filter_only=STATE.config.get("media_filter_only", True)):
            continue

        url = extract_media_url(current_text) or current_text
        clean = clean_url(url)

        with STATE.lock:
            if clean in STATE.seen_clipboard:
                continue
            STATE.seen_clipboard.add(clean)

        play_sound("notice", enabled=STATE.config.get("sound_effects", True))
        auto_ref = auto_detect_referer(url, last_seen_website=STATE.last_seen_website, default_referer=STATE.config.get("default_stream_referer", "https://movy.sx/"))
        if auto_ref:
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Cloud Stream! Attached Referer:{Style.RESET_ALL} {Fore.CYAN}{auto_ref}{Style.RESET_ALL}")

        if clip_mode == "auto":
            needs_prompt = STATE.config.get("ask_quality_each_time", True)
            job = DownloadJob(url=url, referer=auto_ref, needs_quality_prompt=needs_prompt)
            if needs_prompt:
                chosen_preset, custom_fmt = prompt_video_quality(url, referer=auto_ref)
                if chosen_preset is not None or custom_fmt is not None:
                    job.preset_override = chosen_preset
                    job.custom_format_str = custom_fmt
                    queue_mgr.enqueue(job)
            else:
                queue_mgr.enqueue(job)
        elif clip_mode == "prompt":
            with STATE.lock:
                STATE.pending_prompt_url = url
                STATE.pending_prompt_ref = auto_ref


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


def main():
    if os.name == "nt":
        os.system("title YT-DLP Supercharged Workstation v2.0")

    bootstrap_workstation_environment()

    # Initialize Concurrent Queue Manager
    workers = STATE.config.get("max_concurrent_downloads", 2)
    queue_mgr = QueueManager(max_workers=workers)

    def _render_progress(job: DownloadJob):
        bar_text = format_linux_bar(
            job.display_title or job.saved_filename or job.url,
            job.progress_pct,
            job.downloaded_str,
            job.total_str,
            job.speed_str,
            job.eta_str,
            job.fragment_str
        )
        sys.stdout.write(bar_text)
        sys.stdout.flush()

    queue_mgr.on_job_progress = _render_progress

    print_banner(active_workers=queue_mgr.max_workers)
    cleanup_orphaned_fragments()
    check_for_updates_background()

    # Start clipboard watcher thread
    watcher_t = threading.Thread(target=clipboard_watcher_thread, args=(queue_mgr,), daemon=True)
    watcher_t.start()

    prompt = f"{Fore.CYAN}>>> {Style.RESET_ALL}"
    fallback_reader = None
    if not (HAS_MSVCRT and sys.stdin.isatty()):
        fallback_reader = TerminalLineReader()

    try:
        while not STATE.stop_requested:
            if HAS_MSVCRT and sys.stdin.isatty():
                sys.stdout.write(prompt)
                sys.stdout.flush()
                line_buf = []
                hist_idx = len(COMMAND_HISTORY)
                saved_cur = ""

                while not STATE.stop_requested:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ("\r", "\n"):
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                            line_str = "".join(line_buf)
                            if line_str.strip():
                                if not COMMAND_HISTORY or COMMAND_HISTORY[-1] != line_str.strip():
                                    COMMAND_HISTORY.append(line_str.strip())
                            handle_user_command(line_str, queue_mgr)
                            break
                        elif ch == "\x08":  # Backspace
                            if line_buf:
                                line_buf.pop()
                                sys.stdout.write("\b \b")
                                sys.stdout.flush()
                        elif ch in ("\x00", "\xe0"):
                            if msvcrt.kbhit():
                                code = msvcrt.getwch()
                                if code == "H":  # Up Arrow
                                    if COMMAND_HISTORY:
                                        if hist_idx == len(COMMAND_HISTORY):
                                            saved_cur = "".join(line_buf)
                                        if hist_idx > 0:
                                            hist_idx -= 1
                                            sys.stdout.write("\r" + " " * (len(prompt) + len(line_buf) + 5) + "\r")
                                            line_buf = list(COMMAND_HISTORY[hist_idx])
                                            sys.stdout.write(prompt + "".join(line_buf))
                                            sys.stdout.flush()
                                elif code == "P":  # Down Arrow
                                    if hist_idx < len(COMMAND_HISTORY) - 1:
                                        hist_idx += 1
                                        sys.stdout.write("\r" + " " * (len(prompt) + len(line_buf) + 5) + "\r")
                                        line_buf = list(COMMAND_HISTORY[hist_idx])
                                        sys.stdout.write(prompt + "".join(line_buf))
                                        sys.stdout.flush()
                                    elif hist_idx == len(COMMAND_HISTORY) - 1:
                                        hist_idx += 1
                                        sys.stdout.write("\r" + " " * (len(prompt) + len(line_buf) + 5) + "\r")
                                        line_buf = list(saved_cur)
                                        sys.stdout.write(prompt + "".join(line_buf))
                                        sys.stdout.flush()
                        elif ord(ch) >= 32:
                            line_buf.append(ch)
                            sys.stdout.write(ch)
                            sys.stdout.flush()
                    else:
                        time.sleep(0.04)
            else:
                sys.stdout.write(prompt)
                sys.stdout.flush()
                while not STATE.stop_requested:
                    if fallback_reader and fallback_reader.input_queue:
                        line = fallback_reader.input_queue.popleft()
                        handle_user_command(line, queue_mgr)
                        break
                    time.sleep(0.04)

    except (KeyboardInterrupt, EOFError):
        print(f"\n{Fore.YELLOW}Exiting YT-DLP Workstation. Goodbye!{Style.RESET_ALL}")
    finally:
        STATE.stop_requested = True
        queue_mgr.stop_requested = True


if __name__ == "__main__":
    main()
