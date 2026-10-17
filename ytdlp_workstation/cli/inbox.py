"""
Main-thread task inbox.

Only the REPL (main) thread is allowed to read from the keyboard. Background
threads that need user interaction — e.g. the clipboard watcher asking which
quality to download — post a task here instead. The REPL interrupts its idle
prompt, runs the pending tasks, then shows the prompt again.
"""

__all__ = ["post", "pending", "drain", "clear"]

import queue
from typing import Any, Callable

_TASKS: "queue.Queue[tuple[Callable[..., Any], tuple, dict]]" = queue.Queue()


def post(fn: Callable[..., Any], *args, **kwargs) -> None:
    """Schedule ``fn(*args, **kwargs)`` to run on the main REPL thread."""
    _TASKS.put((fn, args, kwargs))


def pending() -> bool:
    return not _TASKS.empty()


def drain() -> int:
    """Run all queued tasks on the calling (main) thread. Returns count run."""
    count = 0
    while True:
        try:
            fn, args, kwargs = _TASKS.get_nowait()
        except queue.Empty:
            return count
        count += 1
        try:
            fn(*args, **kwargs)
        except KeyboardInterrupt:
            print("\n[!] Interrupted.")
        except Exception as exc:  # never let a task kill the REPL
            print(f"[!] Background task failed: {exc!r}")


def clear() -> None:
    while True:
        try:
            _TASKS.get_nowait()
        except queue.Empty:
            return
