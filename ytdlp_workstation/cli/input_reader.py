"""
Terminal input layer.

All keyboard input goes through this module and must only be called from the
main REPL thread:

* :func:`read_line`          – line editor (history, Esc, Ctrl+C) on Windows
                               TTYs, or a background line reader elsewhere.
* :func:`read_single_choice` – single-keystroke picker.
* :func:`prompt_video_quality` / :func:`inspect_and_pick_formats` – pickers.

Prompts are registered with :data:`CONSOLE` so background output (progress
bars, clipboard notices) is printed *above* the prompt instead of on top of it.
"""

__all__ = [
    "HAS_MSVCRT",
    "COMMAND_HISTORY",
    "TerminalLineReader",
    "is_interactive",
    "read_line",
    "read_single_choice",
    "ask_text",
    "prompt_video_quality",
    "inspect_and_pick_formats",
]

import sys
import time
import queue
import threading
import subprocess
from typing import Tuple, Optional, Set, List, Any

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

from ..core.state import AppState, DownloadJob, resolve_state
from ..core.config import YTDLP_EXE, FFMPEG_EXE
from ..core.presets import PRESETS
from . import inbox
from .console import CONSOLE
from .ui import Fore, Style

COMMAND_HISTORY: List[str] = []
_HISTORY_LIMIT = 200

_POLL_SECS = 0.02


def is_interactive() -> bool:
    """True when we can read raw keystrokes (Windows console with msvcrt)."""
    return HAS_MSVCRT and sys.stdin.isatty()


