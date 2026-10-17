"""
Intelligent Video CDN and Cloud Streaming Referer Engine.
Automatically matches cloud embed streams (.m3u8 / .mpd) with their required parent referer
to eliminate HTTP 403 Forbidden hotlink blocks.
"""

from typing import Optional

CDN_TO_REFERER_MAP = {
    # VidEasy / Peakpine / Moon servers (used by Movy, Cinejoy, etc.)
    "zenoak.top": "https://movy.sx/",
    "peakpine.top": "https://movy.sx/",
    "videasy.net": "https://movy.sx/",
    # MegaCloud / Rabbitstream (used by Aniwave, Zoro, HiAnime, 1Movies)
    "megacloud.tv": "https://megacloud.tv/",
    "rabbitstream.net": "https://rabbitstream.net/",
    "dokicloud.one": "https://dokicloud.one/",
    # VidSrc
    "vidsrc.to": "https://vidsrc.to/",
    "vidsrc.me": "https://vidsrc.me/",
    "vidsrc.xyz": "https://vidsrc.xyz/",
    "vidsrc.stream": "https://vidsrc.stream/",
    # Streamtape
    "streamtape.com": "https://streamtape.com/",
    # Mixdrop
    "mixdrop.co": "https://mixdrop.co/",
    "mixdrop.to": "https://mixdrop.to/",
    # DoodStream
    "doodstream.com": "https://doodstream.com/",
    "dood.to": "https://dood.to/",
    # Filemoon
    "filemoon.sx": "https://filemoon.sx/",
    "filemoon.to": "https://filemoon.to/",
    # Streamwish
    "streamwish.to": "https://streamwish.to/",
    # VidMoly
    "vidmoly.to": "https://vidmoly.to/",
    # Voe
    "voe.sx": "https://voe.sx/",
    # Upstream
    "upstream.to": "https://upstream.to/",
    # 2Embed / SuperEmbed
    "2embed.cc": "https://2embed.cc/",
    "superembed.stream": "https://superembed.stream/",
    # Cinejoy
    "cinejoy.pk": "https://cinejoy.pk/",
    # PopcornMovies
    "popcornmovies.ac": "https://popcornmovies.ac/",
    # BingeBox
    "bingebox.ac": "https://bingebox.ac/",
}

KNOWN_STREAMING_DOMAINS = {
    "movy.sx": "https://movy.sx/",
    "cinejoy.pk": "https://cinejoy.pk/",
    "bingebox.ac": "https://bingebox.ac/",
    "popcornmovies.ac": "https://popcornmovies.ac/",
    "vidsrc.to": "https://vidsrc.to/",
    "vidsrc.me": "https://vidsrc.me/",
    "soap2day.to": "https://soap2day.to/",
    "lookmovie2.to": "https://lookmovie2.to/",
    "flixtor.to": "https://flixtor.to/",
    "fmovies.to": "https://fmovies.to/",
}


def auto_detect_referer(url: str, last_seen_website: Optional[str] = None, default_referer: str = "https://movy.sx/") -> Optional[str]:
    """
    Intelligently deduce the required Referer for cloud video servers and m3u8 streams
    so the user never has to manually hunt or type referer URLs.
    """
    if not url:
        return None
    url_lower = url.lower()

    # If it's a mainstream platform (YouTube, Twitch, Instagram, Twitter, etc.), no referer needed
    if any(ign in url_lower for ign in (
        "youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "tiktok.com",
        "instagram.com", "twitter.com", "x.com", "reddit.com", "spotify.com"
    )):
        return None

    active_site = last_seen_website or default_referer

    # 1. Direct CDN / Cloud Server pattern matching
    for cdn_domain, parent_referer in CDN_TO_REFERER_MAP.items():
        if cdn_domain in url_lower:
            if any(k in url_lower for k in ("zenoak.top", "peakpine.top", "videasy")):
                return active_site
            return parent_referer

    # 2. Check if URL itself matches a known streaming domain
    for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
        if s_domain in url_lower:
            return s_url

    # 3. For any cloud HLS (.m3u8), DASH (.mpd) or video stream chunk, attach active streaming site
    if any(ext in url_lower for ext in (".m3u8", ".mpd", "/vd/", "/hls/", "/stream/", "/frag")):
        return active_site

    return None
