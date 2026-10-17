"""
Automatic movie and media title detector for generic HLS (.m3u8) and cloud streams.

Detects the human-readable movie/show title from:
1. URL query parameters or fragments (?title=..., ?name=..., ?dn=...)
2. Meaningful URL path slugs
3. Active Windows browser window/tab titles (Chrome, Brave, Edge, Firefox, Opera, Vivaldi, Arc)
4. Last seen streaming website URL slug or HTML <title>
"""

__all__ = [
    "detect_stream_title",
    "extract_resolution_tag",
    "clean_browser_tab_title",
]

import os
import re
import urllib.parse
import urllib.request
from typing import List, Optional

from ..utils.system import sanitize_filename

# Browser window title suffixes on Windows
_BROWSER_SUFFIXES = (
    " - Google Chrome",
    " - Brave",
    " - Microsoft\u200b Edge",
    " - Microsoft Edge",
    " — Mozilla Firefox",
    " - Mozilla Firefox",
    " - Opera",
    " - Vivaldi",
    " - Arc",
)

# Tabs that are definitely not movie/video pages
_IGNORED_TAB_PATTERNS = (
    "new tab",
    "devtools",
    "developer tools",
    "extensions",
    "settings",
    "downloads",
    "history",
    "bookmarks",
    "google search",
    " - google",
    "github",
    "chatgpt",
    "claude",
    "localhost",
    "127.0.0.1",
    "yt-dlp",
    "gmail",
    "outlook",
    "discord",
    "slack",
    "stack overflow",
)

# Streaming site keywords that boost confidence when scanning multiple browser windows
_STREAMING_KEYWORDS = (
    "movy",
    "cinejoy",
    "vidsrc",
    "braflix",
    "bflix",
    "sflix",
    "fmovies",
    "himovies",
    "flixhq",
    "watch ",
    "episode ",
    "season ",
    "stream",
    "movie",
)

# Generic path tokens that are NOT movie titles
_GENERIC_PATH_TOKENS = {
    "vd", "hls", "m3u8", "dash", "mpd", "stream", "streams", "video", "videos",
    "media", "play", "player", "embed", "e", "d", "v", "c", "watch", "movie",
    "movies", "tv", "show", "series", "master", "index", "playlist", "manifest",
    "chunklist", "live", "cdn", "storage", "files", "file", "source",
}

_RES_RE = re.compile(r"(?:^|[^0-9])(2160p|1440p|1080p|720p|480p|360p|4k)(?:[^0-9]|$)", re.IGNORECASE)


def extract_resolution_tag(url: str) -> Optional[str]:
    """Extract resolution tag like '2160p' or '1080p' from a stream URL if present."""
    if not url:
        return None
    path = urllib.parse.urlsplit(url).path
    m = _RES_RE.search(path)
    if m:
        tag = m.group(1).lower()
        return "2160p" if tag == "4k" else tag
    return None