# --------------------------------------------------------------------------
# Fallback (non-TTY) line source
# --------------------------------------------------------------------------
class TerminalLineReader:
    """Background stdin reader for terminals without raw key access
    (VS Code / Cursor consoles, Git Bash, piped input)."""

    def __init__(self, state: Optional[AppState] = None):
        self.state = resolve_state(state)
        self.input_queue: "queue.Queue[str]" = queue.Queue()
        self.eof = False
        self.thread = threading.Thread(target=self._run, name="StdinReader", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.state.stop_requested:
            try:
                line = sys.stdin.readline()
            except Exception:
                break
            if not line:
                break
            self.input_queue.put(line.rstrip("\r\n"))
        self.eof = True

    def get(self, timeout: float) -> Optional[str]:
        try:
            return self.input_queue.get(timeout=timeout)
        except queue.Empty:
            return None


_fallback_reader: Optional[TerminalLineReader] = None
_fallback_lock = threading.Lock()


def _get_fallback_reader(state: AppState) -> TerminalLineReader:
    global _fallback_reader
    with _fallback_lock:
        if _fallback_reader is None:
            _fallback_reader = TerminalLineReader(state)
        return _fallback_reader


def _remember(line: str) -> None:
    line = line.strip()
    if not line:
        return
    if not COMMAND_HISTORY or COMMAND_HISTORY[-1] != line:
        COMMAND_HISTORY.append(line)
        del COMMAND_HISTORY[:-_HISTORY_LIMIT]


# --------------------------------------------------------------------------
# Line input
# --------------------------------------------------------------------------
def read_line(
    prompt: str = "",
    state: Optional[AppState] = None,
    *,
    history: bool = False,
    interruptible: bool = False,
    queue_mgr: Any = None,
) -> Optional[str]:
    """Read one line of input.

    Returns the entered text, or ``None`` when the app is stopping or (if
    ``interruptible``) when a background task was posted to the inbox while
    the input line was still empty.

    Raises ``KeyboardInterrupt`` on Ctrl+C with an empty line and
    ``EOFError`` when stdin is closed.
    """
    state = resolve_state(state)
    if is_interactive():
        return _read_line_msvcrt(prompt, state, history, interruptible, queue_mgr=queue_mgr)
    return _read_line_fallback(prompt, state, history, interruptible)


def _read_line_msvcrt(
    prompt: str,
    state: AppState,
    history: bool,
    interruptible: bool,
    queue_mgr: Any = None,
) -> Optional[str]:
    from .completion import CompletionEngine

    CONSOLE.begin_prompt(prompt)
    buf: List[str] = []
    cursor_pos = 0
    hist_idx = len(COMMAND_HISTORY)
    draft = ""
    completion_engine = CompletionEngine(state=state, queue_mgr=queue_mgr)

    try:
        while not state.stop_requested:
            if not msvcrt.kbhit():
                if interruptible and not buf and inbox.pending():
                    CONSOLE.end_prompt(commit=False)
                    return None
                time.sleep(_POLL_SECS)
                continue

            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                completion_engine.reset()
                line = "".join(buf)
                CONSOLE.end_prompt(commit=True)
                if history:
                    _remember(line)
                return line
            if ch == "\x03":  # Ctrl+C
                completion_engine.reset()
                if buf:
                    buf.clear()
                    cursor_pos = 0
                    CONSOLE.set_buffer("", 0)
                    continue
                CONSOLE.end_prompt(commit=True)
                raise KeyboardInterrupt
            if ch == "\x1a":  # Ctrl+Z
                CONSOLE.end_prompt(commit=True)
                raise EOFError
            if ch == "\x1b":  # Esc clears the line
                completion_engine.reset()
                buf.clear()
                cursor_pos = 0
                CONSOLE.set_buffer("", 0)
                continue
            if ch == "\x01":  # Ctrl+A: Home
                completion_engine.reset()
                cursor_pos = 0
                CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\x05":  # Ctrl+E: End
                completion_engine.reset()
                cursor_pos = len(buf)
                CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\x15":  # Ctrl+U: Delete line to left
                completion_engine.reset()
                buf = buf[cursor_pos:]
                cursor_pos = 0
                CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\x0b":  # Ctrl+K: Delete line to right
                completion_engine.reset()
                buf = buf[:cursor_pos]
                CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\x08":  # Backspace
                completion_engine.reset()
                if cursor_pos > 0:
                    buf.pop(cursor_pos - 1)
                    cursor_pos -= 1
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\t":  # Tab completion
                new_buf, new_cursor, changed = completion_engine.handle_tab(buf, cursor_pos)
                if changed:
                    buf = new_buf
                    cursor_pos = new_cursor
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch in ("\x00", "\xe0"):  # Extended key: second code follows
                code = msvcrt.getwch()
                if code == "K":  # Left Arrow
                    completion_engine.reset()
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "M":  # Right Arrow
                    completion_engine.reset()
                    if cursor_pos < len(buf):
                        cursor_pos += 1
                        CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "G":  # Home
                    completion_engine.reset()
                    cursor_pos = 0
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "O":  # End
                    completion_engine.reset()
                    cursor_pos = len(buf)
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "S":  # Delete
                    completion_engine.reset()
                    if cursor_pos < len(buf):
                        buf.pop(cursor_pos)
                        CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "s":  # Ctrl+Left: Jump word left
                    completion_engine.reset()
                    idx = cursor_pos - 1
                    while idx > 0 and buf[idx] == " ":
                        idx -= 1
                    while idx > 0 and buf[idx - 1] != " ":
                        idx -= 1
                    cursor_pos = max(0, idx)
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "t":  # Ctrl+Right: Jump word right
                    completion_engine.reset()
                    idx = cursor_pos
                    while idx < len(buf) and buf[idx] != " ":
                        idx += 1
                    while idx < len(buf) and buf[idx] == " ":
                        idx += 1
                    cursor_pos = min(len(buf), idx)
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "H":  # Up Arrow (History)
                    completion_engine.reset()
                    if history and COMMAND_HISTORY and hist_idx > 0:
                        if hist_idx == len(COMMAND_HISTORY):
                            draft = "".join(buf)
                        hist_idx -= 1
                        buf = list(COMMAND_HISTORY[hist_idx])
                        cursor_pos = len(buf)
                        CONSOLE.set_buffer("".join(buf), cursor_pos)
                elif code == "P":  # Down Arrow (History)
                    completion_engine.reset()
                    if history and COMMAND_HISTORY and hist_idx < len(COMMAND_HISTORY):
                        hist_idx += 1
                        buf = list(COMMAND_HISTORY[hist_idx]) if hist_idx < len(COMMAND_HISTORY) else list(draft)
                        cursor_pos = len(buf)
                        CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ch == "\x16":  # Ctrl+V: paste clipboard text
                completion_engine.reset()
                try:
                    from ..utils.clipboard import get_clipboard_text
                    text = (get_clipboard_text() or "").replace("\r", " ").replace("\n", " ")
                except Exception:
                    text = ""
                if text:
                    for c in text:
                        buf.insert(cursor_pos, c)
                        cursor_pos += 1
                    CONSOLE.set_buffer("".join(buf), cursor_pos)
                continue
            if ord(ch) >= 32:
                completion_engine.reset()
                buf.insert(cursor_pos, ch)
                cursor_pos += 1
                CONSOLE.set_buffer("".join(buf), cursor_pos)
        return None
    finally:
        if CONSOLE.prompt_active:
            CONSOLE.end_prompt(commit=False)


def _read_line_fallback(prompt: str, state: AppState, history: bool, interruptible: bool) -> Optional[str]:
    reader = _get_fallback_reader(state)
    CONSOLE.begin_prompt(prompt)
    try:
        while not state.stop_requested:
            line = reader.get(timeout=0.05)
            if line is not None:
                CONSOLE.end_prompt(commit=True)
                if history:
                    _remember(line)
                return line
            if reader.eof:
                CONSOLE.end_prompt(commit=True)
                raise EOFError
            if interruptible and inbox.pending():
                CONSOLE.end_prompt(commit=False)
                return None
        return None
    finally:
        if CONSOLE.prompt_active:
            CONSOLE.end_prompt(commit=False)


def read_single_choice(
    valid_chars: Set[str],
    default_val: str,
    state: Optional[AppState] = None,
    prompt: str = "",
) -> str:
    """Read a single keystroke (no Enter needed); Enter returns the default.

    Esc / Ctrl+C return ``"s"`` (skip).
    """
    state = resolve_state(state)
    valid = {c.lower() for c in valid_chars}

    if not is_interactive():
        try:
            line = read_line(prompt, state)
        except (KeyboardInterrupt, EOFError):
            return "s"
        line = (line or "").strip().lower()
        return line if line else default_val

    CONSOLE.begin_prompt(prompt)
    try:
        while not state.stop_requested:
            if not msvcrt.kbhit():
                time.sleep(_POLL_SECS)
                continue
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()  # discard arrow/function key
                continue
            if ch in ("\r", "\n"):
                CONSOLE.end_prompt(commit=True)
                return default_val
            if ch in ("\x03", "\x1b"):
                CONSOLE.echo("Skip")
                CONSOLE.end_prompt(commit=True)
                return "s"
            if ch.lower() in valid:
                CONSOLE.echo(ch)
                CONSOLE.end_prompt(commit=True)
                return ch.lower()
        return default_val
    finally:
        if CONSOLE.prompt_active:
            CONSOLE.end_prompt(commit=False)


def ask_text(prompt: str, state: Optional[AppState] = None) -> str:
    """Convenience: read a line for a sub-prompt; Ctrl+C / EOF cancel to ''."""
    try:
        return (read_line(prompt, state) or "").strip()
    except (KeyboardInterrupt, EOFError):
        return ""


# --------------------------------------------------------------------------
# Pickers
# --------------------------------------------------------------------------
def inspect_and_pick_formats(url: str, referer: Optional[str] = None, state: Optional[AppState] = None) -> Optional[str]:
    """Run yt-dlp -F to show all formats and let the user pick exact format codes."""
    state = resolve_state(state)
    print(f"\n{Fore.CYAN}[*] Fetching available formats from video...{Style.RESET_ALL}\n")
    cmd = [str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"), "--no-warnings"]
    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])
    if state.config.get("browser_cookies", "none") != "none":
        cmd.extend(["--cookies-from-browser", state.config["browser_cookies"]])
    if referer:
        cmd.extend(["--referer", referer])
    cmd.extend(["-F", url])

    try:
        # yt-dlp writes straight to the terminal: hide live regions meanwhile.
        with CONSOLE.suspend():
            subprocess.run(cmd)
    except Exception as e:
        print(f"{Fore.RED}[!] Error fetching formats: {e}{Style.RESET_ALL}")
        return None

    print(f"\n{Fore.YELLOW}Examples: '137+140' (1080p video + audio), '22' (720p with audio), 'best'{Style.RESET_ALL}")
    chosen = ask_text(f"{Fore.CYAN}Enter format ID (or press Enter for best): {Style.RESET_ALL}", state)
    return chosen if chosen else "bv*+ba/b"


