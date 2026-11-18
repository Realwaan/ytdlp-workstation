"""
Universal Web Video Sniffer.

Inspects arbitrary web pages (news sites, blogs, streaming portals) to extract
embedded HTML5 video streams, OpenGraph videos, JSON-LD metadata, and player configs.

Accelerates HTML regex/JSON-LD extraction and concurrent async HTTP/2 fetching via
`ytdlp_rust_core` when compiled, with an automatic pure-Python fallback.
"""

from __future__ import annotations

import re
import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, List, Any

from ..engine.rust_accel import is_rust_enabled, rust_core

__all__ = [
    "SniffedMediaResult",
    "extract_media_from_html",
    "extract_all_media_from_html",
    "sniff_webpage_media",
    "sniff_web_media",
    "sniff_webpages_batch",
    "_resolve_relative_url",
]

USER_AGENT_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class SniffedMediaResult:
    """Represents a discovered video stream from an arbitrary webpage."""

    media_url: str
    title: str
    referer: str
    source_type: str = "html5"  # "og:video", "json-ld", "html5", "player-config", "direct-header"
    is_m3u8: bool = False

    @property
    def url(self) -> str:
        return self.media_url

    @property
    def stream_type(self) -> str:
        return self.source_type


# Regex patterns for direct embedded media in HTML (pure-Python fallback)
RE_OG_VIDEO = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["\']\s+[^>]*?content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
RE_OG_VIDEO_ALT = re.compile(
    r'<meta\s+[^>]*?content=["\']([^"\']+)["\']\s+[^>]*?(?:property|name)=["\'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["\']',
    re.IGNORECASE,
)
RE_VIDEO_SRC = re.compile(
    r'<(?:video|source)\s+[^>]*?src=["\']([^"\']+\.(?:mp4|m3u8|webm|mov|mkv|mpd)(?:\?[^"\']*)?)["\']',
    re.IGNORECASE,
)
RE_PLAYER_SCRIPT_FILE = re.compile(
    r'(?:file|source|src|url)\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8|webm|mpd)(?:\?[^"\']*)?)["\']',
    re.IGNORECASE,
)
RE_HTML_TITLE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _from_rust_media(rm: Any) -> SniffedMediaResult:
    return SniffedMediaResult(
        media_url=rm.media_url,
        title=rm.title,
        referer=rm.referer,
        source_type=rm.source_type,
        is_m3u8=bool(rm.is_m3u8),
    )


def _is_urlopen_unpatched() -> bool:
    fn = urllib.request.urlopen
    return (
        getattr(fn, "__module__", "") == "urllib.request"
        and getattr(fn, "__name__", "") == "urlopen"
    )


def _resolve_relative_url(base_url: str, link: str) -> str:
    """Resolve a relative URL to an absolute HTTP(S) URL."""
    if not link:
        return ""
    if is_rust_enabled() and rust_core is not None:
        return str(rust_core.resolve_relative_url(base_url, link))

    link = link.strip()
    if link.startswith("//"):
        parsed = urllib.parse.urlparse(base_url)
        scheme = parsed.scheme or "https"
        return f"{scheme}:{link}"
    if link.startswith(("http://", "https://")):
        return link
    return urllib.parse.urljoin(base_url, link)


def _extract_all_media_python(html: str, page_url: str) -> List[SniffedMediaResult]:
    """Pure-Python fallback to inspect raw HTML content for embedded video streams."""
    if not html:
        return []

    title_match = RE_HTML_TITLE.search(html)
    raw_title = title_match.group(1).strip() if title_match else "Web Video"
    clean_title = re.sub(r"[\r\n\t]+", " ", raw_title)
    clean_title = re.split(r"\s+[|\-–—]\s+", clean_title)[0].strip() or "Web Video"

    results: List[SniffedMediaResult] = []
    seen = set()

    def _push(cand: str, title: str, source_type: str) -> None:
        if cand and cand not in seen:
            seen.add(cand)
            results.append(
                SniffedMediaResult(
                    media_url=cand,
                    title=title,
                    referer=page_url,
                    source_type=source_type,
                    is_m3u8=".m3u8" in cand.lower(),
                )
            )

    # 1. OpenGraph and Twitter card video streams
    for rx in (RE_OG_VIDEO, RE_OG_VIDEO_ALT):
        for m_og in rx.finditer(html):
            cand = _resolve_relative_url(page_url, m_og.group(1).strip())
            if cand.startswith("http") and not cand.lower().endswith((".html", ".htm", ".php")):
                _push(cand, clean_title, "og:video")

    # 2. JSON-LD structured data (VideoObject)
    def _collect_video_objs(node: Any) -> List[dict]:
        found: List[dict] = []
        if isinstance(node, dict):
            ntype = node.get("@type")
            if ntype == "VideoObject" or (isinstance(ntype, list) and "VideoObject" in ntype):
                found.append(node)
            if "@graph" in node:
                found.extend(_collect_video_objs(node["@graph"]))
        elif isinstance(node, list):
            for elem in node:
                found.extend(_collect_video_objs(elem))
        return found

    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1).strip())
            for it in _collect_video_objs(data):
                content_url = it.get("contentUrl") or it.get("embedUrl")
                if content_url:
                    cand = _resolve_relative_url(page_url, str(content_url).strip())
                    v_name = str(it.get("name") or "").strip() or clean_title
                    _push(cand, v_name, "json-ld")
        except Exception:
            pass

    # 3. HTML5 <video> / <source> elements
    for m_vid in RE_VIDEO_SRC.finditer(html):
        cand = _resolve_relative_url(page_url, m_vid.group(1).strip())
        _push(cand, clean_title, "html5")

    # 4. Inline player configs (JWPlayer, VideoJS, Hls.js)
    for m_script in RE_PLAYER_SCRIPT_FILE.finditer(html):
        cand = _resolve_relative_url(page_url, m_script.group(1).strip())
        _push(cand, clean_title, "player-config")

    return results


