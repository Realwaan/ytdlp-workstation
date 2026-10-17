"""
Thread-safe terminal console.

The console is the single owner of the screen. It keeps track of two "live"
regions at the bottom of the terminal:

    ┌ ... regular scrolling output (print) ...
    │ [status line for job A]      <- live status region (progress bars)
    │ [status line for job B]
    └ >>> user is typing here_     <- live prompt line

Any thread may ``print()`` (once the console is installed as ``sys.stdout``)
or call :meth:`Console.set_status`. Before writing, the console erases the
live regions, writes the message, then redraws the status lines and the
prompt with whatever the user has typed so far. This prevents worker threads
from corrupting the input line.

When stdout is not an interactive terminal (pipes, CI, some IDE consoles)
the console degrades to plain line output and status lines are not drawn.
"""

__all__ = ["Console", "CONSOLE"]

import re
import sys
import time
import shutil
import threading
from collections import OrderedDict
from contextlib import contextmanager
from typing import Optional, TextIO

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def visible_len(text: str) -> int:
    """Length of text as rendered (ANSI escape sequences stripped)."""
    return len(_ANSI_RE.sub("", text))


class Console:
    """Serialises all terminal writes and keeps the prompt line intact."""

    STATUS_REFRESH_SECS = 0.1

    def __init__(self, stream: Optional[TextIO] = None):
        self._lock = threading.RLock()
        self._stream = stream
        self._installed = False
        self._live = False            # True = ANSI line editing available

        self._prompt: Optional[str] = None
        self._buffer = ""
        self._prompt_drawn = False

        self._status: "OrderedDict[str, str]" = OrderedDict()
        self._status_drawn = 0
        self._last_status_draw = 0.0

        self._pending = ""            # partial (no newline yet) write
        self._suspended = 0

    # ------------------------------------------------------------------ setup
    @property
    def stream(self) -> TextIO:
        if self._stream is not None:
            return self._stream
        current = sys.stdout
        if current is not self and current is not None:
            return current
        return sys.__stdout__

    @property
    def live(self) -> bool:
        return self._live

    def install(self, live: Optional[bool] = None) -> None:
        """Route ``sys.stdout`` through the console."""
        with self._lock:
            if self._installed:
                return
            if self._stream is None:
                self._stream = sys.stdout
            _enable_windows_vt()
            self._live = self.stream.isatty() if live is None else live
            sys.stdout = self  # type: ignore[assignment]
            self._installed = True

    def uninstall(self) -> None:
        with self._lock:
            if not self._installed:
                return
            self._erase_live()
            self._flush_pending()
            self._status.clear()
            self._prompt = None
            if self._stream is not None:
                sys.stdout = self._stream  # type: ignore[assignment]
            self._stream = None
            self._installed = False
            self._live = False

    # --------------------------------------------------- file-like interface
    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            out = self.stream
            if not self._has_live_region():
                out.write(text)
                return len(text)

            self._pending += text
            if "\n" in self._pending:
                head, self._pending = self._pending.rsplit("\n", 1)
                self._erase_live()
                out.write(head + "\n")
                self._draw_live()
                out.flush()
        return len(text)

    def flush(self) -> None:
        with self._lock:
            try:
                self.stream.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        try:
            return self.stream.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self.stream.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self.stream, "encoding", "utf-8")

    def __getattr__(self, name):
        # Delegate anything else (errors, buffer, ...) to the real stream.
        return getattr(self.stream, name)

    # ------------------------------------------------------------- status bar
    def set_status(self, key: str, line: str) -> None:
        """Create or update a live status line (e.g. a progress bar)."""
        line = line.replace("\r", "").replace("\n", " ")
        with self._lock:
            is_new = key not in self._status
            self._status[key] = line
            if not self._live or self._suspended:
                return
            now = time.monotonic()
            if not is_new and now - self._last_status_draw < self.STATUS_REFRESH_SECS:
                return
            self._last_status_draw = now
            self._redraw()

    def clear_status(self, key: str) -> None:
        with self._lock:
            if self._status.pop(key, None) is None:
                return
            if self._live and not self._suspended:
                self._redraw()

    # ----------------------------------------------------------- prompt line
    def begin_prompt(self, prompt: str) -> None:
        with self._lock:
            self._flush_pending()
            self._erase_live()
            self._prompt = prompt
            self._buffer = ""
            self._draw_live()
            self.flush()

    def echo(self, text: str) -> None:
        """Append typed characters to the prompt buffer."""
        with self._lock:
            self._buffer += text
            if self._prompt_drawn:
                self.stream.write(text)
                self.flush()

    def set_buffer(self, text: str) -> None:
        """Replace the prompt buffer (backspace, history, Esc...)."""
        with self._lock:
            self._buffer = text
            if self._prompt_drawn and self._live:
                self.stream.write("\r\x1b[K" + (self._prompt or "") + text)
                self.flush()

    def end_prompt(self, commit: bool = True) -> None:
        """Finish the prompt.

        commit=True keeps ``prompt + input`` as a permanent scrollback line;
        commit=False removes the prompt (used when the prompt is abandoned).
        """
        with self._lock:
            if self._prompt is None:
                return
            if self._live:
                self._erase_live()
                if commit:
                    self.stream.write(self._prompt + self._buffer + "\n")
                self._prompt = None
                self._buffer = ""
                self._draw_live()
            else:
                # Cooked terminals already echoed the user's newline.
                self._prompt = None
                self._buffer = ""
                self._prompt_drawn = False
            self.flush()

    @property
    def prompt_active(self) -> bool:
        return self._prompt is not None

    # ------------------------------------------------------------ suspension
    @contextmanager
    def suspend(self):
        """Hide live regions while something else owns the screen.

        Use around subprocesses that inherit the terminal (``yt-dlp -F``)
        or around ``cls``.
        """
        with self._lock:
            self._flush_pending()
            self._erase_live()
            self._suspended += 1
            self.flush()
        try:
            yield
        finally:
            with self._lock:
                self._suspended -= 1
                if not self._suspended:
                    self._draw_live()
                    self.flush()

    # -------------------------------------------------------------- internals
    def _has_live_region(self) -> bool:
        return not self._suspended and (self._prompt_drawn or self._status_drawn > 0)

    def _flush_pending(self) -> None:
        if self._pending:
            self._erase_live()
            self.stream.write(self._pending + "\n")
            self._pending = ""

    def _redraw(self) -> None:
        self._erase_live()
        self._draw_live()
        self.flush()

    def _erase_live(self) -> None:
        out = self.stream
        if self._live:
            if self._prompt_drawn:
                out.write("\r\x1b[K")
            for _ in range(self._status_drawn):
                out.write("\x1b[1A\r\x1b[K")
        elif self._prompt_drawn:
            # No cursor control: move off the prompt line.
            out.write("\n")
        self._prompt_drawn = False
        self._status_drawn = 0

    def _draw_live(self) -> None:
        if self._suspended:
            return
        out = self.stream
        if self._live and self._status:
            width = max(20, shutil.get_terminal_size((80, 20)).columns - 1)
            for line in self._status.values():
                if visible_len(line) > width:
                    line = _ANSI_RE.sub("", line)[: width - 1] + "…"
                out.write(line + "\x1b[0m\n")
            self._status_drawn = len(self._status)
        if self._prompt is not None:
            out.write(self._prompt + self._buffer)
            self._prompt_drawn = True


def _enable_windows_vt() -> None:
    """Enable Windows 10+ Virtual Terminal Processing for ANSI cursor codes."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


CONSOLE = Console()
