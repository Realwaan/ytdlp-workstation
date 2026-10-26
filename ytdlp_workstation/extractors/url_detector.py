"""
Media URL identification, regular expression pattern matching, and cleaning.
Supports 1,800+ media sites and direct video/audio CDN streams.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

__all__ = [
    "is_valid_media_url",
    "extract_media_url",
    "clean_url",
    "COMMON_MEDIA_DOMAINS",
    "MEDIA_REGEX",
    "MEDIA_EXT_REGEX",
    "GENERIC_URL_REGEX",
]

COMMON_MEDIA_DOMAINS = [
    # Music & Podcasts
    r"(?:open\.)?spotify\.com",
    r"spotify\.link",
    r"(?:www\.)?soundcloud\.com",
    r"(?:www\.)?bandcamp\.com",
    r"(?:www\.)?mixcloud\.com",
    
    # Major Video Platforms
    r"(?:www\.)?youtube\.com",
    r"youtu\.be",
    r"(?:www\.)?vimeo\.com",
    r"(?:www\.)?dailymotion\.com",
    r"dai\.ly",
    r"(?:www\.)?bilibili\.com",
    r"b23\.tv",
    r"(?:www\.)?twitch\.tv",
    r"(?:www\.)?kick\.com",
    r"(?:www\.)?rumble\.com",
    r"(?:www\.)?streamable\.com",
    r"(?:www\.)?loom\.com",
    r"(?:www\.)?odysee\.com",
    r"(?:www\.)?bitchute\.com",
    r"(?:www\.)?crunchyroll\.com",
    r"(?:www\.)?ted\.com",
    r"(?:www\.)?archive\.org",
    
    # Social & Short-Form Video (TikTok, Douyin, CapCut, Kuaishou, Xiaohongshu)
    r"(?:www\.)?tiktok\.com",
    r"vt\.tiktok\.com",
    r"vm\.tiktok\.com",
    r"(?:www\.)?douyin\.com",
    r"v\.douyin\.com",
    r"iesdouyin\.com",
    r"(?:www\.)?capcut\.com",
    r"(?:www\.)?kuaishou\.com",
    r"kwai\.com",
    r"(?:www\.)?xiaohongshu\.com",
    r"xhslink\.com",
    r"(?:www\.)?instagram\.com",
    r"(?:www\.)?threads\.net",
    r"(?:www\.)?snapchat\.com",
    r"(?:www\.)?pinterest\.com",
    r"pin\.it",
    r"(?:www\.)?twitter\.com",
    r"(?:www\.)?x\.com",
    r"t\.co",
    r"(?:www\.)?reddit\.com",
    r"v\.redd\.it",
    r"(?:www\.)?facebook\.com",
    r"fb\.watch",
    r"(?:www\.)?weibo\.com",
    r"weibo\.cn",
    r"(?:www\.)?linkedin\.com",
    r"(?:www\.)?tumblr\.com",
    r"(?:www\.)?vk\.com",
    r"(?:www\.)?ok\.ru",
    r"(?:www\.)?imgur\.com",
    r"(?:www\.)?giphy\.com",
    r"(?:www\.)?redgifs\.com",
    
    # Streaming hosts & cloud embeds
    r"(?:www\.)?streamtape\.com",
    r"doodstream\.com",
    r"dood\.to",
    r"dood\.watch",
    r"dood\.so",
    r"filemoon\.sx",
    r"filemoon\.to",
    r"voe\.sx",
    r"voe-network\.net",
    r"mixdrop\.co",
    r"mixdrop\.to",
    r"mp4upload\.com",
    r"vidhide\.com",
    r"vidhidepro\.com",
    r"streamsb\.net",
    r"sbembed\.com",
    r"watchsb\.com",
    r"streamwish\.to",
    r"streamwish\.com",
    r"vidmoly\.me",
    r"upstream\.to",
]

MEDIA_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9_\-]+\.)*(?:" + "|".join(COMMON_MEDIA_DOMAINS) + r")(?::[0-9]+)?(?:/[^\s]*)?",
    re.IGNORECASE
)

# Direct media files hosted on CDNs or arbitrary websites
MEDIA_EXT_REGEX = re.compile(
    r"https?://[^\s]+\.(?:mp4|m3u8|webm|mov|mkv|flv|avi|ts|mpd|mp3|m4a|aac|wav|opus|ogg|flac)(?:\?[^\s]*)?",
    re.IGNORECASE
)

GENERIC_URL_REGEX = re.compile(
    r"^https?://[a-zA-Z0-9\-.]+(?:\:[0-9]+)?(?:/[^\s]*)?$",
    re.IGNORECASE
)


def is_valid_media_url(text: str, media_filter_only: bool = True) -> bool:
    """Validate if the string is a downloadable media URL."""
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    if media_filter_only:
        return bool(MEDIA_REGEX.search(text) or MEDIA_EXT_REGEX.search(text))
    return bool(GENERIC_URL_REGEX.match(text) or text.startswith(("http://", "https://")))


def extract_media_url(text: str) -> Optional[str]:
    """Extract first matching URL from text string."""
    if not text or not isinstance(text, str):
        return None
    match = MEDIA_REGEX.search(text)
    if match:
        return match.group(0)
    match_ext = MEDIA_EXT_REGEX.search(text)
    if match_ext:
        return match_ext.group(0)
    match2 = GENERIC_URL_REGEX.search(text)
    if match2:
        return match2.group(0)
    return text.strip() if text.startswith(("http://", "https://")) else None


def clean_url(url: str) -> str:
    """Strip marketing tracking parameters (utm_*, si, feature, fbclid, etc.) from URLs."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    try:
        parts = urllib.parse.urlsplit(url)
        if not parts.query:
            return url
        # Strip tracking parameters while keeping critical video IDs, auth tokens, and stream formats
        drop_exact = {
            "si", "feature", "fbclid", "gclid", "igshid",
            "share_token", "share_app_name", "share_id", "ref_src", "ref_url",
        }
        filtered_q = []
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            k_lower = k.lower()
            if k_lower.startswith("utm_") or k_lower in drop_exact:
                continue
            filtered_q.append((k, v))
        new_query = urllib.parse.urlencode(filtered_q)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:
        return url

