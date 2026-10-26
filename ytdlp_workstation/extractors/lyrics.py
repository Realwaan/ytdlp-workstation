"""
Synchronized lyrics (.lrc) fetching and parsing via LRCLIB public API.
Fetches time-tagged synchronized lyrics and plain lyrics for music tracks.
"""

__all__ = [
    "fetch_lyrics",
    "search_lyrics",
    "save_lrc_file",
    "fetch_and_save_lyrics_for_media",
]

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List

LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
USER_AGENT = "yt-dlp-workstation/2.0 (https://github.com/Realwaan/ytdlp-workstation)"


def fetch_lyrics(
    track_name: str,
    artist_name: str,
    album_name: Optional[str] = None,
    duration: Optional[int] = None,
    timeout: float = 6.0,
) -> Optional[Dict[str, Any]]:
    """
    Fetch lyrics for a track using LRCLIB's exact match endpoint.
    Falls back to search query if exact match is not found (404/empty).
    """
    if not track_name or not artist_name:
        return None

    clean_track = track_name.strip()
    clean_artist = artist_name.strip()

    params: Dict[str, str] = {
        "track_name": clean_track,
        "artist_name": clean_artist,
    }
    if album_name:
        params["album_name"] = album_name.strip()
    if duration and duration > 0:
        params["duration"] = str(int(duration))

    query_str = urllib.parse.urlencode(params)
    target_url = f"{LRCLIB_GET_URL}?{query_str}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
                return {
                    "id": data.get("id"),
                    "track_name": data.get("trackName") or clean_track,
                    "artist_name": data.get("artistName") or clean_artist,
                    "album_name": data.get("albumName", ""),
                    "duration": data.get("duration", 0),
                    "instrumental": bool(data.get("instrumental", False)),
                    "plain_lyrics": data.get("plainLyrics") or "",
                    "synced_lyrics": data.get("syncedLyrics") or "",
                }
    except Exception:
        # Fallback to search query
        pass

    return search_lyrics(f"{clean_artist} {clean_track}", timeout=timeout)


def search_lyrics(query: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """
    Search for lyrics by general free-text query (e.g. 'Artist Title').
    Returns the first matching item with valid lyrics.
    """
    if not query or not query.strip():
        return None

    params = {"q": query.strip()}
    query_str = urllib.parse.urlencode(params)
    target_url = f"{LRCLIB_SEARCH_URL}?{query_str}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            results = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(results, list):
                # Prioritize items with syncedLyrics
                for item in results:
                    if item.get("syncedLyrics"):
                        return {
                            "id": item.get("id"),
                            "track_name": item.get("trackName", ""),
                            "artist_name": item.get("artistName", ""),
                            "album_name": item.get("albumName", ""),
                            "duration": item.get("duration", 0),
                            "instrumental": bool(item.get("instrumental", False)),
                            "plain_lyrics": item.get("plainLyrics") or "",
                            "synced_lyrics": item.get("syncedLyrics") or "",
                        }
                for item in results:
                    if item.get("plainLyrics"):
                        return {
                            "id": item.get("id"),
                            "track_name": item.get("trackName", ""),
                            "artist_name": item.get("artistName", ""),
                            "album_name": item.get("albumName", ""),
                            "duration": item.get("duration", 0),
                            "instrumental": bool(item.get("instrumental", False)),
                            "plain_lyrics": item.get("plainLyrics") or "",
                            "synced_lyrics": item.get("syncedLyrics") or "",
                        }
    except Exception:
        pass

    return None


def save_lrc_file(media_file: Path, synced_lyrics: str) -> Optional[Path]:
    """
    Save time-tagged synced lyrics as an .lrc file matching media_file stem.
    E.g. for 'Song.mp3' -> 'Song.lrc' in the same folder.
    """
    if not synced_lyrics or not synced_lyrics.strip():
        return None

    lrc_path = media_file.with_suffix(".lrc")
    try:
        lrc_path.write_text(synced_lyrics.strip() + "\n", encoding="utf-8")
        return lrc_path
    except OSError:
        return None


def fetch_and_save_lyrics_for_media(
    media_path: Path,
    artist: str,
    track: str,
    album: Optional[str] = None,
    duration: Optional[int] = None,
) -> Optional[Path]:
    """
    Fetch lyrics for an audio track and save alongside as an .lrc file.
    """
    if not media_path.exists():
        return None

    lyrics_data = fetch_lyrics(track_name=track, artist_name=artist, album_name=album, duration=duration)
    if not lyrics_data:
        return None

    synced = lyrics_data.get("synced_lyrics")
    plain = lyrics_data.get("plain_lyrics")
    content_to_save = synced if synced else plain
    if content_to_save:
        return save_lrc_file(media_path, content_to_save)
    return None
