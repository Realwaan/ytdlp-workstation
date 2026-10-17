"""
Interactive terminal REPL loop.

Handles the >>> prompt, keyboard input (msvcrt on Windows TTY or fallback
reader), command history / arrow-key navigation, and dispatches to the
command dispatcher. Extracted from cli/main.py.
"""

__all__ = ["run_repl", "check_for_updates_background"]

import sys
import time
import threading
from pathlib import Path

from ..core.state import STATE, DownloadJob
from ..core.config import YTDLP_EXE
from ..queue.manager import QueueManager
from ..utils.system import cleanup_orphaned_fragments, bootstrap_workstation_environment
from .ui import Fore, Style, print_banner, format_linux_bar
from .input_reader import (
    HAS_MSVCRT,
    COMMAND_HISTORY,
    TerminalLineReader,
)
from .command_dispatcher import handle_user_command
from .clipboard import clipboard_watcher_thread


if HAS_MSVCRT:
    import msvcrt


def check_for_updates_background():
    """Background check for newer yt-dlp release."""
    def _check():
        try:
            cmd = [str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"), "--version"]
            cur_ver = subprocess_check_output(cmd)
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

    import subprocess
    threading.Thread(target=_check, daemon=True).start()


def subprocess_check_output(cmd):
    import subprocess
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def run_repl(queue_mgr: QueueManager):
    """Run the interactive REPL loop until stop_requested is set."""
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
                _run_msvcrt_loop(prompt, queue_mgr)
            else:
                _run_fallback_loop(prompt, fallback_reader, queue_mgr)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{Fore.YELLOW}Exiting YT-DLP Workstation. Goodbye!{Style.RESET_ALL}")
    finally:
        STATE.stop_requested = True
        queue_mgr.stop_requested = True


def _run_msvcrt_loop(prompt: str, queue_mgr: QueueManager):
    """Single iteration of the msvcrt-based Windows TTY input loop."""
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


def _run_fallback_loop(prompt: str, fallback_reader, queue_mgr: QueueManager):
    """Single iteration of the fallback (non-TTY) input loop."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while not STATE.stop_requested:
        if fallback_reader and fallback_reader.input_queue:
            line = fallback_reader.input_queue.popleft()
            handle_user_command(line, queue_mgr)
            break
        time.sleep(0.04)
