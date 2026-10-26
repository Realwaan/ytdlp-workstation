"""
Universal Web Video Sniffer.

Inspects arbitrary web pages (news sites, blogs, streaming portals) to extract
embedded HTML5 video streams, OpenGraph videos, JSON-LD metadata, and player configs.
"""

from __future__ import annotations

import re
import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


USER_AGENT_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


@dataclass
class SniffedMediaResult:
    """Represents a discovered video stream from an arbitrary webpage."""
    media_url: str
    title: str
    referer: str
    source_type: str = "html5"  # "og:video", "json-ld", "html5", "player-config", "iframe"
    is_m3u8: bool = False

    @property
    def url(self) -> str:
        return self.media_url

    @property
    def stream_type(self) -> str:
        return self.source_type


# Regex patterns for direct embedded media in HTML
RE_OG_VIDEO = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["\']\s+[^>]*?content=["\']([^"\']+)["\']',
    re.IGNORECASE
)
RE_OG_VIDEO_ALT = re.compile(
    r'<meta\s+[^>]*?content=["\']([^"\']+)["\']\s+[^>]*?(?:property|name)=["\'](?:og:video|og:video:url|og:video:secure_url|twitter:player:stream)["\']',
    re.IGNORECASE
)
RE_VIDEO_SRC = re.compile(
    r'<(?:video|source)\s+[^>]*?src=["\']([^"\']+\.(?:mp4|m3u8|webm|mov|mkv|mpd)(?:\?[^"\']*)?)["\']',
    re.IGNORECASE
)
RE_PLAYER_SCRIPT_FILE = re.compile(
    r'(?:file|source|src|url)\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8|webm|mpd)(?:\?[^"\']*)?)["\']',
    re.IGNORECASE
)
RE_HTML_TITLE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE)


def _resolve_relative_url(base_url: str, link: str) -> str:
    """Resolve a relative URL to an absolute HTTP(S) URL."""
    if not link:
        return ""
    if link.startswith("//"):
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme}:{link}"
    if link.startswith(("http://", "https://")):
        return link
    return urllib.parse.urljoin(base_url, link)


def extract_media_from_html(html: str, page_url: str) -> Optional[SniffedMediaResult]:
    """Inspect raw HTML content to locate embedded video streams."""
    if not html:
        return None

    # 1. Extract clean page title
    title_match = RE_HTML_TITLE.search(html)
    raw_title = title_match.group(1).strip() if title_match else "Web Video"
    clean_title = re.sub(r'[\r\n\t]+', ' ', raw_title)
    # Strip site names from end of title (e.g. "My Video - CNN.com")
    clean_title = re.split(r'\s+[|\-–—]\s+', clean_title)[0].strip() or "Web Video"

    # 2. Check OpenGraph and Twitter card video streams
    m_og = RE_OG_VIDEO.search(html) or RE_OG_VIDEO_ALT.search(html)
    if m_og:
        cand = _resolve_relative_url(page_url, m_og.group(1).strip())
        if cand.startswith("http") and not cand.endswith((".html", ".htm", ".php")):
            return SniffedMediaResult(
                media_url=cand,
                title=clean_title,
                referer=page_url,
                source_type="og:video",
                is_m3u8=".m3u8" in cand.lower(),
            )

    # 3. Check JSON-LD structured data (VideoObject)
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(m.group(1).strip())
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") == "VideoObject":
                    content_url = it.get("contentUrl") or it.get("embedUrl")
                    if content_url:
                        cand = _resolve_relative_url(page_url, content_url)
                        v_name = it.get("name") or clean_title
                        return SniffedMediaResult(
                            media_url=cand,
                            title=v_name,
                            referer=page_url,
                            source_type="json-ld",
                            is_m3u8=".m3u8" in cand.lower(),
                        )
        except Exception:
            pass

    # 4. Check HTML5 <video> / <source> elements
    m_vid = RE_VIDEO_SRC.search(html)
    if m_vid:
        cand = _resolve_relative_url(page_url, m_vid.group(1).strip())
        return SniffedMediaResult(
            media_url=cand,
            title=clean_title,
            referer=page_url,
            source_type="html5",
            is_m3u8=".m3u8" in cand.lower(),
        )

    # 5. Check inline player configs (JWPlayer, VideoJS, Hls.js script source variables)
    m_script = RE_PLAYER_SCRIPT_FILE.search(html)
    if m_script:
        cand = _resolve_relative_url(page_url, m_script.group(1).strip())
        return SniffedMediaResult(
            media_url=cand,
            title=clean_title,
            referer=page_url,
            source_type="player-config",
            is_m3u8=".m3u8" in cand.lower(),
        )

    return None


def sniff_webpage_media(page_url: str, timeout: float = 8.0) -> Optional[SniffedMediaResult]:
    """Fetch webpage HTML and sniff for embedded video streams."""
    if not page_url or not page_url.startswith(("http://", "https://")):
        return None

    try:
        req = urllib.request.Request(
            page_url,
            headers={
                "User-Agent": USER_AGENT_DESKTOP,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            # If server directly returned a media file, return it directly
            if any(t in content_type for t in ("video/", "audio/", "application/vnd.apple.mpegurl", "application/x-mpegurl")):
                return SniffedMediaResult(
                    media_url=resp.geturl(),
                    title="Direct Video Stream",
                    referer=page_url,
                    source_type="direct-header",
                    is_m3u8="mpegurl" in content_type or ".m3u8" in resp.geturl().lower(),
                )

            html = resp.read().decode("utf-8", errors="replace")
            return extract_media_from_html(html, page_url)
    except Exception:
        return None


def sniff_web_media(page_url: str, timeout: float = 8.0) -> List[SniffedMediaResult]:
    """Fetch webpage and return list of all sniffed media streams."""
    single = sniff_webpage_media(page_url, timeout=timeout)
    return [single] if single else []