def clean_browser_tab_title(raw_title: str) -> Optional[str]:
    """Clean a raw browser window title into a clean movie/episode title."""
    if not raw_title:
        return None

    title = raw_title.strip()

    # Strip browser application suffix
    matched_browser = False
    for suffix in _BROWSER_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            matched_browser = True
            break

    # Also handle " - Personal - Microsoft Edge" or " - Work - Microsoft Edge"
    if not matched_browser:
        m_edge = re.sub(r"\s+-\s+[^-]+-\s+Microsoft\u200b?\s+Edge$", "", title)
        if m_edge != title:
            title = m_edge.strip()
            matched_browser = True

    if not matched_browser:
        return None

    # Strip notification count "(1) " or audio playing indicator "🔊 "
    title = re.sub(r"^(?:\(\d+\)\s*|[🔊🔈🔉▶⏸⚡]+\s*)+", "", title).strip()

    low = title.lower()
    if not title or any(pat in low for pat in _IGNORED_TAB_PATTERNS):
        return None

    # Remove trailing site branding after " - ", " | ", " — ", " :: "
    # e.g. "Watch The Odyssey (2026) Online Free - Movy.sx"
    parts = re.split(r"\s+(?:[-|—•:]|::)\s+", title)
    if len(parts) > 1:
        # Keep parts that don't look like site names or generic taglines
        cleaned_parts = []
        for idx, p in enumerate(parts):
            p_low = p.lower().strip()
            if idx > 0 and any(
                kw in p_low
                for kw in (
                    "movy", "cinejoy", "braflix", "bflix", "sflix", "fmovies",
                    "himovies", "flixhq", "vidsrc", "watch free", "free movies",
                    "watch movies", "online free", "free online", "hd movies",
                    "streaming", ".sx", ".to", ".top", ".ru", ".net", ".cc", ".gg",
                )
            ):
                continue
            cleaned_parts.append(p.strip())
        if cleaned_parts:
            title = " - ".join(cleaned_parts)

    # Strip leading "Watch ", "Stream ", "Free "
    title = re.sub(r"^(?:watch|stream|play|download)\s+", "", title, flags=re.IGNORECASE).strip()

    # Strip trailing "Online Free...", "Free Online...", "Full Movie..."
    title = re.sub(
        r"\s+(?:online\s+free|free\s+online|full\s+movie(?:\s+online)?|in\s+hd|hd\s+online).*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()

    # Remove trailing punctuation
    title = title.strip(" -|—:•")
    if len(title) < 2 or len(title) > 120:
        return None
    if title.lower() in _GENERIC_PATH_TOKENS:
        return None

    return sanitize_filename(title)


def _get_windows_browser_titles() -> List[str]:
    """Return raw window titles of visible top-level windows on Windows (foreground first)."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        u32 = ctypes.windll.user32
        results: List[str] = []

        def _read_hwnd_title(hwnd) -> Optional[str]:
            if not hwnd or not u32.IsWindowVisible(hwnd):
                return None
            length = u32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return None
            buf = ctypes.create_unicode_buffer(length + 1)
            u32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value

        fg = u32.GetForegroundWindow()
        fg_title = _read_hwnd_title(fg)
        if fg_title:
            results.append(fg_title)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum_cb(hwnd, lparam):
            t = _read_hwnd_title(hwnd)
            if t and t not in results:
                results.append(t)
            return True

        u32.EnumWindows(_enum_cb, 0)
        return results
    except Exception:
        return []


def _detect_from_browser_windows() -> Optional[str]:
    """Detect movie title from open browser window titles."""
    raw_titles = _get_windows_browser_titles()
    if not raw_titles:
        return None

    # Pass 1: Prefer browser windows whose raw title mentions a streaming keyword
    for raw in raw_titles:
        raw_low = raw.lower()
        if any(kw in raw_low for kw in _STREAMING_KEYWORDS):
            cleaned = clean_browser_tab_title(raw)
            if cleaned:
                return cleaned

    # Pass 2: Fall back to any cleanable browser tab title
    for raw in raw_titles:
        cleaned = clean_browser_tab_title(raw)
        if cleaned:
            return cleaned

    return None


def _detect_from_url_params_or_slug(url: str) -> Optional[str]:
    """Extract movie title from URL query parameters (?title=...) or readable path slug."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("title", "name", "dn", "filename", "movie", "video_title"):
            if key in qs and qs[key]:
                val = urllib.parse.unquote(qs[key][0]).strip()
                val = re.sub(r"\.(mp4|mkv|webm|m3u8|ts)$", "", val, flags=re.IGNORECASE)
                if len(val) >= 2:
                    return sanitize_filename(val)

        # Check URL path segments for human-readable slugs (e.g. /movies/the-odyssey-2026/master.m3u8)
        segments = [urllib.parse.unquote(s).strip() for s in parsed.path.split("/") if s.strip()]
        for seg in reversed(segments):
            seg_clean = re.sub(r"\.(m3u8|mpd|mp4|mkv|ts|webm)$", "", seg, flags=re.IGNORECASE)
            low = seg_clean.lower()
            if low in _GENERIC_PATH_TOKENS:
                continue
            if re.match(r"^(?:index|master|playlist|chunklist|segment|frag|stream)[-_0-9a-z]*$", low):
                continue
            # Ignore high-entropy encrypted tokens / base64 / hashes (no spaces or hyphens separating words)
            if len(seg_clean) > 24 and " " not in seg_clean and seg_clean.count("-") <= 1:
                continue
            if re.match(r"^[0-9a-fA-F]{8,}$", seg_clean):
                continue
            # Must look like a slug with words separated by hyphens, underscores, or spaces
            if ("-" in seg_clean or "_" in seg_clean or " " in seg_clean) and re.search(r"[a-zA-Z]{3,}", seg_clean):
                # Strip trailing numeric ID in slug like "the-odyssey-12849"
                words = re.split(r"[-_\s]+", seg_clean)
                if len(words) >= 2 and words[-1].isdigit() and len(words[-1]) >= 5:
                    words = words[:-1]
                human = " ".join(w.capitalize() if w.islower() else w for w in words if w)
                if len(human) >= 3:
                    return sanitize_filename(human)
    except Exception:
        pass
    return None


def _detect_from_website_url(website_url: Optional[str]) -> Optional[str]:
    """Extract movie title from last_seen_website path slug or HTML <title>."""
    if not website_url:
        return None
    slug_title = _detect_from_url_params_or_slug(website_url)
    if slug_title:
        return slug_title

    try:
        parsed = urllib.parse.urlsplit(website_url)
        if not parsed.path or parsed.path == "/":
            return None
        req = urllib.request.Request(
            website_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            html = resp.read(32768).decode("utf-8", errors="ignore")
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            raw_t = re.sub(r"\s+", " ", m.group(1)).strip()
            cleaned = clean_browser_tab_title(raw_t + " - Google Chrome")
            if cleaned:
                return cleaned
    except Exception:
        pass
    return None


def detect_stream_title(url: str, last_seen_website: Optional[str] = None) -> Optional[str]:
    """
    Attempt to automatically detect the movie/episode title for a generic stream URL.
    Checks:
      1. Stream URL query parameters or readable path slug
      2. Last seen website URL slug / HTML <title>
      3. Open Windows browser tab titles (Chrome/Brave/Edge/Firefox/etc.)
    """
    title = _detect_from_url_params_or_slug(url)
    if title:
        return title

    title = _detect_from_website_url(last_seen_website)
    if title:
        return title

    title = _detect_from_browser_windows()
    if title:
        return title

    return None