_QUALITY_MENU = [
    ("1", Fore.GREEN, "4K / 2160p (Best Available)", "Maximum possible resolution"),
    ("2", Fore.GREEN, "1440p (2K Quad HD)", "Ultra high quality"),
    ("3", Fore.GREEN, "1080p (Full HD)", "Recommended quality & size"),
    ("4", Fore.GREEN, "720p  (HD)", "Fast download, smaller size"),
    ("5", Fore.GREEN, "480p  (SD Standard)", "Low bandwidth"),
    ("6", Fore.GREEN, "360p  (Data Saver)", "Smallest video file size"),
    ("7", Fore.YELLOW, "Audio MP3 (320kbps)", "MP3 with album artwork & tags"),
    ("8", Fore.YELLOW, "Audio M4A (Original AAC)", "Direct audio extraction"),
    ("9", Fore.YELLOW, "Audio FLAC (Lossless Studio)", "High-res lossless audiophile audio"),
    ("a", Fore.YELLOW, "Audio OPUS (Next-Gen)", "Ultra efficient modern audio"),
    ("b", Fore.YELLOW, "Audio WAV (Raw PCM)", "Uncompressed raw audio"),
    ("0", Fore.CYAN, "Universal MKV (All Subs)", "Preserves all subtitles & tracks"),
    ("f", Fore.MAGENTA, "Inspect All Formats (-F)", "Pick exact format ID table"),
]

