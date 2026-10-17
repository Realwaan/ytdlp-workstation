"""
Terminal input reader: Single-key interactive picker (msvcrt), Up/Down command history,
and non-blocking background queue pollers.
"""

import sys
import time
import subprocess
import collections
from pathlib import Path
from typing import Tuple, Optional, Set

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

from ..core.state import STATE
from ..core.config import YTDLP_EXE, FFMPEG_EXE
from ..core.presets import PRESETS
from .ui import Fore, Style

COMMAND_HISTORY = []


def read_single_choice(valid_chars: Set[str], default_val: str) -> str:
    """Reads a single keystroke without requiring Enter, or Enter for default."""
    if HAS_MSVCRT and sys.stdin.isatty():
        while not STATE.stop_requested:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return default_val
                elif ch in ("\x03", "\x1b"):  # Ctrl+C or Esc
                    sys.stdout.write("Skip\n")
                    sys.stdout.flush()
                    return "s"
                elif ch.lower() in valid_chars:
                    sys.stdout.write(ch + "\n")
                    sys.stdout.flush()
                    return ch.lower()
            time.sleep(0.02)
        return default_val
    else:
        line = sys.stdin.readline().strip().lower()
        return line if line else default_val


def inspect_and_pick_formats(url: str, referer: Optional[str] = None) -> Optional[str]:
    """Run yt-dlp -F to show all formats and let the user pick exact format codes."""
    print(f"\n{Fore.CYAN}[*] Fetching available formats from video...{Style.RESET_ALL}\n")
    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--no-warnings"
    ]
    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])
    if STATE.config.get("browser_cookies", "none") != "none":
        cmd.extend(["--cookies-from-browser", STATE.config["browser_cookies"]])
    if referer:
        cmd.extend(["--referer", referer])
    cmd.extend(["-F", url])

    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"{Fore.RED}[!] Error fetching formats: {e}{Style.RESET_ALL}")
        return None

    print(f"\n{Fore.YELLOW}Examples: '137+140' (1080p video + audio), '22' (720p with audio), 'best'{Style.RESET_ALL}")
    chosen = input(f"{Fore.CYAN}Enter format ID (or press Enter for best): {Style.RESET_ALL}").strip()
    return chosen if chosen else "bv*+ba/b"


def prompt_video_quality(url: str, referer: Optional[str] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Interactive Video Quality Picker:
    Single-keystroke selection: Press 1-9, a, b, 0, f, s, or Enter for default!
    """
    default_pid = STATE.config.get("preset", 1)
    default_name = PRESETS.get(default_pid, PRESETS[1])["name"]

    print(f"\n{Fore.CYAN}╔═══════════════════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║ {Style.BRIGHT}{Fore.YELLOW}🎥 PICK VIDEO QUALITY FOR THIS DOWNLOAD{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║ {Fore.WHITE}URL: {Fore.LIGHTCYAN_EX}{url[:65]}{'...' if len(url) > 65 else ''}{Style.RESET_ALL}")
    if referer:
        print(f"{Fore.CYAN}║ {Fore.WHITE}Referer: {Fore.YELLOW}{referer}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╠═══════════════════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[1] 4K / 2160p (Best Available){Style.RESET_ALL}     {Fore.LIGHTBLACK_EX}- Maximum possible resolution{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[2] 1440p (2K Quad HD){Style.RESET_ALL}              {Fore.LIGHTBLACK_EX}- Ultra high quality{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[3] 1080p (Full HD){Style.RESET_ALL}                 {Fore.LIGHTBLACK_EX}- Recommended quality & size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[4] 720p  (HD){Style.RESET_ALL}                     {Fore.LIGHTBLACK_EX}- Fast download, smaller size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[5] 480p  (SD Standard){Style.RESET_ALL}            {Fore.LIGHTBLACK_EX}- Low bandwidth{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[6] 360p  (Data Saver){Style.RESET_ALL}             {Fore.LIGHTBLACK_EX}- Smallest video file size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[7] Audio MP3 (320kbps){Style.RESET_ALL}            {Fore.LIGHTBLACK_EX}- MP3 with album artwork & tags{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[8] Audio M4A (Original AAC){Style.RESET_ALL}       {Fore.LIGHTBLACK_EX}- Direct audio extraction{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[9] Audio FLAC (Lossless Studio){Style.RESET_ALL}   {Fore.LIGHTBLACK_EX}- High-res lossless audiophile audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[a] Audio OPUS (Next-Gen){Style.RESET_ALL}          {Fore.LIGHTBLACK_EX}- Ultra efficient modern audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[b] Audio WAV (Raw PCM){Style.RESET_ALL}           {Fore.LIGHTBLACK_EX}- Uncompressed raw audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.CYAN}[0] Universal MKV (All Subs){Style.RESET_ALL}        {Fore.LIGHTBLACK_EX}- Preserves all subtitles & tracks{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.MAGENTA}[f] Inspect All Formats (-F){Style.RESET_ALL}       {Fore.LIGHTBLACK_EX}- Pick exact format ID table{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.RED}[s] Skip / Cancel{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╚═══════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"{Fore.LIGHTWHITE_EX}Press single key [1-9, a, b, 0, f, s, or {Fore.GREEN}Enter for Default (#{default_pid} - {default_name}){Fore.LIGHTWHITE_EX}]: {Style.RESET_ALL}", end="", flush=True)

    valid_keys = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "0", "f", "s"}
    choice = read_single_choice(valid_keys, default_val=str(default_pid))

    choice_map = {
        "1": 1, "4k": 1, "2160p": 1,
        "2": 2, "2k": 2, "1440p": 2,
        "3": 3, "1080p": 3, "1080": 3,
        "4": 4, "720p": 4, "720": 4,
        "5": 5, "480p": 5, "480": 5,
        "6": 6, "360p": 6, "360": 6,
        "7": 7, "mp3": 7,
        "8": 8, "m4a": 8, "aac": 8,
        "9": 9, "flac": 9,
        "a": 10, "opus": 10,
        "b": 11, "wav": 11,
        "0": 12, "mkv": 12,
    }

    if choice in ("f", "formats", "format"):
        custom_fmt = inspect_and_pick_formats(url, referer=referer)
        return None, custom_fmt
    elif choice in ("s", "skip", "cancel", "n"):
        print(f"{Fore.LIGHTBLACK_EX}[!] Download skipped.{Style.RESET_ALL}\n")
        return None, None
    elif choice in choice_map:
        return choice_map[choice], None
    return default_pid, None


class TerminalLineReader:
    """Background stdin reader for non-TTY terminals (VS Code, Cursor, Git Bash)."""
    def __init__(self):
        import threading
        self.input_queue = collections.deque()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not STATE.stop_requested:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                self.input_queue.append(line.rstrip("\r\n"))
            except Exception:
                break
