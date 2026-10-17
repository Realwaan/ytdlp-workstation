"""
Clipboard watcher thread.

Monitors the system clipboard for media URLs and Spotify links, auto-enqueuing
downloads when clipboard mode is set to "auto". Extracted from cli/main.py.
"""

__all__ = ["clipboard_watcher_thread"]

import time
import threading
import urllib.parse
from typing import Optional

from ..core.state import STATE, DownloadJob, AppState, resolve_state
from ..core.config import DEFAULT_DOWNLOAD_DIR
from ..queue.manager import QueueManager
from ..extractors.url_detector import is_valid_media_url, extract_media_url, clean_url
from ..extractors.referer import (
    auto_detect_referer,
    is_valid_streaming_referer,
    KNOWN_STREAMING_DOMAINS,
    CDN_TO_REFERER_MAP,
    MAINSTREAM_PLATFORMS,
)
from ..extractors.spotify import is_spotify_url
from ..utils.clipboard import get_clipboard_text
from ..utils.notifications import play_sound
from . import inbox
from .console import CONSOLE
from .input_reader import prompt_video_quality
from .command_dispatcher import enqueue_spotify_download
from .ui import Fore, Style


def _resolve_state(state: Optional[AppState] = None) -> AppState:
    return resolve_state(state)


def _prompt_and_enqueue(url: str, auto_ref: Optional[str], queue_mgr: QueueManager, state: AppState) -> None:
    chosen_preset, custom_fmt = prompt_video_quality(url, referer=auto_ref, state=state)
    if chosen_preset is not None or custom_fmt is not None:
        job = DownloadJob(
            url=url,
            referer=auto_ref,
            needs_quality_prompt=True,
            preset_override=chosen_preset,
            custom_format_str=custom_fmt,
        )
        queue_mgr.enqueue(job)
        ref_note = f" {Fore.LIGHTBLACK_EX}(referer: {auto_ref}){Style.RESET_ALL}" if auto_ref else ""
        print(f"{Fore.GREEN}[+] Queued{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {url}{ref_note}\n")


def clipboard_watcher_thread(queue_mgr: QueueManager, state: Optional[AppState] = None):
    """Background thread that monitors system clipboard."""
    state = _resolve_state(state)
    last_text = ""
    try:
        last_text = get_clipboard_text().strip()
    except Exception:
        pass

    while not state.stop_requested:
        time.sleep(0.4)
        clip_mode = state.config.get("clipboard_mode", "auto")
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

        # Check if copied text is a streaming website URL (never match YouTube/Twitch/CDN/media links)
        matched_site = None
        for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
            if s_domain in lower_txt:
                matched_site = s_url
                break
        if (
            not matched_site
            and lower_txt.startswith(("http://", "https://"))
            and not any(p in lower_txt for p in MAINSTREAM_PLATFORMS)
            and not any(c in lower_txt for c in CDN_TO_REFERER_MAP)
            and any(k in lower_txt for k in ("movie", "watch", "stream", "series", "anime"))
        ):
            parsed = urllib.parse.urlparse(current_text)
            if parsed.netloc:
                candidate = f"{parsed.scheme}://{parsed.netloc}/"
                if is_valid_streaming_referer(candidate):
                    matched_site = candidate

        if matched_site and not any(ext in lower_txt for ext in (".mp4", ".m3u8", ".webm", ".mkv", ".mpd", ".ts", "/vd/", "/hls/")):
            if state.last_seen_website != matched_site:
                state.last_seen_website = matched_site
                state.set_config("default_stream_referer", matched_site)
                play_sound("notice", enabled=state.config.get("sound_effects", True))
                print(f"\n{Fore.GREEN}[⚡] Auto-detected Active Streaming Site:{Style.RESET_ALL} {Fore.CYAN}{matched_site}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Stream links will auto-use this referer){Style.RESET_ALL}\n")
            continue

        # Check if copied text is Spotify
        if is_spotify_url(current_text):
            m_url = extract_media_url(current_text) or current_text
            clean = clean_url(m_url)
            with state.lock:
                if clean in state.seen_clipboard:
                    continue
                state.seen_clipboard.add(clean)
            play_sound("notice", enabled=state.config.get("sound_effects", True))
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Spotify link on Clipboard!{Style.RESET_ALL} {Fore.CYAN}{m_url}{Style.RESET_ALL}")
            if clip_mode == "auto":
                enqueue_spotify_download(m_url, queue_mgr, state=state)
            elif clip_mode == "prompt":
                with state.lock:
                    state.pending_prompt_url = m_url
                    state.pending_prompt_ref = None
            continue

        # Check media URL
        if not is_valid_media_url(current_text, media_filter_only=state.config.get("media_filter_only", True)):
            continue

        url = extract_media_url(current_text) or current_text
        clean = clean_url(url)

        with state.lock:
            if clean in state.seen_clipboard:
                continue
            state.seen_clipboard.add(clean)

        play_sound("notice", enabled=state.config.get("sound_effects", True))
        auto_ref = auto_detect_referer(url, last_seen_website=state.last_seen_website, default_referer=state.config.get("default_stream_referer", "https://movy.sx/"))
        if auto_ref:
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Cloud Stream! Attached Referer:{Style.RESET_ALL} {Fore.CYAN}{auto_ref}{Style.RESET_ALL}")

        if clip_mode == "auto":
            needs_prompt = state.config.get("ask_quality_each_time", True)
            if needs_prompt:
                if CONSOLE.prompt_active:
                    inbox.post(_prompt_and_enqueue, url, auto_ref, queue_mgr, state)
                else:
                    _prompt_and_enqueue(url, auto_ref, queue_mgr, state)
            else:
                job = DownloadJob(url=url, referer=auto_ref, needs_quality_prompt=False)
                queue_mgr.enqueue(job)
                print(f"{Fore.GREEN}[+] Queued{Style.RESET_ALL} {Fore.CYAN}[{job.id}]{Style.RESET_ALL} {url}\n")
        elif clip_mode == "prompt":
            with state.lock:
                state.pending_prompt_url = url
                state.pending_prompt_ref = auto_ref
