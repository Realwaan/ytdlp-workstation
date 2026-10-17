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
from typing import Optional

from ..core.state import STATE, DownloadJob, AppState, resolve_state
from ..core.config import YTDLP_EXE, DEFAULT_DOWNLOAD_DIR
from ..queue.manager import QueueManager
from ..engine.fragment_merger import find_fragment_groups, merge_fragment_group
from ..utils.system import cleanup_orphaned_fragments, bootstrap_workstation_environment
from . import inbox
from .ui import Fore, Style, print_banner, format_linux_bar
from .input_reader import (
    HAS_MSVCRT,
    COMMAND_HISTORY,
    TerminalLineReader,
    read_line,
)
from .command_dispatcher import handle_user_command
from .clipboard import clipboard_watcher_thread


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return resolve_state(state)


def check_for_updates_background(state: Optional[AppState] = None):
    """Background check for newer yt-dlp release."""
    state = _resolve_state(state)

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
                    state.update_available = latest_ver
        except Exception:
            pass

    threading.Thread(target=_check, daemon=True).start()


def subprocess_check_output(cmd):
    import subprocess
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def run_repl(queue_mgr: QueueManager, state: Optional[AppState] = None):
    """Run the interactive REPL loop until stop_requested is set."""
    state = _resolve_state(state)
    print_banner(active_workers=queue_mgr.max_workers, state=state)
    dl_dir = Path(state.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    frag_groups = find_fragment_groups(dl_dir)
    if frag_groups:
        total_f = sum(len(v) for v in frag_groups.values())
        print(
            f"  {Fore.YELLOW}[⚡] Auto-merging {total_f} unmerged video fragment(s) found in {dl_dir.name}/...{Style.RESET_ALL}\n"
        )

        def _auto_merge_startup():
            for base_name, frags in list(frag_groups.items()):
                m_job = DownloadJob(url=base_name, display_title=base_name)
                out = merge_fragment_group(
                    directory=dl_dir,
                    base_name=base_name,
                    frags=frags,
                    job=m_job,
                    on_progress=queue_mgr.on_job_progress,
                )
                if out and out.exists():
                    b = out.stat().st_size
                    m_job.saved_filename = out.name
                    m_job.saved_filesize_str = f"{b / (1024 ** 3):.2f} GB" if b >= 1024 ** 3 else f"{b / (1024 ** 2):.1f} MB"
                    if queue_mgr.on_job_finished:
                        queue_mgr.on_job_finished(m_job, True)

        threading.Thread(target=_auto_merge_startup, name="StartupFragmentMerger", daemon=True).start()

    check_for_updates_background(state=state)

    # Start clipboard watcher thread
    watcher_t = threading.Thread(
        target=clipboard_watcher_thread,
        args=(queue_mgr, state),
        name="ClipboardWatcher",
        daemon=True,
    )
    watcher_t.start()

    prompt = f"{Fore.CYAN}>>> {Style.RESET_ALL}"

    try:
        while not state.stop_requested:
            inbox.drain()
            if state.stop_requested:
                break
            line = read_line(prompt, state, history=True, interruptible=True)
            if line is None:
                continue
            handle_user_command(line, queue_mgr, state=state)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{Fore.YELLOW}Exiting YT-DLP Workstation. Goodbye!{Style.RESET_ALL}")
    finally:
        state.stop_requested = True
        queue_mgr.stop_requested = True
        inbox.clear()
