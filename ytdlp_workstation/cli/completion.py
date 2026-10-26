"""
Terminal Tab autocompletion engine for ytdlp_workstation.

Provides completion candidates for core commands, quality shortcuts,
subcommands, and dynamic queue/job identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

from ..core.state import AppState, resolve_state


# Master list of top-level commands recognized by the CLI
TOP_LEVEL_COMMANDS: List[str] = [
    # General / Session
    "help",
    "queue",
    "quit",
    "exit",
    "q",
    "cls",
    "clear",
    "pause",
    "resume",
    "cancel",
    "clearqueue",
    "workers",
    "settings",
    "preset",
    "history",
    "open",
    "reveal",
    "play",
    "watch",
    "retry",
    "dir",
    "update",
    # Downloads / Media
    "search",
    "spotify",
    "info",
    "inspect",
    "archive",
    "codec",
    "site",
    "website",
    "referer",
    "ref",
    "trim",
    "clip",
    "items",
    "subs",
    "cookies",
    "limit",
    "qmode",
    "sb",
    "name",
    "title",
    "merge",
    "nowm",
    "sniff",
    "clean",
    "delogo",
    "crop",
    # Quality shortcuts
    "1080p",
    "720p",
    "4k",
    "1440p",
    "480p",
    "360p",
    "mp3",
    "flac",
    "m4a",
    "wav",
    "best",
    "worst",
]

# Static subcommand completions
SUBCOMMAND_MAP: Dict[str, List[str]] = {
    "help": ["downloads", "audio", "streaming", "settings", "queue", "watermark"],
    "history": ["clear"],
    "archive": ["clear", "check"],
    "codec": ["auto", "avc", "hevc", "av01", "vp9"],
    "clean": ["delogo", "crop"],
    "sb": ["on", "off"],
    "cookies": ["chrome", "edge", "firefox", "brave", "off"],
    "cancel": ["all"],
}


def _common_prefix(strings: List[str]) -> str:
    """Return the longest common prefix of a list of strings."""
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix


def get_job_candidates(
    queue_mgr: Any = None,
    filter_status: Optional[str] = None,
) -> List[str]:
    """Retrieve 1-based index numbers and short IDs for active/pending/completed jobs."""
    if queue_mgr is None:
        return []
    candidates: List[str] = []
    
    try:
        with queue_mgr.lock:
            active_jobs = list(queue_mgr.active_jobs.values())
            pending_jobs = list(queue_mgr.pending_queue)

        if filter_status == "active_or_pending" or filter_status is None:
            total = len(active_jobs) + len(pending_jobs)
            for i in range(1, total + 1):
                candidates.append(str(i))
            for j in active_jobs + pending_jobs:
                candidates.append(j.id[:8])
    except Exception:
        pass

    return candidates


def get_completion_candidates(
    line: str,
    cursor_pos: int,
    state: Optional[AppState] = None,
    queue_mgr: Any = None,
) -> Tuple[int, int, str, List[str]]:
    """Determine the replacement span [start, end], current word prefix, and matching candidates.

    Returns:
        (word_start, word_end, prefix, candidates)
    """
    state = resolve_state(state) if state is not None else None
    
    # Identify word boundary before cursor
    before_cursor = line[:cursor_pos]
    tokens = before_cursor.split()

    if not before_cursor or before_cursor.endswith(" "):
        # Cursor is after whitespace, completing a new argument or empty line
        prefix = ""
        word_start = cursor_pos
        word_end = cursor_pos
        current_token_idx = len(tokens)
    else:
        # Cursor is inside or at the end of an existing token
        last_space = before_cursor.rfind(" ")
        word_start = last_space + 1 if last_space != -1 else 0
        word_end = cursor_pos
        prefix = before_cursor[word_start:word_end]
        current_token_idx = len(tokens) - 1

    first_cmd = tokens[0].lower() if tokens else ""

    if current_token_idx == 0:
        # Completing the top-level command
        matches = [c for c in TOP_LEVEL_COMMANDS if c.lower().startswith(prefix.lower())]
        matches.sort()
        return word_start, word_end, prefix, matches

    # Completing arguments
    arg_candidates: List[str] = []
    if first_cmd in SUBCOMMAND_MAP:
        arg_candidates.extend(SUBCOMMAND_MAP[first_cmd])

    if first_cmd in ("cancel", "info", "inspect"):
        job_cands = get_job_candidates(queue_mgr, filter_status="active_or_pending")
        arg_candidates.extend(job_cands)
    elif first_cmd in ("play", "watch", "reveal", "retry"):
        # For play/reveal/retry, accept indices 1..15 or hex IDs from history/downloads
        for i in range(1, 10):
            arg_candidates.append(str(i))
        if state is not None:
            entries = state.history_manager.get_entries(limit=10)
            for e in entries:
                jid = e.get("id")
                if jid:
                    arg_candidates.append(str(jid)[:8])

    matches = [c for c in arg_candidates if c.lower().startswith(prefix.lower())]
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            deduped.append(m)

    return word_start, word_end, prefix, deduped


@dataclass
class CompletionSession:
    """Manages multi-tab cycling state."""
    word_start: int
    word_end: int
    prefix: str
    candidates: List[str]
    index: int = 0
    lcp_applied: bool = False


class CompletionEngine:
    """Tracks tab completions and cycling across keystrokes."""

    def __init__(self, state: Optional[AppState] = None, queue_mgr: Any = None):
        self.state = state
        self.queue_mgr = queue_mgr
        self.session: Optional[CompletionSession] = None

    def reset(self) -> None:
        self.session = None

    def handle_tab(self, buf: List[str], cursor_pos: int) -> Tuple[List[str], int, bool]:
        """Handle a Tab keystroke.

        Returns:
            (new_buf, new_cursor_pos, changed)
        """
        line = "".join(buf)

        if self.session is None:
            word_start, word_end, prefix, candidates = get_completion_candidates(
                line, cursor_pos, state=self.state, queue_mgr=self.queue_mgr
            )
            if not candidates:
                return buf, cursor_pos, False

            lcp = _common_prefix(candidates)

            # If LCP is strictly longer than typed prefix, expand to LCP first
            if len(lcp) > len(prefix):
                # If only 1 candidate, append a trailing space
                suffix = " " if len(candidates) == 1 else ""
                replacement = lcp + suffix
                new_line = line[:word_start] + replacement + line[word_end:]
                new_cursor = word_start + len(replacement)
                
                if len(candidates) > 1:
                    # Store session so next Tab cycles through candidates
                    self.session = CompletionSession(
                        word_start=word_start,
                        word_end=new_cursor,
                        prefix=lcp,
                        candidates=candidates,
                        index=-1,
                        lcp_applied=True,
                    )
                return list(new_line), new_cursor, True

            # If LCP is not longer, start cycling from the first candidate
            self.session = CompletionSession(
                word_start=word_start,
                word_end=word_end,
                prefix=prefix,
                candidates=candidates,
                index=-1,
                lcp_applied=False,
            )

        # Multi-tab candidate cycling
        session = self.session
        session.index = (session.index + 1) % len(session.candidates)
        candidate = session.candidates[session.index]
        suffix = " " if len(session.candidates) == 1 else ""
        replacement = candidate + suffix

        new_line = line[:session.word_start] + replacement + line[session.word_end:]
        new_cursor = session.word_start + len(replacement)
        session.word_end = new_cursor
        return list(new_line), new_cursor, True