def extract_all_media_from_html(html: str, page_url: str) -> List[SniffedMediaResult]:
    """Extract all unique embedded video streams from raw HTML in priority order."""
    if not html:
        return []
    if is_rust_enabled() and rust_core is not None:
        raw_list = rust_core.extract_all_media_from_html(html, page_url)
        return [_from_rust_media(item) for item in raw_list]
    return _extract_all_media_python(html, page_url)


def extract_media_from_html(html: str, page_url: str) -> Optional[SniffedMediaResult]:
    """Inspect raw HTML content to locate the highest-priority embedded video stream."""
    if not html:
        return None
    if is_rust_enabled() and rust_core is not None:
        rm = rust_core.extract_media_from_html(html, page_url)
        return _from_rust_media(rm) if rm is not None else None

    all_items = _extract_all_media_python(html, page_url)
    return all_items[0] if all_items else None


def _sniff_webpage_urllib(page_url: str, timeout: float = 8.0, all_streams: bool = False) -> List[SniffedMediaResult]:
    """Fetch webpage via `urllib.request.urlopen` and extract embedded streams."""
    if not page_url or not page_url.startswith(("http://", "https://")):
        return []

    try:
        req = urllib.request.Request(
            page_url,
            headers={
                "User-Agent": USER_AGENT_DESKTOP,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type", "") or "").lower()
            if any(
                t in content_type
                for t in ("video/", "audio/", "application/vnd.apple.mpegurl", "application/x-mpegurl")
            ):
                final_url = resp.geturl()
                return [
                    SniffedMediaResult(
                        media_url=final_url,
                        title="Direct Video Stream",
                        referer=page_url,
                        source_type="direct-header",
                        is_m3u8="mpegurl" in content_type or ".m3u8" in final_url.lower(),
                    )
                ]

            html = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
            if all_streams:
                return extract_all_media_from_html(html, page_url)
            single = extract_media_from_html(html, page_url)
            return [single] if single else []
    except Exception:
        return []


def sniff_webpage_media(page_url: str, timeout: float = 8.0) -> Optional[SniffedMediaResult]:
    """Fetch webpage HTML and sniff for the primary embedded video stream."""
    if not page_url or not page_url.startswith(("http://", "https://")):
        return None

    if is_rust_enabled() and rust_core is not None and _is_urlopen_unpatched():
        rm = rust_core.sniff_webpage(page_url, float(timeout))
        return _from_rust_media(rm) if rm is not None else None

    found = _sniff_webpage_urllib(page_url, timeout=timeout, all_streams=False)
    return found[0] if found else None


def sniff_web_media(page_url: str, timeout: float = 8.0) -> List[SniffedMediaResult]:
    """Fetch webpage and return list of all sniffed media streams."""
    if not page_url or not page_url.startswith(("http://", "https://")):
        return []
    return _sniff_webpage_urllib(page_url, timeout=timeout, all_streams=True)


def sniff_webpages_batch(
    page_urls: List[str],
    timeout: float = 8.0,
    max_concurrency: int = 16,
) -> List[Optional[SniffedMediaResult]]:
    """
    Fetch and sniff multiple webpages concurrently, returning results in input order.
    Uses Tokio + Reqwest HTTP/2 async connection pool when `ytdlp_rust_core` is active.
    """
    if not page_urls:
        return []

    if is_rust_enabled() and rust_core is not None and _is_urlopen_unpatched():
        raw_results = rust_core.sniff_webpages_batch(
            [str(u) for u in page_urls],
            float(timeout),
            int(max(1, max_concurrency)),
        )
        return [_from_rust_media(r) if r is not None else None for r in raw_results]

    workers = max(1, min(max_concurrency, len(page_urls), 32))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u: sniff_webpage_media(u, timeout=timeout), page_urls))
