"""
Spotify Studio Engine: Metadata extraction, YouTube Music search synthesis,
duration validation, and ID3 / cover art embedding.
"""

__all__ = [
    "is_spotify_url",
    "resolve_spotify_url",
    "build_music_search_query",
    "embed_cover_art_ffmpeg",
]

import re
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List
from ..core.config import BASE_DIR


def is_spotify_url(url: str) -> bool:
    """Check if URL points to a Spotify track, album, playlist, or shortlink."""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower()
    return "spotify.com" in lower or "spotify.link" in lower


def resolve_spotify_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Extract comprehensive metadata from Spotify track, album, or playlist URL.
    Uses public Spotify oEmbed and Web Embed JSON endpoints without requiring API tokens.
    """
    url = url.strip()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Follow redirects for short links (e.g. spotify.link)
    if "spotify.link" in url:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                url = r.geturl()
        except Exception:
            pass

    # Extract media type and ID from URL
    m = re.search(r"spotify\.com/(intl-[a-zA-Z0-9_-]+/)?(track|album|playlist)/([a-zA-Z0-9]+)", url)
    if not m:
        return None

    entity_type = m.group(2)
    entity_id = m.group(3)
    embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
    oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"

    thumbnail = ""
    oembed_title = ""
    try:
        req_oe = urllib.request.Request(oembed_url, headers=headers)
        with urllib.request.urlopen(req_oe, timeout=6) as resp:
            oe_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            thumbnail = oe_data.get("thumbnail_url", "")
            # Upgrade thumbnail to 640x640 high resolution
            if "ab67616d00001e02" in thumbnail:
                thumbnail = thumbnail.replace("ab67616d00001e02", "ab67616d0000b273")
            oembed_title = oe_data.get("title", "")
    except Exception:
        pass

    entity: Dict[str, Any] = {}
    try:
        req_emb = urllib.request.Request(embed_url, headers=headers)
        with urllib.request.urlopen(req_emb, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            nd_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
            if nd_match:
                d = json.loads(nd_match.group(1))
                entity = d.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
    except Exception:
        pass

    res: Dict[str, Any] = {
        "type": entity_type,
        "id": entity_id,
        "title": entity.get("title") or entity.get("name") or oembed_title or "Spotify Media",
        "artist": "",
        "thumbnail": thumbnail,
        "tracks": []
    }

    if entity_type == "track":
        artists_list = entity.get("artists", [])
        if artists_list:
            res["artist"] = ", ".join(a.get("name") for a in artists_list if a.get("name"))
        elif entity.get("subtitle"):
            res["artist"] = entity.get("subtitle")
        elif " - " in res["title"]:
            parts = res["title"].split(" - ", 1)
            res["artist"], res["title"] = parts[0].strip(), parts[1].strip()
        else:
            res["artist"] = "Various Artists"

        # Duration in milliseconds converted to seconds
        raw_dur = entity.get("duration", 0)
        dur_sec = round(raw_dur / 1000.0) if raw_dur > 1000 else raw_dur

        res["tracks"].append({
            "title": res["title"],
            "artist": res["artist"],
            "album": res["title"],
            "track_number": 1,
            "duration": dur_sec,
            "thumbnail": thumbnail
        })

    elif entity_type in ("album", "playlist"):
        res["artist"] = entity.get("subtitle") or ("Spotify" if entity_type == "playlist" else "Various Artists")
        raw_tracks = entity.get("trackList", [])
        for idx, t in enumerate(raw_tracks, 1):
            t_title = t.get("title", f"Track {idx}")
            t_artist = t.get("subtitle") or res["artist"]
            raw_dur = t.get("duration", 0)
            dur_sec = round(raw_dur / 1000.0) if raw_dur > 1000 else raw_dur

            res["tracks"].append({
                "title": t_title,
                "artist": t_artist,
                "album": res["title"],
                "track_number": idx,
                "duration": dur_sec,
                "thumbnail": thumbnail
            })

    return res


def build_music_search_query(artist: str, title: str, provider: str = "ytsearch") -> str:
    """
    Build targeted YouTube search query.
    Uses yt-dlp supported ytsearch1: prefix (ytmsearch1: is not natively supported by yt-dlp).
    """
    clean_artist = artist.replace("\"", "").strip()
    clean_title = title.replace("\"", "").strip()
    prefix = "ytsearch1:"
    return f"{prefix}{clean_artist} - {clean_title} Audio"


def embed_cover_art_ffmpeg(media_path: Path, image_url: str) -> bool:
    """Embed official Spotify cover artwork into MP3 / audio file via ffmpeg."""
    if not image_url or not media_path.exists():
        return False
    try:
        temp_img = media_path.parent / f".tmp_{media_path.stem[:12]}_cover.jpg"
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            with open(temp_img, "wb") as f:
                f.write(r.read())

        if temp_img.exists() and temp_img.stat().st_size > 1000:
            temp_out = media_path.parent / f".tmp_{media_path.name}"
            ffmpeg_bin = str(BASE_DIR / "ffmpeg.exe") if (BASE_DIR / "ffmpeg.exe").exists() else "ffmpeg"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(media_path),
                "-i", str(temp_img),
                "-map", "0:a",
                "-map", "1:0",
                "-c", "copy",
                "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
                str(temp_out)
            ]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0 and temp_out.exists() and temp_out.stat().st_size > 1000:
                media_path.unlink()
                temp_out.rename(media_path)
            if temp_out.exists():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
        if temp_img.exists():
            try:
                temp_img.unlink()
            except Exception:
                pass
        return True
    except Exception:
        return False
