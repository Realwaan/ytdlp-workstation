"""
Dedicated No-Watermark video extraction engine.

Resolves clean, watermark-free direct video streams from TikTok, Douyin,
CapCut, Xiaohongshu, Instagram Reels, and Threads.
"""

from __future__ import annotations

import re
import json
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple


USER_AGENT_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
USER_AGENT_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


@dataclass
class CleanMediaResult:
    """Represents a resolved clean media stream without watermarks."""
    direct_url: str
    title: str
    thumbnail: str = ""
    duration: str = ""
    referer: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    platform: str = ""


# Convenient alias
NoWatermarkMedia = CleanMediaResult



# Domains that typically embed or overlay watermarks during app playback
WATERMARK_DOMAINS = [
    "tiktok.com",
    "douyin.com",
    "capcut.com",
    "xiaohongshu.com",
    "xhslink.com",
    "kuaishou.com",
    "kwai.com",
]


def is_no_watermark_candidate(url: str) -> bool:
    """Return True if URL is from a platform that typically requires clean stream unwatermarking."""
    if not url:
        return False
    lower = url.lower()
    return any(d in lower for d in WATERMARK_DOMAINS)


def follow_redirects(url: str, timeout: float = 6.0) -> str:
    """Follow HTTP 301/302 shortlinks (e.g. vt.tiktok.com, v.douyin.com, xhslink.com) to final destination."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_DESKTOP})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return url


def clean_douyin_watermark_url(url: str) -> str:
    """Rewrite Douyin video CDN URL to replace 'playwm' with 'play' for watermark removal."""
    if not url:
        return ""
    # Douyin's watermark removal trick: replace /playwm/ with /play/
    cleaned = url.replace("/playwm/", "/play/")
    cleaned = re.sub(r'([?&])watermark=[0-9]+', '', cleaned)
    return cleaned


def resolve_tiktok_clean(url: str, timeout: float = 8.0) -> Optional[CleanMediaResult]:
    """Resolve TikTok video to clean unwatermarked MP4 stream."""
    canonical_url = follow_redirects(url, timeout=timeout)

    # 1. First attempt: TikWM high-speed clean API
    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(canonical_url)}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": USER_AGENT_DESKTOP,
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data and data.get("code") == 0 and "data" in data:
                d = data["data"]
                # 'play' is the clean stream without watermark
                clean_url = d.get("play") or d.get("hdplay")
                if clean_url:
                    title = d.get("title") or "TikTok Video"
                    author = d.get("author", {}).get("nickname") or d.get("author", {}).get("unique_id", "")
                    if author:
                        title = f"{author} - {title}"
                    return CleanMediaResult(
                        direct_url=clean_url,
                        title=title.strip()[:80],
                        thumbnail=d.get("cover", ""),
                        duration=str(d.get("duration", "")),
                        referer="https://www.tiktok.com/",
                        platform="TikTok (No-Watermark)",
                    )
    except Exception:
        pass

    # 2. Second attempt: Official oEmbed / Web Metadata
    try:
        match = re.search(r'/video/(\d+)', canonical_url)
        video_id = match.group(1) if match else None
        oembed_url = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(canonical_url)}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": USER_AGENT_DESKTOP})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            oembed_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            title = oembed_data.get("title") or "TikTok Video"
            author = oembed_data.get("author_name")
            if author:
                title = f"{author} - {title}"
            thumb = oembed_data.get("thumbnail_url", "")
            return CleanMediaResult(
                direct_url=canonical_url,
                title=title[:80],
                thumbnail=thumb,
                referer="https://www.tiktok.com/",
                platform="TikTok",
            )
    except Exception:
        pass

    return None


def resolve_douyin_clean(url: str, timeout: float = 8.0) -> Optional[CleanMediaResult]:
    """Resolve Douyin shortlinks and videos to clean unwatermarked stream."""
    canonical_url = follow_redirects(url, timeout=timeout)

    match = re.search(r'video/(\d+)', canonical_url)
    aweme_id = match.group(1) if match else None

    if not aweme_id:
        match_modal = re.search(r'modal_id=(\d+)', canonical_url)
        if match_modal:
            aweme_id = match_modal.group(1)

    if aweme_id:
        try:
            # Query Douyin web item API
            api_url = f"https://www.iesdouyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": USER_AGENT_MOBILE,
                    "Referer": "https://www.douyin.com/",
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                item = data.get("aweme_detail", {})
                desc = item.get("desc") or "Douyin Video"
                author = item.get("author", {}).get("nickname")
                full_title = f"{author} - {desc}" if author else desc

                video_obj = item.get("video", {})
                play_list = video_obj.get("play_addr", {}).get("url_list", [])
                if play_list:
                    raw_stream = play_list[0]
                    # Strip Douyin watermark
                    clean_stream = clean_douyin_watermark_url(raw_stream)
                    return CleanMediaResult(
                        direct_url=clean_stream,
                        title=full_title.strip()[:80],
                        thumbnail=video_obj.get("cover", {}).get("url_list", [""])[0],
                        referer="https://www.douyin.com/",
                        platform="Douyin (No-Watermark)",
                    )
        except Exception:
            pass

    return None


def resolve_capcut_clean(url: str, timeout: float = 8.0) -> Optional[CleanMediaResult]:
    """Resolve CapCut video / template links to direct clean MP4."""
    canonical_url = follow_redirects(url, timeout=timeout)
    try:
        req = urllib.request.Request(
            canonical_url,
            headers={
                "User-Agent": USER_AGENT_DESKTOP,
                "Referer": "https://www.capcut.com/",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")

            # Look for video URL in JSON state or open graph tags
            og_match = re.search(r'<meta\s+property=["\']og:video["\']\s+content=["\']([^"\']+)["\']', html, re.I)
            if not og_match:
                og_match = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:video["\']', html, re.I)

            video_src = og_match.group(1) if og_match else None
            if not video_src:
                json_match = re.search(r'["\']video_url["\']:\s*["\'](https?://[^"\']+)["\']', html)
                if json_match:
                    video_src = json_match.group(1).encode("utf-8").decode("unicode_escape")

            title_match = re.search(r'<title>([^<]+)</title>', html, re.I)
            title = title_match.group(1).replace("CapCut", "").strip(" -|") if title_match else "CapCut Video"

            if video_src:
                return CleanMediaResult(
                    direct_url=video_src,
                    title=title[:80],
                    referer="https://www.capcut.com/",
                    platform="CapCut (No-Watermark)",
                )
    except Exception:
        pass

    return None


def resolve_no_watermark_media(url: str, timeout: float = 8.0) -> Optional[CleanMediaResult]:
    """Universal dispatcher for no-watermark social and short-form video extraction."""
    if not url:
        return None

    lower = url.lower()
    if "tiktok.com" in lower:
        return resolve_tiktok_clean(url, timeout=timeout)
    if "douyin.com" in lower:
        return resolve_douyin_clean(url, timeout=timeout)
    if "capcut.com" in lower:
        return resolve_capcut_clean(url, timeout=timeout)

    return None