_CHOICE_TO_PRESET = {
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "a": 10, "b": 11, "0": 12,
    # Typed aliases (fallback line mode)
    "4k": 1, "2160p": 1, "2k": 2, "1440p": 2, "1080p": 3, "1080": 3,
    "720p": 4, "720": 4, "480p": 5, "480": 5, "360p": 6, "360": 6,
    "mp3": 7, "m4a": 8, "aac": 8, "flac": 9, "opus": 10, "wav": 11, "mkv": 12,
}


def prompt_video_quality(
    url: str,
    referer: Optional[str] = None,
    state: Optional[AppState] = None,
    job: Optional[DownloadJob] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """Interactive quality picker.

    Returns ``(preset_id, None)``, ``(None, custom_format)`` or ``(None, None)``
    when the user skips.
    """
    state = resolve_state(state)
    default_pid = state.config.get("preset", 1)
    default_name = PRESETS.get(default_pid, PRESETS[1])["name"]
    bar = "═" * 71

    while True:
        cur_title = job.display_title if job else None
        lines = [
            f"\n{Fore.CYAN}╔{bar}╗{Style.RESET_ALL}",
            f"{Fore.CYAN}║ {Style.BRIGHT}{Fore.YELLOW}🎥 PICK VIDEO QUALITY FOR THIS DOWNLOAD{Style.RESET_ALL}",
            f"{Fore.CYAN}║ {Fore.WHITE}URL: {Fore.LIGHTCYAN_EX}{url[:65]}{'...' if len(url) > 65 else ''}{Style.RESET_ALL}",
        ]
        if cur_title:
            lines.append(f"{Fore.CYAN}║ {Fore.WHITE}Movie/Title: {Fore.LIGHTGREEN_EX}{cur_title}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(press [t] to rename){Style.RESET_ALL}")
        elif referer or ".m3u8" in url.lower():
            lines.append(f"{Fore.CYAN}║ {Fore.WHITE}Movie/Title: {Fore.LIGHTBLACK_EX}Auto / Unknown (press [t] to set movie name){Style.RESET_ALL}")
        if referer:
            lines.append(f"{Fore.CYAN}║ {Fore.WHITE}Referer: {Fore.YELLOW}{referer}{Style.RESET_ALL}")
        lines.append(f"{Fore.CYAN}╠{bar}╣{Style.RESET_ALL}")
        for key, color, label, desc in _QUALITY_MENU:
            lines.append(f"{Fore.CYAN}║  {color}[{key}] {label:<30}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}- {desc}{Style.RESET_ALL}")
        lines.append(f"{Fore.CYAN}║  {Fore.LIGHTCYAN_EX}[t] {'Set / Rename Movie Title':<30}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}- Custom output filename{Style.RESET_ALL}")
        lines.append(f"{Fore.CYAN}║  {Fore.RED}[s] Skip / Cancel{Style.RESET_ALL}")
        lines.append(f"{Fore.CYAN}╚{bar}╝{Style.RESET_ALL}")
        print("\n".join(lines))

        prompt = (
            f"{Fore.LIGHTWHITE_EX}Press a key [1-9, a, b, 0, f, t, s] or "
            f"{Fore.GREEN}Enter for default (#{default_pid} - {default_name}){Fore.LIGHTWHITE_EX}: {Style.RESET_ALL}"
        )
        valid_keys = {k for k, *_ in _QUALITY_MENU} | {"t", "s"}
        choice = read_single_choice(valid_keys, default_val=str(default_pid), state=state, prompt=prompt)

        if choice in ("t", "title", "name"):
            new_title = ask_text(f"{Fore.CYAN}🎬 Enter movie/video title: {Style.RESET_ALL}", state)
            if new_title and job is not None:
                job.display_title = new_title.strip()
                print(f"{Fore.GREEN}[✓] Title set to:{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{job.display_title}{Style.RESET_ALL}")
            continue
        if choice in ("f", "formats", "format"):
            return None, inspect_and_pick_formats(url, referer=referer, state=state)
        if choice in ("s", "skip", "cancel", "n"):
            print(f"{Fore.LIGHTBLACK_EX}[!] Download skipped.{Style.RESET_ALL}\n")
            return None, None
        if choice in _CHOICE_TO_PRESET:
            return _CHOICE_TO_PRESET[choice], None
        return default_pid, None
