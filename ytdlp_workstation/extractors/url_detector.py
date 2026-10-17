"""
Media URL identification, regular expression pattern matching, and cleaning.
Supports 1,750+ media sites and direct video/audio CDN streams.
"""

__all__ = [
    "is_valid_media_url",
    "extract_media_url",
    "clean_url",
    "COMMON_MEDIA_DOMAINS",
    "MEDIA_REGEX",
    "MEDIA_EXT_REGEX",
    "GENERIC_URL_REGEX",
]

import re
from typing import Optional

COMMON_MEDIA_DOMAINS = [
    r"(?:open\.)?spotify\.com",
    r"spotify\.link",
    r"(?:www\.)?youtube\.com",
    r"youtu\.be",
    r"(?:www\.)?tiktok\.com",
    r"(?:www\.)?instagram\.com",
    r"(?:www\.)?twitter\.com",
    r"(?:www\.)?x\.com",
    r"(?:www\.)?reddit\.com",
    r"(?:www\.)?twitch\.tv",
    r"(?:www\.)?facebook\.com",
    r"fb\.watch",
    r"(?:www\.)?bilibili\.com",
    r"(?:www\.)?vimeo\.com",
    r"(?:www\.)?soundcloud\.com",
    r"(?:www\.)?dailymotion\.com",
    r"(?:www\.)?pinterest\.com",
    r"pin\.it",
    r"(?:www\.)?threads\.net",
    r"(?:www\.)?rumble\.com",
    r"(?:www\.)?streamable\.com",
    r"(?:www\.)?kick\.com",
    r"(?:www\.)?loom\.com",
    r"(?:www\.)?vk\.com",
    r"(?:www\.)?ok\.ru",
    r"(?:www\.)?bandcamp\.com",
    r"(?:www\.)?mixcloud\.com",
    r"(?:www\.)?crunchyroll\.com",
    r"(?:www\.)?odysee\.com",
    r"(?:www\.)?bitchute\.com",
    r"(?:www\.)?archive\.org",
    r"(?:www\.)?snapchat\.com",
    r"(?:www\.)?tumblr\.com",
    r"(?:www\.)?ted\.com",
    r"(?:www\.)?linkedin\.com",
    r"(?:www\.)?imgur\.com",
    r"(?:www\.)?giphy\.com"
]

MEDIA_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9_\-]+\.)*(?:" + "|".join(COMMON_MEDIA_DOMAINS) + r")/[^\s]+",
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
    """Strip marketing tracking parameters (utm_*, si, feature) from URLs."""
    if not url:
        return ""
    url = url.strip()
    url = re.sub(r'([?&])(utm_[^&=]+|si|feature)=[^&#]*', '', url)
    url = url.rstrip('?&')
    return url
