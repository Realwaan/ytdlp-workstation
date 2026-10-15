"""
YT-DLP Supercharged Terminal & Automated Downloader
===================================================
Features:
- Automated clipboard sentinel (Zero-click or interactive quality choice)
- Interactive Video Quality Picker (4K, 1440p, 1080p, 720p, 480p, 360p, MP3, M4A, FLAC, OPUS, WAV, MKV, or exact format -F)
- Browser cookie integration (Bypass YouTube age restrictions, Twitter/Instagram login walls)
- Video trimming & clip extractor (Download only specific time segments: trim 01:15-02:30 <URL>)
- Selective playlist downloading (Download only specific tracks: items 1-5 <URL>)
- Multi-language subtitles auto-embedding (English, Auto, All languages)
- Bandwidth speed limiter (limit 5M / limit off)
- Native Windows 10/11 Toast Notifications on completion
- Dedicated downloads queue & non-blocking terminal input
- Node.js runtime acceleration for throttle-free extraction
"""

import sys
import os
import re
import json
import time
import base64
import shutil
import threading
import subprocess
import collections
import ctypes
import urllib.parse
import urllib.request
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent

def _detect_portable_mode() -> bool:
    try:
        if (MODULE_DIR / "setup.bat").exists() or (MODULE_DIR / "run.bat").exists():
            test_file = MODULE_DIR / ".write_test"
            test_file.touch()
            test_file.unlink()
            return True
    except (PermissionError, OSError):
        pass
    return False

IS_PORTABLE = _detect_portable_mode()

if IS_PORTABLE:
    BASE_DIR = MODULE_DIR
    USER_DATA_DIR = MODULE_DIR
    DEFAULT_DOWNLOAD_DIR = MODULE_DIR / "downloads"
else:
    USER_DATA_DIR = Path.home() / ".ytdlp-workstation"
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR = USER_DATA_DIR
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YT-DLP"

# Add directories to system PATH so ffmpeg and yt-dlp are always found globally
for _p in [str(BASE_DIR), str(MODULE_DIR)]:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# Force UTF-8 encoding on standard streams to avoid Windows charmap errors
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Windows console and sounds
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# External dependencies
try:
    import colorama
    from colorama import Fore, Style, Back
    colorama.init(autoreset=True)
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Style = Back = DummyColor()

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


def get_clipboard_text() -> str:
    """Universal clipboard reader: uses pyperclip if available, else native Windows ctypes, else powershell"""
    if HAS_PYPERCLIP:
        try:
            val = pyperclip.paste()
            if val and isinstance(val, str):
                return val
        except Exception:
            pass
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_bool
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_bool
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_bool

            if user32.OpenClipboard(None):
                try:
                    CF_UNICODETEXT = 13
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        ptr = kernel32.GlobalLock(handle)
                        if ptr:
                            try:
                                return ctypes.c_wchar_p(ptr).value or ""
                            finally:
                                kernel32.GlobalUnlock(handle)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass
        try:
            res = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                text=True, stderr=subprocess.DEVNULL, timeout=1
            )
            return res.strip()
        except Exception:
            pass
    return ""


def set_clipboard_text(text: str) -> bool:
    """Universal clipboard writer: uses pyperclip if available, else native Windows ctypes"""
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            GMEM_MOVEABLE = 0x0002
            CF_UNICODETEXT = 13
            if user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                    data = text.encode("utf-16-le") + b"\x00\x00"
                    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if h_mem:
                        ptr = kernel32.GlobalLock(h_mem)
                        if ptr:
                            try:
                                ctypes.memmove(ptr, data, len(data))
                            finally:
                                kernel32.GlobalUnlock(h_mem)
                            user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                            return True
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass
    return False

# Paths configuration
YTDLP_EXE = BASE_DIR / "yt-dlp.exe"
FFMPEG_EXE = BASE_DIR / "ffmpeg.exe"
ARIA2C_EXE = BASE_DIR / "aria2c.exe"
CONFIG_FILE = USER_DATA_DIR / "config.json"
HISTORY_FILE = USER_DATA_DIR / "history.json"

# Ensure download dir exists
DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Presets definition with full video & audio spectrum
PRESETS = {
    1: {
        "name": "Best Available (Up to 4K / 8K MP4)",
        "desc": "Maximum available video resolution merged with best audio",
        "format": "bv*+ba/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-thumbnail", "--embed-metadata"]
    },
    2: {
        "name": "2K Quad HD 1440p (MP4)",
        "desc": "1440p maximum resolution merged with best audio",
        "format": "bv*[height<=1440]+ba/b[height<=1440]/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-thumbnail", "--embed-metadata"]
    },
    3: {
        "name": "Full HD 1080p (MP4)",
        "desc": "1080p maximum resolution (recommended for quality & size)",
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-thumbnail", "--embed-metadata"]
    },
    4: {
        "name": "HD 720p (MP4)",
        "desc": "720p maximum resolution (fast download, great for sharing)",
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-metadata"]
    },
    5: {
        "name": "Standard SD 480p (MP4)",
        "desc": "480p maximum resolution (low bandwidth / small file size)",
        "format": "bv*[height<=480]+ba/b[height<=480]/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-metadata"]
    },
    6: {
        "name": "Low 360p (MP4)",
        "desc": "360p maximum resolution (data saver / very small file size)",
        "format": "bv*[height<=360]+ba/b[height<=360]/b",
        "merge_format": "mp4",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--embed-metadata"]
    },
    7: {
        "name": "Audio Only - MP3 (320kbps High Quality)",
        "desc": "Extracts audio, converts to MP3, embeds album art & ID3 metadata",
        "format": "ba/b",
        "merge_format": None,
        "extract_audio": True,
        "audio_format": "mp3",
        "extra_args": ["--audio-quality", "0", "--embed-thumbnail", "--embed-metadata"]
    },
    8: {
        "name": "Audio Only - M4A (Original AAC - Instant)",
        "desc": "Extracts original AAC audio without re-encoding",
        "format": "ba[ext=m4a]/ba/b",
        "merge_format": None,
        "extract_audio": True,
        "audio_format": "m4a",
        "extra_args": ["--embed-metadata"]
    },
    9: {
        "name": "Audio Only - FLAC (Lossless Studio Quality)",
        "desc": "Lossless CD/Studio quality audio with embedded metadata & art",
        "format": "ba/b",
        "merge_format": None,
        "extract_audio": True,
        "audio_format": "flac",
        "extra_args": ["--embed-thumbnail", "--embed-metadata"]
    },
    10: {
        "name": "Audio Only - OPUS (Next-Gen High Efficiency)",
        "desc": "Modern high-fidelity audio at low file size",
        "format": "ba/b",
        "merge_format": None,
        "extract_audio": True,
        "audio_format": "opus",
        "extra_args": ["--embed-metadata"]
    },
    11: {
        "name": "Audio Only - WAV (Uncompressed Raw PCM)",
        "desc": "Uncompressed raw waveform audio for video editors and DAWs",
        "format": "ba/b",
        "merge_format": None,
        "extract_audio": True,
        "audio_format": "wav",
        "extra_args": ["--embed-metadata"]
    },
    12: {
        "name": "Universal MKV (All Subtitles & Audio Tracks)",
        "desc": "Best video & audio, preserves all subtitle streams in MKV container",
        "format": "bv*+ba/b",
        "merge_format": "mkv",
        "extract_audio": False,
        "audio_format": None,
        "extra_args": ["--all-subs", "--embed-subs", "--embed-metadata"]
    }
}

# Known media domain patterns (1,750+ sites supported by yt-dlp)
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

# Direct media file extensions on ANY website or CDN
MEDIA_EXT_REGEX = re.compile(
    r"https?://[^\s]+\.(?:mp4|m3u8|webm|mov|mkv|flv|avi|ts|mpd|mp3|m4a|aac|wav|opus|ogg|flac)(?:\?[^\s]*)?",
    re.IGNORECASE
)

GENERIC_URL_REGEX = re.compile(
    r"^https?://[a-zA-Z0-9\-.]+(?:\:[0-9]+)?(?:/[^\s]*)?$",
    re.IGNORECASE
)

# Intelligent Video CDN to Streaming Site Auto-Referer Engine
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


def auto_detect_referer(url: str) -> str:
    """
    Intelligently deduce the required Referer for cloud video servers and m3u8 streams
    so the user NEVER has to manually type or choose referer numbers.
    """
    if not url:
        return None
    url_lower = url.lower()

    # If it's a mainstream platform (YouTube, Twitch, etc.), no referer needed
    if any(ign in url_lower for ign in ("youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "tiktok.com", "instagram.com", "twitter.com", "x.com")):
        return None

    # 1. Direct CDN / Cloud Server pattern matching
    for cdn_domain, parent_referer in CDN_TO_REFERER_MAP.items():
        if cdn_domain in url_lower:
            if any(k in url_lower for k in ("zenoak.top", "peakpine.top", "videasy")):
                try:
                    return getattr(STATE, "last_seen_website", None) or STATE.config.get("default_stream_referer", "https://movy.sx/")
                except Exception:
                    return parent_referer
            return parent_referer

    # 2. Check if URL itself matches a known streaming domain
    for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
        if s_domain in url_lower:
            return s_url

    # 3. For any cloud HLS (.m3u8), DASH (.mpd) or video stream, attach active streaming site
    if any(ext in url_lower for ext in (".m3u8", ".mpd", "/vd/", "/hls/", "/stream/", "/frag")):
        try:
            return getattr(STATE, "last_seen_website", None) or STATE.config.get("default_stream_referer", "https://movy.sx/")
        except Exception:
            return "https://movy.sx/"

    return None


class AppState:
    def __init__(self):
        self.config = self.load_config()
        self.history = self.load_history()
        self.seen_clipboard = set()
        self.download_queue = collections.deque()
        self.pending_prompt_url = None
        self.pending_prompt_ref = None
        self.is_downloading = False
        self.current_job = None
        self.lock = threading.Lock()
        self.stop_requested = False
        self.update_available = None
        self.last_seen_website = self.config.get("default_stream_referer", "https://movy.sx/")

        # Pre-populate seen_clipboard from history
        for item in self.history:
            if "url" in item:
                self.seen_clipboard.add(self.clean_url(item["url"]))

    def enqueue_job(self, job: dict):
        """Thread-safe enqueue with intelligent referer auto-detection"""
        if not job.get("referer"):
            auto_ref = auto_detect_referer(job.get("url", ""))
            if auto_ref:
                job["referer"] = auto_ref
        with self.lock:
            self.download_queue.append(job)
        return job

    def load_config(self):
        defaults = {
            "clipboard_mode": "auto",  # 'auto', 'prompt', 'off'
            "ask_quality_each_time": True,  # Allows user to pick quality choices!
            "default_stream_referer": "https://movy.sx/",
            "preset": 1,
            "download_dir": str(DEFAULT_DOWNLOAD_DIR),
            "sound_effects": True,
            "desktop_notifications": True,
            "browser_cookies": "none",  # 'none', 'chrome', 'edge', 'firefox', 'brave', 'opera'
            "subtitles_mode": "off",  # 'off', 'en', 'all'
            "speed_limit": "none",  # 'none', '5M', '10M', etc.
            "sponsorblock": False,
            "media_filter_only": True
        }
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    defaults.update(data)
            except Exception:
                pass
        return defaults

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"{Fore.RED}[!] Could not save config: {e}")

    def load_history(self):
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_history(self):
        try:
            trimmed = self.history[-200:]
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, indent=2)
        except Exception as e:
            print(f"{Fore.RED}[!] Could not save history: {e}")

    def add_history_entry(self, entry):
        with self.lock:
            self.history.append(entry)
            self.save_history()

    @staticmethod
    def clean_url(url: str) -> str:
        url = url.strip()
        url = re.sub(r'([?&])(utm_[^&=]+|si|feature)=[^&#]*', '', url)
        url = url.rstrip('?&')
        return url


STATE = AppState()


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filesystem usage"""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip() or "Untitled"


def cleanup_orphaned_fragments(directory: Path = None):
    """Clean up dangling *-Frag* files so they don't corrupt subsequent resumes or clutter disk"""
    try:
        target_dir = Path(directory or STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        if target_dir.exists():
            for f in target_dir.glob("*-Frag*"):
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


def get_free_disk_space_gb(directory: Path = None) -> float:
    """Return free disk space in Gigabytes for the download directory"""
    target = Path(directory or STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    try:
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(target)
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return -1.0


def is_spotify_url(url: str) -> bool:
    """Check if URL points to a Spotify track, album, playlist, or shortlink"""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower()
    return "spotify.com" in lower or "spotify.link" in lower


def resolve_spotify_url(url: str) -> dict:
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

    # 1. Fetch oEmbed for fallback metadata and high-res cover artwork
    thumbnail = ""
    oembed_title = ""
    try:
        req_oe = urllib.request.Request(oembed_url, headers=headers)
        with urllib.request.urlopen(req_oe, timeout=6) as resp:
            oe_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            thumbnail = oe_data.get("thumbnail_url", "")
            if "ab67616d00001e02" in thumbnail:
                thumbnail = thumbnail.replace("ab67616d00001e02", "ab67616d0000b273")
            oembed_title = oe_data.get("title", "")
    except Exception:
        pass

    # 2. Fetch Embed HTML to parse __NEXT_DATA__
    entity = {}
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

    res = {
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

        res["tracks"].append({
            "title": res["title"],
            "artist": res["artist"],
            "album": res["title"],
            "track_number": 1,
            "duration": entity.get("duration", 0),
            "thumbnail": thumbnail
        })

    elif entity_type in ("album", "playlist"):
        res["artist"] = entity.get("subtitle") or ("Spotify" if entity_type == "playlist" else "Various Artists")
        raw_tracks = entity.get("trackList", [])
        for idx, t in enumerate(raw_tracks, 1):
            t_title = t.get("title", f"Track {idx}")
            t_artist = t.get("subtitle") or res["artist"]
            res["tracks"].append({
                "title": t_title,
                "artist": t_artist,
                "album": res["title"],
                "track_number": idx,
                "duration": t.get("duration", 0),
                "thumbnail": thumbnail
            })

    return res


def embed_cover_art_ffmpeg(mp3_path: Path, image_url: str):
    """Embed official Spotify cover artwork into MP3 file via ffmpeg"""
    try:
        temp_img = mp3_path.parent / f".tmp_{mp3_path.stem[:15]}_cover.jpg"
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            with open(temp_img, "wb") as f:
                f.write(r.read())

        if temp_img.exists() and temp_img.stat().st_size > 1000:
            temp_out = mp3_path.parent / f".tmp_{mp3_path.name}"
            ffmpeg_bin = str(BASE_DIR / "ffmpeg.exe") if (BASE_DIR / "ffmpeg.exe").exists() else "ffmpeg"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(mp3_path),
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
                mp3_path.unlink()
                temp_out.rename(mp3_path)
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
    except Exception:
        pass


def enqueue_spotify_download(url: str):
    """
    Resolve Spotify track, album, or playlist and queue for high-fidelity 320kbps download.
    """
    print(f"\n{Fore.CYAN}[⚡] Resolving Spotify metadata...{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}{url}{Style.RESET_ALL}")
    data = resolve_spotify_url(url)
    if not data or not data.get("tracks"):
        print(f"{Fore.RED}[!] Could not resolve Spotify media from URL.{Style.RESET_ALL}\n")
        return False

    ent_type = data["type"].capitalize()
    ent_title = data["title"]
    ent_artist = data["artist"]
    tracks = data["tracks"]
    total = len(tracks)
    thumbnail = data.get("thumbnail", "")

    download_dir = Path(STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    # Multi-track albums & playlists save in a dedicated subfolder
    target_folder = download_dir
    if data["type"] in ("album", "playlist") and total > 1:
        folder_label = f"{sanitize_filename(ent_artist)} - {sanitize_filename(ent_title)}" if ent_artist and data["type"] == "album" else sanitize_filename(ent_title)
        target_folder = download_dir / folder_label
        target_folder.mkdir(parents=True, exist_ok=True)

    print(f"{Fore.GREEN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Style.BRIGHT}{Fore.WHITE}🎵 SPOTIFY STUDIO ENGINE{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Type   :{Style.RESET_ALL} {Fore.YELLOW}{ent_type}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Title  :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{ent_title}{Style.RESET_ALL}")
    if ent_artist:
        print(f"{Fore.GREEN}│ {Fore.WHITE}Artist :{Style.RESET_ALL} {Fore.LIGHTCYAN_EX}{ent_artist}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Tracks :{Style.RESET_ALL} {Fore.WHITE}{total} track(s){Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Quality:{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}High-Fidelity 320kbps MP3 + ID3 Tags + Album Art{Style.RESET_ALL}")
    print(f"{Fore.GREEN}│ {Fore.WHITE}Save In:{Style.RESET_ALL} {Fore.CYAN}{target_folder}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}\n")

    with STATE.lock:
        for idx, t in enumerate(tracks, 1):
            t_title = t["title"]
            t_artist = t["artist"]
            t_album = t.get("album") or ent_title

            search_query = f"ytsearch1:{t_artist} - {t_title} Official Audio"

            if total == 1:
                out_tmpl = str(target_folder / f"{sanitize_filename(t_artist)} - {sanitize_filename(t_title)}.%(ext)s")
                disp = f"{t_artist} - {t_title}"
            else:
                out_tmpl = str(target_folder / f"{idx:02d} - {sanitize_filename(t_title)}.%(ext)s")
                disp = f"[{idx:02d}/{total:02d}] {t_artist} - {t_title}"

            job = {
                "url": search_query,
                "display_title": disp,
                "preset_override": 7,  # MP3 320k
                "force_audio": True,
                "needs_quality_prompt": False,
                "target_dir": target_folder,
                "custom_output_template": out_tmpl,
                "extra_metadata": {
                    "artist": t_artist,
                    "title": t_title,
                    "album": t_album,
                    "track_number": str(idx),
                    "track_count": str(total)
                },
                "spotify_thumbnail": thumbnail
            }
            STATE.download_queue.append(job)

    if total > 1:
        print(f"{Fore.GREEN}[✓] Queued {total} tracks into folder:{Style.RESET_ALL} {Fore.CYAN}{target_folder.name}{Style.RESET_ALL}\n")
    else:
        print(f"{Fore.GREEN}[✓] Queued track for 320kbps studio download!{Style.RESET_ALL}\n")
    return True


def play_sound(sound_type="notice"):
    """Play audio feedback"""
    if not STATE.config.get("sound_effects", True) or not HAS_WINSOUND:
        return
    try:
        if sound_type == "notice":
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif sound_type == "success":
            winsound.MessageBeep(winsound.MB_OK)
        elif sound_type == "error":
            winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass


def send_windows_toast(title: str, message: str):
    """Send native Windows 10/11 Desktop Notification banner in background"""
    if not STATE.config.get("desktop_notifications", True) or os.name != "nt":
        return

    def _toast():
        safe_title = title.replace("'", "").replace('"', "").replace("<", "").replace(">", "")
        safe_msg = message.replace("'", "").replace('"', "").replace("<", "").replace(">", "")
        script = f"""
$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::new()
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{safe_title}</text><text>{safe_msg}</text></binding></visual></toast>')
$toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)
"""
        try:
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
        except Exception:
            pass

    threading.Thread(target=_toast, daemon=True).start()


def check_for_updates_background():
    """Background check for newer yt-dlp release"""
    def _check():
        try:
            cmd = [str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"), "--version"]
            cur_ver = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
            # Query GitHub release
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
                latest_ver = data.get("tag_name", "").lstrip("v")
                if latest_ver and latest_ver != cur_ver:
                    STATE.update_available = latest_ver
        except Exception:
            pass

    threading.Thread(target=_check, daemon=True).start()


def is_valid_media_url(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    text = text.strip()
    if STATE.config.get("media_filter_only", True):
        return bool(MEDIA_REGEX.search(text) or MEDIA_EXT_REGEX.search(text))
    else:
        return bool(GENERIC_URL_REGEX.match(text) or text.startswith(("http://", "https://")))


def extract_media_url(text: str) -> str:
    match = MEDIA_REGEX.search(text)
    if match:
        return match.group(0)
    match_ext = MEDIA_EXT_REGEX.search(text)
    if match_ext:
        return match_ext.group(0)
    match2 = GENERIC_URL_REGEX.search(text)
    if match2:
        return match2.group(0)
    return text.strip()


def print_banner():
    """Print the cyber-styled terminal banner and status dashboard"""
    os.system("cls" if os.name == "nt" else "clear")
    preset_info = PRESETS.get(STATE.config.get("preset", 1), PRESETS[1])
    clip_mode = STATE.config.get("clipboard_mode", "auto").upper()

    if clip_mode == "AUTO":
        clip_badge = f"{Back.GREEN}{Fore.BLACK} ACTIVE (AUTO-DETECT) {Style.RESET_ALL}"
    elif clip_mode == "PROMPT":
        clip_badge = f"{Back.YELLOW}{Fore.BLACK} ACTIVE (ASK FIRST) {Style.RESET_ALL}"
    else:
        clip_badge = f"{Back.RED}{Fore.WHITE} DISABLED {Style.RESET_ALL}"

    ask_quality = STATE.config.get("ask_quality_each_time", True)
    if ask_quality:
        quality_badge = f"{Back.MAGENTA}{Fore.WHITE} PICK ON DOWNLOAD {Style.RESET_ALL} {Fore.LIGHTMAGENTA_EX}(Single-key choices per link){Style.RESET_ALL}"
    else:
        quality_badge = f"{Back.BLUE}{Fore.WHITE} AUTO USE PRESET {Style.RESET_ALL} {Fore.GREEN}#{STATE.config.get('preset', 1)} ({preset_info['name']}){Style.RESET_ALL}"

    cookies_mode = STATE.config.get("browser_cookies", "none").upper()
    cookies_badge = f"{Fore.GREEN}{cookies_mode}{Style.RESET_ALL}" if cookies_mode != "NONE" else f"{Fore.LIGHTBLACK_EX}NONE{Style.RESET_ALL}"

    subs_mode = STATE.config.get("subtitles_mode", "off").upper()
    subs_badge = f"{Fore.GREEN}{subs_mode}{Style.RESET_ALL}" if subs_mode != "OFF" else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    speed_limit = STATE.config.get("speed_limit", "none").upper()
    speed_badge = f"{Fore.YELLOW}{speed_limit}{Style.RESET_ALL}" if speed_limit != "NONE" else f"{Fore.LIGHTBLACK_EX}UNLIMITED{Style.RESET_ALL}"

    sb_mode = STATE.config.get("sponsorblock", False)
    sb_badge = f"{Fore.GREEN}ON{Style.RESET_ALL}" if sb_mode else f"{Fore.LIGHTBLACK_EX}OFF{Style.RESET_ALL}"

    download_folder = Path(STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    free_gb = get_free_disk_space_gb(download_folder)
    if free_gb >= 10.0:
        disk_badge = f"{Fore.GREEN}{free_gb} GB Free{Style.RESET_ALL}"
    elif free_gb >= 0.0:
        disk_badge = f"{Fore.RED}⚠️ LOW: {free_gb} GB Free{Style.RESET_ALL}"
    else:
        disk_badge = f"{Fore.LIGHTBLACK_EX}Available{Style.RESET_ALL}"

    engine_badge = f"{Back.CYAN}{Fore.BLACK} 16x GIGABIT TURBO (ARIA2C + NATIVE MULTI-STREAM) {Style.RESET_ALL}" if ARIA2C_EXE.exists() else f"{Back.GREEN}{Fore.BLACK} 16-CONCURRENT STREAMS {Style.RESET_ALL}"
    active_site = getattr(STATE, "last_seen_website", None) or STATE.config.get("default_stream_referer", "https://movy.sx/")

    banner = f"""{Fore.CYAN}
  ██╗   ██╗████████╗   ██████╗ ██╗     ██████╗ 
  ╚██╗ ██╔╝╚══██╔══╝   ██╔══██╗██║     ██╔══██╗
   ╚████╔╝    ██║█████╗██║  ██║██║     ██████╔╝
    ╚██╔╝     ██║╚════╝██║  ██║██║     ██╔═══╝ 
     ██║      ██║      ██████╔╝███████╗██║     
     ╚═╝      ╚═╝      ╚═════╝ ╚══════╝╚═╝     
   {Style.BRIGHT}{Fore.YELLOW}★ SUPERCHARGED DOWNLOAD WORKSTATION ★{Style.RESET_ALL}
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
  {Fore.WHITE}[●] ENGINE SPEED       :{Style.RESET_ALL} {engine_badge}
  {Fore.WHITE}[●] CLIPBOARD MONITOR  :{Style.RESET_ALL} {clip_badge}
  {Fore.WHITE}[●] STREAMING DETECTOR :{Style.RESET_ALL} {Fore.GREEN}{active_site}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Auto-attaches referer){Style.RESET_ALL}
  {Fore.WHITE}[●] QUALITY MODE       :{Style.RESET_ALL} {quality_badge}
  {Fore.WHITE}[●] BROWSER COOKIES    :{Style.RESET_ALL} {cookies_badge} (Bypasses login & age walls)
  {Fore.WHITE}[●] SUBTITLES          :{Style.RESET_ALL} {subs_badge} | {Fore.WHITE}SPEED LIMIT:{Style.RESET_ALL} {speed_badge} | {Fore.WHITE}SPONSORBLOCK:{Style.RESET_ALL} {sb_badge}
  {Fore.WHITE}[●] SAVE DIRECTORY     :{Style.RESET_ALL} {Fore.CYAN}{download_folder}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}({disk_badge}{Fore.LIGHTBLACK_EX}){Style.RESET_ALL}
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
  {Style.BRIGHT}{Fore.LIGHTWHITE_EX}HOW TO DOWNLOAD:{Style.RESET_ALL}
  {Fore.LIGHTGREEN_EX}▶ Just COPY any video OR Spotify link in your browser!{Style.RESET_ALL}
    Terminal detects it immediately and prompts for quality or downloads.
  {Fore.LIGHTBLACK_EX}──────────────────────────────────────────────────────────────────{Style.RESET_ALL}
  {Fore.LIGHTYELLOW_EX}POWER COMMANDS:{Style.RESET_ALL}
  {Fore.CYAN}[URL]{Style.RESET_ALL}                   : Paste URL directly to download
  {Fore.CYAN}play <song/video>{Style.RESET_ALL}       : Search YouTube & instant download as 320k MP3
  {Fore.CYAN}yt <query>{Style.RESET_ALL}                 : Search YouTube and pick from top 5 results
  {Fore.CYAN}info [URL]{Style.RESET_ALL}                 : Inspect video details, max resolution, audio & subs
  {Fore.CYAN}spotify [URL]{Style.RESET_ALL}           : Download Spotify track, album, or playlist (320kbps MP3)
  {Fore.CYAN}site <name/url>{Style.RESET_ALL}         : Switch active streaming site (e.g. {Fore.YELLOW}site cinejoy{Style.RESET_ALL} or {Fore.YELLOW}site movy{Style.RESET_ALL})
  {Fore.CYAN}trim <start>-<end> [URL]{Style.RESET_ALL} : Download specific time clip (e.g. {Fore.YELLOW}trim 01:15-02:30 URL{Style.RESET_ALL})
  {Fore.CYAN}items <range> [URL]{Style.RESET_ALL}      : Download playlist items (e.g. {Fore.YELLOW}items 1-5 URL{Style.RESET_ALL})
  {Fore.CYAN}1080p [URL]{Style.RESET_ALL}             : Download in 1080p Full HD
  {Fore.CYAN}720p [URL]{Style.RESET_ALL}              : Download in 720p HD
  {Fore.CYAN}4k [URL]{Style.RESET_ALL}                : Download in 4K / Best Quality
  {Fore.CYAN}mp3 [URL]{Style.RESET_ALL}               : Download as MP3 (320kbps)
  {Fore.CYAN}m4a [URL]{Style.RESET_ALL}               : Download as Original AAC Audio (.m4a)
  {Fore.CYAN}flac [URL]{Style.RESET_ALL}              : Download as Lossless Studio FLAC
  {Fore.CYAN}subs [lang] [URL]{Style.RESET_ALL}        : Embed subtitles (e.g. {Fore.YELLOW}subs en URL{Style.RESET_ALL} or {Fore.YELLOW}subs list URL{Style.RESET_ALL})
  {Fore.CYAN}sb [on/off]{Style.RESET_ALL}              : Toggle SponsorBlock (auto-skip sponsors/promos)
  {Fore.CYAN}ref [site] [URL]{Style.RESET_ALL}        : Cloud stream with Referer (or type 'ref' alone for guided)
  {Fore.CYAN}f [URL]{Style.RESET_ALL}                 : Inspect & pick from ALL exact format codes (-F)
  {Fore.CYAN}cookies <browser>{Style.RESET_ALL}       : Set cookies (chrome / edge / firefox / brave / off)
  {Fore.CYAN}limit <rate>{Style.RESET_ALL}            : Set speed limit (e.g. limit 5M, limit 10M, limit off)
  {Fore.CYAN}p{Style.RESET_ALL} or {Fore.CYAN}preset{Style.RESET_ALL}              : Choose default quality preset (1-12)
  {Fore.CYAN}qmode{Style.RESET_ALL}                   : Toggle Quality Picker (Pick Choices / Auto Preset)
  {Fore.CYAN}c{Style.RESET_ALL} or {Fore.CYAN}clip{Style.RESET_ALL}                : Toggle Clipboard Mode (Auto / Prompt / Off)
  {Fore.CYAN}o{Style.RESET_ALL} or {Fore.CYAN}open{Style.RESET_ALL}                : Open Downloads Folder in Explorer
  {Fore.CYAN}d{Style.RESET_ALL} or {Fore.CYAN}dir{Style.RESET_ALL}                 : Change Downloads Folder
  {Fore.CYAN}h{Style.RESET_ALL} or {Fore.CYAN}history{Style.RESET_ALL} [clear]     : View Download History (or 'h clear' to reset)
  {Fore.CYAN}s{Style.RESET_ALL} or {Fore.CYAN}settings{Style.RESET_ALL}            : Full Settings Menu
  {Fore.CYAN}u{Style.RESET_ALL} or {Fore.CYAN}update{Style.RESET_ALL}              : Update yt-dlp to latest version
  {Fore.CYAN}cls{Style.RESET_ALL}                    : Clear screen and refresh status
  {Fore.CYAN}q{Style.RESET_ALL} or {Fore.CYAN}exit{Style.RESET_ALL}                : Exit
{Fore.LIGHTBLACK_EX}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}
"""
    print(banner)

    if STATE.update_available:
        print(f"{Back.YELLOW}{Fore.BLACK} ★ NEW YT-DLP RELEASE AVAILABLE: v{STATE.update_available} {Style.RESET_ALL} {Fore.YELLOW}Type 'u' or 'update' to upgrade!{Style.RESET_ALL}\n")


def read_single_choice(valid_chars: set, default_val: str) -> str:
    """Reads a single keystroke without requiring Enter, or Enter for default"""
    if HAS_MSVCRT and sys.stdin.isatty():
        while not STATE.stop_requested:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return default_val
                elif ch in ("\x03", "\x1b"):  # Ctrl+C or Esc
                    sys.stdout.write("Skip\n")
                    sys.stdout.flush()
                    return "s"
                elif ch.lower() in valid_chars:
                    sys.stdout.write(ch + "\n")
                    sys.stdout.flush()
                    return ch.lower()
            time.sleep(0.02)
        return default_val
    else:
        line = sys.stdin.readline().strip().lower()
        return line if line else default_val


def inspect_and_pick_formats(url: str, referer: str = None):
    """Run yt-dlp -F to show all formats and let the user pick the exact format code"""
    print(f"\n{Fore.CYAN}[*] Fetching available formats from video...{Style.RESET_ALL}\n")
    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--no-warnings"
    ]
    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])
    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])
    if STATE.config.get("browser_cookies", "none") != "none":
        cmd.extend(["--cookies-from-browser", STATE.config["browser_cookies"]])
    if referer:
        cmd.extend(["--referer", referer])
    cmd.extend(["-F", url])

    try:
        subprocess.run(cmd)
    except Exception as e:
        print(f"{Fore.RED}[!] Error fetching formats: {e}{Style.RESET_ALL}")
        return None

    print(f"\n{Fore.LIGHTYELLOW_EX}Examples: '137+140' (1080p video + audio), '22' (720p with audio), 'best'{Style.RESET_ALL}")
    chosen = input(f"{Fore.CYAN}Enter format ID (or press Enter for best): {Style.RESET_ALL}").strip()
    return chosen if chosen else "bv*+ba/b"


def prompt_video_quality(url: str, referer: str = None):
    """
    Interactive Video Quality Picker:
    Single-keystroke selection: Press 1-9, a, b, c, 0, or Enter for instant download!
    """
    default_pid = STATE.config.get("preset", 1)
    default_name = PRESETS.get(default_pid, PRESETS[1])["name"]

    print(f"\n{Fore.CYAN}╔═══════════════════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║ {Style.BRIGHT}{Fore.YELLOW}🎥 PICK VIDEO QUALITY FOR THIS DOWNLOAD{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║ {Fore.WHITE}URL: {Fore.LIGHTCYAN_EX}{url[:65]}{'...' if len(url) > 65 else ''}{Style.RESET_ALL}")
    if referer:
        print(f"{Fore.CYAN}║ {Fore.WHITE}Referer: {Fore.YELLOW}{referer}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╠═══════════════════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[1] 4K / 2160p (Best Available){Style.RESET_ALL}     {Fore.LIGHTBLACK_EX}- Maximum possible resolution{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[2] 1440p (2K Quad HD){Style.RESET_ALL}              {Fore.LIGHTBLACK_EX}- Ultra high quality{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[3] 1080p (Full HD){Style.RESET_ALL}                 {Fore.LIGHTBLACK_EX}- Recommended quality & size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[4] 720p  (HD){Style.RESET_ALL}                     {Fore.LIGHTBLACK_EX}- Fast download, smaller size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[5] 480p  (SD Standard){Style.RESET_ALL}            {Fore.LIGHTBLACK_EX}- Low bandwidth{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.GREEN}[6] 360p  (Data Saver){Style.RESET_ALL}             {Fore.LIGHTBLACK_EX}- Smallest video file size{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[7] Audio MP3 (320kbps){Style.RESET_ALL}            {Fore.LIGHTBLACK_EX}- MP3 with album artwork & tags{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[8] Audio M4A (Original AAC){Style.RESET_ALL}       {Fore.LIGHTBLACK_EX}- Direct audio extraction{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[9] Audio FLAC (Lossless Studio){Style.RESET_ALL}   {Fore.LIGHTBLACK_EX}- High-res lossless audiophile audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[a] Audio OPUS (Next-Gen){Style.RESET_ALL}          {Fore.LIGHTBLACK_EX}- Ultra efficient modern audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.YELLOW}[b] Audio WAV (Raw PCM){Style.RESET_ALL}           {Fore.LIGHTBLACK_EX}- Uncompressed raw audio{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.CYAN}[0] Universal MKV (All Subs){Style.RESET_ALL}        {Fore.LIGHTBLACK_EX}- Preserves all subtitles & tracks{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.MAGENTA}[f] Inspect All Formats (-F){Style.RESET_ALL}       {Fore.LIGHTBLACK_EX}- Pick exact format ID table{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║  {Fore.RED}[s] Skip / Cancel{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╚═══════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"{Fore.LIGHTWHITE_EX}Press single key [1-9, a, b, 0, f, s, or {Fore.GREEN}Enter for Default (#{default_pid} - {default_name}){Fore.LIGHTWHITE_EX}]: {Style.RESET_ALL}", end="", flush=True)

    valid_keys = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "a", "b", "0", "f", "s"}
    choice = read_single_choice(valid_keys, default_val=str(default_pid))

    if choice in ("1", "4k", "2160p"):
        return 1, None
    elif choice in ("2", "2k", "1440p"):
        return 2, None
    elif choice in ("3", "1080p", "1080"):
        return 3, None
    elif choice in ("4", "720p", "720"):
        return 4, None
    elif choice in ("5", "480p", "480"):
        return 5, None
    elif choice in ("6", "360p", "360"):
        return 6, None
    elif choice in ("7", "mp3"):
        return 7, None
    elif choice in ("8", "m4a", "aac"):
        return 8, None
    elif choice in ("9", "flac"):
        return 9, None
    elif choice in ("a", "opus"):
        return 10, None
    elif choice in ("b", "wav"):
        return 11, None
    elif choice in ("0", "mkv"):
        return 12, None
    elif choice in ("f", "formats", "format"):
        custom_fmt = inspect_and_pick_formats(url, referer=referer)
        return None, custom_fmt
    elif choice in ("s", "skip", "cancel", "n"):
        print(f"{Fore.LIGHTBLACK_EX}[!] Download skipped.{Style.RESET_ALL}\n")
        return None, None
    else:
        return default_pid, None


def build_ytdlp_command(job_or_url, **kwargs):
    """Construct command arguments for yt-dlp with full power-user features & 99.9% reliability"""
    if isinstance(job_or_url, dict):
        job = job_or_url
        url = job["url"]
        custom_preset = job.get("preset_override")
        custom_format_str = job.get("custom_format_str")
        force_audio = job.get("force_audio", False)
        force_video = job.get("force_video", False)
        force_playlist = job.get("force_playlist", False)
        download_section = job.get("download_section")
        playlist_items = job.get("playlist_items")
        force_subs = job.get("force_subs", False)
        referer = job.get("referer")
        headers = job.get("headers")
        target_dir = job.get("target_dir")
        custom_output_template = job.get("custom_output_template")
        extra_metadata = job.get("extra_metadata")
    else:
        url = str(job_or_url)
        custom_preset = kwargs.get("custom_preset")
        custom_format_str = kwargs.get("custom_format_str")
        force_audio = kwargs.get("force_audio", False)
        force_video = kwargs.get("force_video", False)
        force_playlist = kwargs.get("force_playlist", False)
        download_section = kwargs.get("download_section")
        playlist_items = kwargs.get("playlist_items")
        force_subs = kwargs.get("force_subs", False)
        referer = kwargs.get("referer")
        headers = kwargs.get("headers")
        target_dir = kwargs.get("target_dir")
        custom_output_template = kwargs.get("custom_output_template")
        extra_metadata = kwargs.get("extra_metadata")

    preset_id = custom_preset or STATE.config.get("preset", 1)
    if force_audio:
        preset_id = 7
    elif force_video:
        preset_id = 1

    preset = PRESETS.get(preset_id, PRESETS[1])
    download_dir = Path(target_dir or STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    download_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--windows-filenames",
        "--no-mtime",
        "--no-part",                   # Crucial: direct write eliminates [WinError 32] file locking collisions
        "--no-continue",               # Re-fetch broken fragments from byte 0 (prevents HTTP 416 Range Not Satisfiable)
        "--skip-unavailable-fragments",# Gracefully skip missing cloud CDN fragments without aborting
        "-N", "16",                    # Turbo: 16 concurrent fragments in parallel (saturates up to 1 Gbps)
        "--buffer-size", "16M",        # High throughput network buffer
        "--http-chunk-size", "10M",
        "--retries", "20",             # Robust network retries
        "--fragment-retries", "25",    # Robust fragment retries
        "--file-access-retries", "25", # Antivirus / Windows Defender lock resilience
        "--retry-sleep", "fragment:exp=1:20",
        "--retry-sleep", "file_access:exp=1:10",
        "--fixup", "warn",             # Safe fixup policy to avoid out-of-memory crashes on 16GB files
        "--newline",
        "--progress-template",
        "download:PROGRESS|P=%(progress._percent_str)s|D=%(progress._downloaded_bytes_str)s|T=%(progress._total_bytes_str,progress._total_bytes_estimate_str)s|S=%(progress._speed_str)s|E=%(progress._eta_str)s|F=%(progress.fragment_index)s/%(progress.fragment_count)s"
    ]

    if FFMPEG_EXE.exists():
        cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE.parent)])

    # Aria2c turbo downloader for direct HTTP/HTTPS connections (16 concurrent streams)
    if ARIA2C_EXE.exists():
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader", "dash,m3u8:native",
            "--downloader-args", "aria2c:-s 16 -x 16 -k 1M -j 16"
        ])

    # Node.js runtime acceleration if installed
    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])

    # Browser cookies integration
    cookies = STATE.config.get("browser_cookies", "none")
    if cookies != "none":
        cmd.extend(["--cookies-from-browser", cookies])

    # Speed limit
    limit = STATE.config.get("speed_limit", "none")
    if limit != "none":
        cmd.extend(["--limit-rate", limit])

    # Referer & custom headers (for cloud video servers / embed players like VidEasy)
    if referer:
        cmd.extend(["--referer", referer])
    if headers:
        for h in headers:
            cmd.extend(["--add-header", h])

    # Output directory & filename templates: playlists get their own subfolder!
    if custom_output_template:
        cmd.extend(["-o", custom_output_template])
    else:
        out_single = str(download_dir / "%(title)s [%(id)s].%(ext)s")
        out_playlist = str(download_dir / "%(playlist_title,playlist)s" / "%(playlist_index)s - %(title)s [%(id)s].%(ext)s")
        cmd.extend(["-o", f"playlist:{out_playlist}", "-o", out_single])

    # Extra metadata tags (artist, title, album, track number for music studio bridge)
    if extra_metadata:
        for mk, mv in extra_metadata.items():
            if mv:
                cmd.extend(["--parse-metadata", f"{mv}:%({mk})s"])

    # Time-range trimming
    if download_section:
        cmd.extend(["--download-sections", f"*{download_section}", "--force-keyframes-at-cuts"])

    # Playlist selective items
    if playlist_items:
        cmd.extend(["--playlist-items", playlist_items, "--yes-playlist"])
    elif not force_playlist:
        if "playlist?list=" in url:
            pass
        elif "list=" in url and "watch?v=" in url:
            cmd.append("--no-playlist")
        else:
            cmd.append("--no-playlist")
    else:
        cmd.append("--yes-playlist")

    # Custom format string override
    if custom_format_str:
        cmd.extend(["-f", custom_format_str])
        cmd.extend(["--merge-output-format", "mp4", "--embed-thumbnail", "--embed-metadata"])
        preset_name = f"Custom: {custom_format_str}"
    else:
        # Standard preset format selection
        preset_name = preset["name"]
        if preset["extract_audio"]:
            cmd.extend(["-x", "--audio-format", preset["audio_format"]])
        else:
            if preset["format"]:
                cmd.extend(["-f", preset["format"]])
            if preset["merge_format"]:
                cmd.extend(["--merge-output-format", preset["merge_format"]])

        # Extra preset args
        if preset.get("extra_args"):
            cmd.extend(preset["extra_args"])

    # Subtitles handling
    sub_lang = job.get("sub_lang") if isinstance(job_or_url, dict) else kwargs.get("sub_lang")
    subs_mode = STATE.config.get("subtitles_mode", "off")
    if (subs_mode != "off" or force_subs or sub_lang) and not preset.get("extract_audio"):
        if sub_lang:
            lang = sub_lang if sub_lang == "all" else f"{sub_lang}.*"
        else:
            lang = "en.*" if subs_mode == "en" else "all"
        cmd.extend(["--write-auto-subs", "--write-subs", "--sub-langs", lang, "--embed-subs"])

    # SponsorBlock
    if STATE.config.get("sponsorblock", False):
        cmd.extend(["--sponsorblock-remove", "sponsor,selfpromo"])

    cmd.append(url)
    return cmd, preset_name


def format_linux_bar(title: str, p_str: str, d_str: str, t_str: str, s_str: str, e_str: str, f_str: str = "") -> tuple:
    """Format Linux CLI / tqdm style progress bar:
    Spider-Man (2160p): 45%|██████████████████░░░░░░░░░░░░░░░| 7.24G/16.1G [11:20, 14.2MB/s]
    """
    p_clean = re.sub(r"[^0-9.]", "", p_str.strip())
    try:
        pct = float(p_clean)
    except Exception:
        pct = 0.0
    if pct == 0.0 and "/" in f_str:
        try:
            parts = f_str.split("/")
            pct = (float(parts[0]) / float(parts[1])) * 100.0
        except Exception:
            pass

    spd = s_str.strip() if s_str and s_str != "NA" else "--"
    eta = e_str.strip() if e_str and e_str != "NA" else "--:--"

    d = d_str.strip() if d_str and d_str != "NA" else ""
    t = t_str.strip() if t_str and t_str != "NA" else ""
    if d and t:
        size_str = f"{d}/{t}"
    elif d:
        size_str = d
    elif f_str and f_str != "NA/NA":
        size_str = f"frag {f_str}"
    else:
        size_str = ""

    clean_title = title.replace("_", " ").replace("-", " ").strip()
    if len(clean_title) > 24:
        clean_title = clean_title[:21] + "..."
    elif not clean_title:
        clean_title = "Downloading"

    term_width = shutil.get_terminal_size((80, 20)).columns
    overhead = len(clean_title) + len(size_str) + len(eta) + len(spd) + 18
    bar_width = max(10, min(32, term_width - overhead))

    filled = int(bar_width * (pct / 100.0))
    filled = max(0, min(bar_width, filled))
    empty = bar_width - filled

    fill_char = "█"
    empty_char = "░"

    bar_gfx = f"{Fore.GREEN}{fill_char * filled}{Fore.LIGHTBLACK_EX}{empty_char * empty}{Style.RESET_ALL}"
    out = f"\r{Fore.CYAN}{clean_title}:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{pct:5.1f}%{Style.RESET_ALL}|{bar_gfx}| {Fore.YELLOW}{size_str}{Style.RESET_ALL} {Fore.WHITE}[{Fore.LIGHTCYAN_EX}{eta}{Fore.WHITE}, {Fore.LIGHTMAGENTA_EX}{spd}{Fore.WHITE}]{Style.RESET_ALL}\033[K"
    return out, pct, spd, eta


def set_console_title(title: str):
    """Update Windows console title bar if running on Windows"""
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:
            pass


def reset_console_title():
    """Reset console title to default workstation title"""
    set_console_title("★ YT-DLP Supercharged Workstation ★")


def print_download_card(job: dict, preset_name: str, effective_target: str):
    """Render a clean status card for an upcoming download"""
    url = job.get("url", "")
    display_title = job.get("display_title")
    print(f"\n{Fore.CYAN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Style.BRIGHT}{Fore.YELLOW}⚡ STARTING DOWNLOAD{Style.RESET_ALL}")
    if display_title:
        print(f"{Fore.CYAN}│ {Fore.WHITE}Track  :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{display_title}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}URL    :{Style.RESET_ALL} {Fore.LIGHTCYAN_EX}{url}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}Quality:{Style.RESET_ALL} {Fore.GREEN}{preset_name}{Style.RESET_ALL}")
    if job.get("referer"):
        print(f"{Fore.CYAN}│ {Fore.WHITE}Referer:{Style.RESET_ALL} {Fore.YELLOW}{job['referer']}{Style.RESET_ALL}")
    if job.get("download_section"):
        print(f"{Fore.CYAN}│ {Fore.WHITE}Trim   :{Style.RESET_ALL} {Fore.YELLOW}{job['download_section']}{Style.RESET_ALL}")
    if job.get("playlist_items"):
        print(f"{Fore.CYAN}│ {Fore.WHITE}Tracks :{Style.RESET_ALL} {Fore.YELLOW}{job['playlist_items']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}│ {Fore.WHITE}Target :{Style.RESET_ALL} {effective_target}")
    print(f"{Fore.CYAN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}\n")


def parse_progress_data(line: str) -> dict:
    """Extract progress metadata fields from yt-dlp progress template output"""
    data = {}
    prog_part = line.split("PROGRESS|")[-1]
    for segment in prog_part.split("|"):
        if "=" in segment:
            k, v = segment.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def finalize_download(job: dict, success: bool, duration: float, error_msg: str,
                      download_title: str, preset_name: str, effective_target: str):
    """Handle post-download operations: cover art embedding, sound, toast, history logging"""
    url = job.get("url", "")
    spotify_thumbnail = job.get("spotify_thumbnail")
    custom_output_template = job.get("custom_output_template")

    if success:
        if spotify_thumbnail:
            try:
                mp3_target = None
                if custom_output_template and custom_output_template.endswith(".%(ext)s"):
                    p_cand = Path(custom_output_template.replace(".%(ext)s", ".mp3"))
                    if p_cand.exists():
                        mp3_target = p_cand
                if not mp3_target:
                    cand_files = sorted(Path(effective_target).glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if cand_files and (time.time() - cand_files[0].stat().st_mtime) < 60:
                        mp3_target = cand_files[0]
                if mp3_target and mp3_target.exists():
                    embed_cover_art_ffmpeg(mp3_target, spotify_thumbnail)
            except Exception:
                pass

        saved_file_name = download_title
        saved_size_str = ""
        try:
            cand_files = sorted(
                [p for p in Path(effective_target).glob("*") if p.is_file() and not p.name.endswith(".part")],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if cand_files and (time.time() - cand_files[0].stat().st_mtime) < 120:
                newest = cand_files[0]
                saved_file_name = newest.name
                bytes_len = newest.stat().st_size
                if bytes_len >= (1024 * 1024 * 1024):
                    saved_size_str = f" ({bytes_len / (1024**3):.2f} GB)"
                elif bytes_len >= (1024 * 1024):
                    saved_size_str = f" ({bytes_len / (1024**2):.1f} MB)"
                elif bytes_len > 0:
                    saved_size_str = f" ({bytes_len / 1024:.0f} KB)"
        except Exception:
            pass

        play_sound("success")
        send_windows_toast("Download Complete!", f"Finished in {duration}s: {download_title[:50]}")
        print(f"\n{Fore.GREEN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│ ✔ DOWNLOAD COMPLETED SUCCESSFULLY ({duration}s){Style.RESET_ALL}")
        print(f"{Fore.GREEN}│ {Fore.WHITE}File  :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{saved_file_name}{saved_size_str}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│ {Fore.WHITE}Preset:{Style.RESET_ALL} {Fore.CYAN}{preset_name}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}│ {Fore.WHITE}Saved :{Style.RESET_ALL} {effective_target}")
        print(f"{Fore.GREEN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}\n")
        STATE.add_history_entry({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "title": saved_file_name,
            "preset": preset_name,
            "status": "Success",
            "duration": f"{duration}s"
        })
    else:
        play_sound("error")
        send_windows_toast("Download Failed", f"{error_msg}")
        print(f"\n{Fore.RED}✘ [FAILED]{Style.RESET_ALL} {error_msg}\n")
        if not job.get("referer"):
            print(f"{Fore.YELLOW}[💡 TIP] If you got HTTP 403 Forbidden, this video server blocks direct downloads!{Style.RESET_ALL}")
            print(f"{Fore.LIGHTYELLOW_EX}    Run with Referer: {Fore.GREEN}ref https://movy.sx/ <stream_url>{Style.RESET_ALL}")
            print(f"{Fore.LIGHTYELLOW_EX}    Or simply type {Fore.GREEN}ref{Fore.LIGHTYELLOW_EX} alone and press Enter for guided download!{Style.RESET_ALL}\n")
        STATE.add_history_entry({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "preset": preset_name,
            "status": "Failed",
            "error": error_msg
        })


def execute_download(job: dict):
    """Execute a single download job with live progress display"""
    effective_target = job.get("target_dir") or STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR)
    free_gb = get_free_disk_space_gb(Path(effective_target))
    if 0.0 <= free_gb < 1.0:
        print(f"{Fore.RED}[⚠️ WARNING] Critical low disk space ({free_gb} GB remaining)! Download may abort if file is large.{Style.RESET_ALL}")

    cmd, preset_name = build_ytdlp_command(job)
    print_download_card(job, preset_name, effective_target)

    start_time = time.time()
    success = False
    error_msg = ""
    last_pct = 0.0
    has_shown_bar = False
    download_title = job.get("display_title") or Path(job["url"]).stem
    captured_errors = []
    in_error_mode = False

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )

        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue

            if "PROGRESS|P=" in line or line.startswith("PROGRESS|") or ("P=" in line and "|D=" in line and "|S=" in line):
                in_error_mode = False
                data = parse_progress_data(line)
                bar_text, pct, spd, eta = format_linux_bar(
                    download_title,
                    data.get("P", "0.0%"),
                    data.get("D", ""),
                    data.get("T", ""),
                    data.get("S", "--"),
                    data.get("E", "--:--"),
                    data.get("F", "")
                )
                sys.stdout.write(bar_text)
                sys.stdout.flush()
                has_shown_bar = True
                last_pct = pct
                set_console_title(f"[{pct:.1f}% - {spd} - ETA {eta}] YT-DLP Workstation")

            elif "[download] Destination:" in line:
                in_error_mode = False
                try:
                    dest = line.split("Destination:", 1)[1].strip()
                    download_title = Path(dest).stem
                except Exception:
                    pass
                if has_shown_bar:
                    sys.stdout.write("\n")
                    has_shown_bar = False
                print(f"{Fore.LIGHTCYAN_EX}[+] File:{Style.RESET_ALL} {download_title}")

            elif any(ign in line for ign in ("Retrying fragment", "fragment not found; Skipping", "Live HLS streams are not supported")):
                continue

            elif "ERROR:" in line:
                if has_shown_bar:
                    sys.stdout.write("\n")
                    has_shown_bar = False
                print(f"{Fore.RED}{line}{Style.RESET_ALL}")
                err_detail = line.replace("ERROR:", "").strip()
                if err_detail:
                    captured_errors.append(err_detail)
                in_error_mode = True

            elif "WARNING:" in line:
                if has_shown_bar:
                    sys.stdout.write("\n")
                    has_shown_bar = False
                print(f"{Fore.YELLOW}{line}{Style.RESET_ALL}")

            elif in_error_mode and not any(k in line for k in ("PROGRESS|", "[download]", "[info]")):
                print(f"{Fore.RED}       {line}{Style.RESET_ALL}")
                captured_errors.append(line)

            elif "[info]" in line or "[Fixup" in line:
                in_error_mode = False
                if has_shown_bar:
                    sys.stdout.write("\n")
                    has_shown_bar = False
                print(f"{Fore.LIGHTBLACK_EX}{line}{Style.RESET_ALL}")

        proc.wait()
        if has_shown_bar:
            sys.stdout.write("\n")

        success = (proc.returncode == 0)
        if not success and last_pct >= 99.0:
            success = True

        if not success:
            cleanup_orphaned_fragments(Path(effective_target))
            error_msg = " | ".join(captured_errors[:2]) if captured_errors else f"yt-dlp exited with error code {proc.returncode}"

    except KeyboardInterrupt:
        cleanup_orphaned_fragments(Path(effective_target))
        print(f"\n{Fore.YELLOW}[!] Download cancelled by user.{Style.RESET_ALL}")
        error_msg = "Cancelled by user"
    except Exception as e:
        success = False
        error_msg = str(e)
    finally:
        reset_console_title()

    duration = round(time.time() - start_time, 1)
    finalize_download(job, success, duration, error_msg, download_title, preset_name, effective_target)


def clipboard_watcher_thread():
    """Background thread that monitors system clipboard"""
    last_text = ""
    try:
        last_text = get_clipboard_text().strip()
    except Exception:
        pass

    while not STATE.stop_requested:
        time.sleep(0.4)
        clip_mode = STATE.config.get("clipboard_mode", "auto")
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

        # Check if copied text is a streaming website URL (e.g. user browsing movy.sx, cinejoy.pk, etc.)
        lower_txt = current_text.lower()
        matched_site = None
        for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
            if s_domain in lower_txt:
                matched_site = s_url
                break
        if not matched_site and any(k in lower_txt for k in ("movie", "watch", "stream", "series", "anime")) and lower_txt.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(current_text)
            if parsed.netloc:
                matched_site = f"{parsed.scheme}://{parsed.netloc}/"

        if matched_site and not any(ext in lower_txt for ext in (".mp4", ".m3u8", ".webm", ".mkv", ".mpd", ".ts")):
            if STATE.last_seen_website != matched_site:
                STATE.last_seen_website = matched_site
                STATE.config["default_stream_referer"] = matched_site
                STATE.save_config()
                play_sound("notice")
                print(f"\n{Fore.GREEN}[⚡] Auto-detected Active Streaming Site:{Style.RESET_ALL} {Fore.CYAN}{matched_site}{Style.RESET_ALL} {Fore.LIGHTBLACK_EX}(Stream links will auto-use this referer){Style.RESET_ALL}\n")
            continue

        # Check if copied text is a Spotify link
        if is_spotify_url(current_text):
            m_url = extract_media_url(current_text) or current_text
            clean = STATE.clean_url(m_url)
            with STATE.lock:
                if clean in STATE.seen_clipboard:
                    continue
                STATE.seen_clipboard.add(clean)
            play_sound("notice")
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Spotify link on Clipboard!{Style.RESET_ALL} {Fore.CYAN}{m_url}{Style.RESET_ALL}")
            if clip_mode == "auto":
                enqueue_spotify_download(m_url)
            elif clip_mode == "prompt":
                with STATE.lock:
                    STATE.pending_prompt_url = m_url
                    STATE.pending_prompt_ref = None
            continue

        # Validate URL
        if not is_valid_media_url(current_text):
            continue

        url = extract_media_url(current_text)
        clean = STATE.clean_url(url)

        # Duplicate guard: check if already in seen set or current queue
        with STATE.lock:
            if clean in STATE.seen_clipboard:
                continue
            if any(item["url"] == url for item in STATE.download_queue):
                continue
            STATE.seen_clipboard.add(clean)

        play_sound("notice")

        auto_ref = auto_detect_referer(url)
        if auto_ref:
            print(f"\n{Fore.GREEN}[⚡] Auto-detected Cloud Stream! Attached Referer:{Style.RESET_ALL} {Fore.CYAN}{auto_ref}{Style.RESET_ALL}")

        if clip_mode == "auto":
            STATE.enqueue_job({
                "url": url,
                "referer": auto_ref,
                "preset_override": None,
                "custom_format_str": None,
                "force_audio": False,
                "force_video": False,
                "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
            })
        elif clip_mode == "prompt":
            with STATE.lock:
                STATE.pending_prompt_url = url
                STATE.pending_prompt_ref = auto_ref


def select_preset_menu():
    """Interactive preset selection menu with full resolution choices"""
    print(f"\n{Fore.CYAN}═══ SELECT DEFAULT QUALITY PRESET ═══{Style.RESET_ALL}")
    for pid, p in PRESETS.items():
        is_cur = " [ACTIVE]" if pid == STATE.config.get("preset", 1) else ""
        color = Fore.LIGHTGREEN_EX if is_cur else Fore.WHITE
        print(f"  {color}[{pid}] {p['name']}{is_cur}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTBLACK_EX}{p['desc']}{Style.RESET_ALL}")

    print(f"\n  {Fore.YELLOW}[0] Toggle 'Ask Quality on Each Download'{Style.RESET_ALL} (Currently: {Fore.GREEN if STATE.config.get('ask_quality_each_time', True) else Fore.RED}{'ON' if STATE.config.get('ask_quality_each_time', True) else 'OFF'}{Style.RESET_ALL})")
    print(f"  {Fore.YELLOW}[b] Back / Cancel{Style.RESET_ALL}")

    choice = input(f"\n{Fore.CYAN}Enter option (1-12, or 0 to toggle prompt mode): {Style.RESET_ALL}").strip().lower()
    if choice == "0":
        STATE.config["ask_quality_each_time"] = not STATE.config.get("ask_quality_each_time", True)
        STATE.save_config()
        print(f"{Fore.GREEN}[✓] 'Ask Quality on Each Download' is now: {'ON' if STATE.config['ask_quality_each_time'] else 'OFF'}{Style.RESET_ALL}\n")
    elif choice in [str(i) for i in PRESETS.keys()]:
        pid = int(choice)
        STATE.config["preset"] = pid
        STATE.save_config()
        print(f"{Fore.GREEN}[✓] Default preset updated to #{pid}: {PRESETS[pid]['name']}{Style.RESET_ALL}\n")
    else:
        print(f"{Fore.LIGHTBLACK_EX}Preset unchanged.{Style.RESET_ALL}\n")


def toggle_quality_prompt():
    """Toggle whether quality choices pop up for each video"""
    STATE.config["ask_quality_each_time"] = not STATE.config.get("ask_quality_each_time", True)
    STATE.save_config()
    status = "ON (Single-key quality picker will pop up for each video)" if STATE.config["ask_quality_each_time"] else "OFF (Videos will use default preset automatically)"
    print(f"\n{Fore.CYAN}[●] Quality Picker Mode:{Style.RESET_ALL} {Fore.GREEN if STATE.config['ask_quality_each_time'] else Fore.YELLOW}{status}{Style.RESET_ALL}\n")


def toggle_clipboard_mode():
    """Cycle between Auto, Prompt, and Off"""
    modes = ["auto", "prompt", "off"]
    current = STATE.config.get("clipboard_mode", "auto")
    next_idx = (modes.index(current) + 1) % len(modes) if current in modes else 0
    new_mode = modes[next_idx]
    STATE.config["clipboard_mode"] = new_mode
    STATE.save_config()

    labels = {
        "auto": f"{Fore.GREEN}AUTO-DETECT ON (Catches copied links immediately!){Style.RESET_ALL}",
        "prompt": f"{Fore.YELLOW}PROMPT FIRST (Asks confirmation before processing){Style.RESET_ALL}",
        "off": f"{Fore.RED}DISABLED (Manual input only){Style.RESET_ALL}"
    }
    print(f"\n{Fore.CYAN}[●] Clipboard Monitor is now:{Style.RESET_ALL} {labels[new_mode]}\n")


def select_browser_cookies():
    """Configure browser cookies to bypass age restriction / login walls"""
    print(f"\n{Fore.CYAN}═══ BROWSER COOKIES (LOGIN / AGE-RESTRICTION BYPASS) ═══{Style.RESET_ALL}")
    print(f"Borrow logged-in session from your browser so you never see 'Sign in to confirm your age':")
    browsers = ["none", "chrome", "edge", "firefox", "brave", "opera", "vivaldi"]
    cur = STATE.config.get("browser_cookies", "none")
    for i, b in enumerate(browsers, 1):
        is_cur = " [ACTIVE]" if b == cur else ""
        color = Fore.LIGHTGREEN_EX if b == cur else Fore.WHITE
        print(f"  {color}[{i}] {b.capitalize()}{is_cur}{Style.RESET_ALL}")

    choice = input(f"\n{Fore.CYAN}Select browser (1-7): {Style.RESET_ALL}").strip()
    if choice in [str(i) for i in range(1, len(browsers) + 1)]:
        selected = browsers[int(choice) - 1]
        STATE.config["browser_cookies"] = selected
        STATE.save_config()
        print(f"{Fore.GREEN}[✓] Browser cookies set to: {selected.upper()}{Style.RESET_ALL}\n")
    else:
        print(f"{Fore.LIGHTBLACK_EX}Unchanged.{Style.RESET_ALL}\n")


def open_downloads_folder():
    """Open download folder in Windows Explorer"""
    folder = Path(STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(folder))
        print(f"{Fore.GREEN}[✓] Opened folder:{Style.RESET_ALL} {folder}\n")
    except Exception as e:
        print(f"{Fore.RED}[!] Could not open folder: {e}{Style.RESET_ALL}\n")


def change_downloads_folder():
    """Change download folder path"""
    current = STATE.config.get("download_dir", DEFAULT_DOWNLOAD_DIR)
    print(f"\n{Fore.CYAN}Current downloads folder:{Style.RESET_ALL} {current}")
    new_path = input(f"{Fore.YELLOW}Enter new folder path (or press Enter to keep current): {Style.RESET_ALL}").strip()
    if new_path:
        p = Path(new_path)
        try:
            p.mkdir(parents=True, exist_ok=True)
            STATE.config["download_dir"] = str(p.resolve())
            STATE.save_config()
            print(f"{Fore.GREEN}[✓] Downloads folder updated to:{Style.RESET_ALL} {STATE.config['download_dir']}\n")
        except Exception as e:
            print(f"{Fore.RED}[!] Invalid folder path: {e}{Style.RESET_ALL}\n")


def show_history(arg: str = ""):
    """Display or manage download history: history [clear]"""
    if str(arg).strip().lower() in ("clear", "cls", "reset"):
        with STATE.lock:
            STATE.history.clear()
            STATE.save_history()
        print(f"\n{Fore.GREEN}[✓] Download history cleared!{Style.RESET_ALL}\n")
        return

    print(f"\n{Fore.CYAN}═══ RECENT DOWNLOAD HISTORY ═══{Style.RESET_ALL}")
    if not STATE.history:
        print(f"{Fore.LIGHTBLACK_EX}No downloads recorded yet.{Style.RESET_ALL}\n")
        return

    for item in STATE.history[-15:]:
        ts = item.get("timestamp", "")
        status = item.get("status", "")
        color = Fore.GREEN if status == "Success" else Fore.RED
        title = item.get("title") or item.get("url")
        print(f"  {Fore.LIGHTBLACK_EX}[{ts}]{Style.RESET_ALL} {color}[{status}]{Style.RESET_ALL} {Fore.WHITE}{title[:60]}{Style.RESET_ALL}")
        print(f"      {Fore.LIGHTBLACK_EX}Preset:{Style.RESET_ALL} {Fore.CYAN}{item.get('preset')}{Style.RESET_ALL} | {Fore.LIGHTBLACK_EX}Time:{Style.RESET_ALL} {item.get('duration', 'N/A')} | {Fore.LIGHTBLACK_EX}URL:{Style.RESET_ALL} {item.get('url')}")
    print(f"{Fore.LIGHTBLACK_EX}Tip: Type 'h clear' or 'history clear' to reset history.{Style.RESET_ALL}\n")


def toggle_settings_menu():
    """Full settings configuration menu"""
    print(f"\n{Fore.CYAN}═══ SETTINGS ═══{Style.RESET_ALL}")
    print(f"  [1] Ask Quality on Each Download              : {Fore.GREEN if STATE.config.get('ask_quality_each_time', True) else Fore.RED}{'ON' if STATE.config.get('ask_quality_each_time', True) else 'OFF'}{Style.RESET_ALL}")
    print(f"  [2] Browser Cookies (Bypass Age/Login Walls)  : {Fore.GREEN}{STATE.config.get('browser_cookies', 'none').upper()}{Style.RESET_ALL}")
    print(f"  [3] Subtitles Mode                            : {Fore.GREEN}{STATE.config.get('subtitles_mode', 'off').upper()}{Style.RESET_ALL}")
    print(f"  [4] Speed Limit                               : {Fore.YELLOW}{STATE.config.get('speed_limit', 'none').upper()}{Style.RESET_ALL}")
    print(f"  [5] Windows Toast Notifications               : {Fore.GREEN if STATE.config.get('desktop_notifications', True) else Fore.RED}{'ON' if STATE.config.get('desktop_notifications', True) else 'OFF'}{Style.RESET_ALL}")
    print(f"  [6] Sound Effects (Chimes)                    : {Fore.GREEN if STATE.config.get('sound_effects') else Fore.RED}{'ON' if STATE.config.get('sound_effects') else 'OFF'}{Style.RESET_ALL}")
    print(f"  [7] SponsorBlock (Auto-skip sponsored segments): {Fore.GREEN if STATE.config.get('sponsorblock') else Fore.RED}{'ON' if STATE.config.get('sponsorblock') else 'OFF'}{Style.RESET_ALL}")
    print(f"  [8] Media Filter (Known sites only / All URLs): {Fore.GREEN if STATE.config.get('media_filter_only') else Fore.YELLOW}{'STRICT' if STATE.config.get('media_filter_only') else 'ALLOW ANY URL'}{Style.RESET_ALL}")
    print(f"  [b] Back\n")

    choice = input(f"{Fore.CYAN}Enter setting number to toggle/change: {Style.RESET_ALL}").strip().lower()
    if choice == "1":
        toggle_quality_prompt()
    elif choice == "2":
        select_browser_cookies()
    elif choice == "3":
        modes = ["off", "en", "all"]
        cur = STATE.config.get("subtitles_mode", "off")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "off"
        STATE.config["subtitles_mode"] = nxt
        print(f"{Fore.GREEN}[✓] Subtitles set to: {nxt.upper()}{Style.RESET_ALL}\n")
    elif choice == "4":
        lim = input(f"{Fore.YELLOW}Enter speed limit (e.g. 5M, 10M, 2M, or 'off'): {Style.RESET_ALL}").strip().lower()
        STATE.config["speed_limit"] = "none" if lim in ("off", "none", "", "0") else lim
        print(f"{Fore.GREEN}[✓] Speed limit set to: {STATE.config['speed_limit'].upper()}{Style.RESET_ALL}\n")
    elif choice == "5":
        STATE.config["desktop_notifications"] = not STATE.config.get("desktop_notifications", True)
        print(f"{Fore.GREEN}[✓] Desktop notifications set to: {STATE.config['desktop_notifications']}{Style.RESET_ALL}\n")
    elif choice == "6":
        STATE.config["sound_effects"] = not STATE.config.get("sound_effects", True)
        print(f"{Fore.GREEN}[✓] Sound effects set to: {STATE.config['sound_effects']}{Style.RESET_ALL}\n")
    elif choice == "7":
        STATE.config["sponsorblock"] = not STATE.config.get("sponsorblock", False)
        print(f"{Fore.GREEN}[✓] SponsorBlock set to: {STATE.config['sponsorblock']}{Style.RESET_ALL}\n")
    elif choice == "8":
        STATE.config["media_filter_only"] = not STATE.config.get("media_filter_only", True)
        print(f"{Fore.GREEN}[✓] Media filter set to: {'STRICT' if STATE.config['media_filter_only'] else 'ANY URL'}{Style.RESET_ALL}\n")
    STATE.save_config()


def update_ytdlp():
    """Run yt-dlp update command"""
    print(f"\n{Fore.CYAN}[*] Checking for yt-dlp updates...{Style.RESET_ALL}")
    try:
        ytdlp_cmd = str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp")
        res = subprocess.run([ytdlp_cmd, "-U"])
        STATE.update_available = None
        if res.returncode == 0:
            print(f"{Fore.GREEN}[✓] Update process finished successfully.{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.YELLOW}[!] yt-dlp update exited with code {res.returncode}.{Style.RESET_ALL}\n")
    except Exception as e:
        print(f"{Fore.RED}[!] Update failed: {e}{Style.RESET_ALL}\n")


def cmd_play(raw: str):
    """Instant search & download top YouTube track as 320kbps MP3: play <query>"""
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ 🎵 Instant YouTube Audio Search ═══{Style.RESET_ALL}")
        query = input(f"{Fore.WHITE}Enter artist, song, or video title >>> {Style.RESET_ALL}").strip().strip("\"'")

    if not query:
        print(f"{Fore.LIGHTBLACK_EX}[!] Cancelled.{Style.RESET_ALL}\n")
        return

    search_target = f"ytsearch1:{query}"
    print(f"\n{Fore.GREEN}[🔍] Searching & downloading top track:{Style.RESET_ALL} {Fore.CYAN}{query}{Style.RESET_ALL}")
    STATE.enqueue_job({
        "url": search_target,
        "preset_override": 7,
        "force_audio": True,
        "display_title": f"🎵 {query.title()}",
        "needs_quality_prompt": False
    })
    print(f"{Fore.LIGHTBLACK_EX}    Queued top YouTube match as 320kbps MP3 with album artwork.{Style.RESET_ALL}\n")


def cmd_search(raw: str):
    """Search YouTube and interactively pick from top 5 results: yt <query> or search <query>"""
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ 🔎 Search YouTube Videos ═══{Style.RESET_ALL}")
        query = input(f"{Fore.WHITE}Search query >>> {Style.RESET_ALL}").strip().strip("\"'")

    if not query:
        print(f"{Fore.LIGHTBLACK_EX}[!] Cancelled.{Style.RESET_ALL}\n")
        return

    print(f"\n{Fore.CYAN}[🔍] Searching YouTube for:{Style.RESET_ALL} {Fore.WHITE}\"{query}\"...{Style.RESET_ALL}")
    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--dump-json",
        "--flat-playlist",
        "--default-search", "ytsearch5",
        query
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
        items = []
        for line in res.stdout.strip().split("\n"):
            if line.strip():
                try:
                    items.append(json.loads(line.strip()))
                except Exception:
                    pass

        if not items:
            print(f"{Fore.RED}[!] No results found for \"{query}\".{Style.RESET_ALL}\n")
            return

        print(f"\n{Fore.CYAN}═══ 🔎 YOUTUBE RESULTS FOR: {Fore.WHITE}\"{query}\"{Fore.CYAN} ═══{Style.RESET_ALL}")
        valid_keys = {"s"}
        for idx, it in enumerate(items, 1):
            t = it.get("title", "Unknown Title")
            d_sec = it.get("duration")
            if d_sec:
                m, s = divmod(int(d_sec), 60)
                h, m = divmod(m, 60)
                dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            else:
                dur_str = "--:--"
            ch = it.get("channel") or it.get("uploader") or "Unknown"
            valid_keys.add(str(idx))
            print(f"  {Fore.LIGHTGREEN_EX}[{idx}]{Style.RESET_ALL} {Fore.WHITE}{t[:65]}{Style.RESET_ALL}")
            print(f"      {Fore.LIGHTBLACK_EX}Duration: {dur_str} | Channel: {ch}{Style.RESET_ALL}")

        valid_keys.add("a")
        print(f"\n  {Fore.YELLOW}[a] Download ALL {len(items)} results{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}[s] Skip / Cancel{Style.RESET_ALL}\n")

        choice = read_single_choice(valid_keys, default_val="s")
        if choice == "s":
            print(f"{Fore.LIGHTBLACK_EX}[!] Search cancelled.{Style.RESET_ALL}\n")
            return

        if choice == "a":
            for it in items:
                v_id = it.get("id") or it.get("url")
                v_url = f"https://www.youtube.com/watch?v={v_id}" if len(str(v_id)) == 11 else str(v_id)
                STATE.enqueue_job({
                    "url": v_url,
                    "display_title": it.get("title"),
                    "needs_quality_prompt": False
                })
            print(f"{Fore.GREEN}[+] Queued all {len(items)} videos!{Style.RESET_ALL}\n")
        elif choice.isdigit() and 1 <= int(choice) <= len(items):
            pick = items[int(choice) - 1]
            v_id = pick.get("id") or pick.get("url")
            v_url = f"https://www.youtube.com/watch?v={v_id}" if len(str(v_id)) == 11 else str(v_id)
            STATE.enqueue_job({
                "url": v_url,
                "display_title": pick.get("title"),
                "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
            })
            print(f"{Fore.GREEN}[+] Queued:{Style.RESET_ALL} {pick.get('title')}\n")

    except Exception as e:
        print(f"{Fore.RED}[!] Search error: {e}{Style.RESET_ALL}\n")


def cmd_inspect(raw: str):
    """Inspect video metadata, available resolutions, audio streams and subs: info <url>"""
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        url_in = parts[1].strip().strip("\"'")
    else:
        print(f"\n{Fore.CYAN}═══ ℹ️ Media Information Inspector ═══{Style.RESET_ALL}")
        url_in = input(f"{Fore.WHITE}Paste Media URL >>> {Style.RESET_ALL}").strip().strip("\"'")

    if not url_in or not is_valid_media_url(url_in):
        print(f"{Fore.RED}[!] Invalid media URL.{Style.RESET_ALL}\n")
        return

    url = extract_media_url(url_in) or url_in
    print(f"\n{Fore.CYAN}[*] Fetching metadata for:{Style.RESET_ALL} {Fore.WHITE}{url}...{Style.RESET_ALL}")

    cmd = [
        str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"),
        "--dump-single-json",
        "--no-playlist",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        if res.returncode != 0 or not res.stdout.strip():
            print(f"{Fore.RED}[!] Could not retrieve video info. ({res.stderr.strip()[:100]}){Style.RESET_ALL}\n")
            return

        info = json.loads(res.stdout)
        title = info.get("title", "Unknown")
        uploader = info.get("uploader") or info.get("channel") or "Unknown"
        duration_sec = info.get("duration")
        if duration_sec:
            m, s = divmod(int(duration_sec), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        else:
            dur_str = "--:--"

        views = f"{info.get('view_count'):,}" if info.get("view_count") else "N/A"
        up_date = info.get("upload_date")
        date_str = f"{up_date[:4]}-{up_date[4:6]}-{up_date[6:]}" if up_date and len(up_date) == 8 else "N/A"

        formats = info.get("formats", [])
        heights = sorted(list({f.get("height") for f in formats if f.get("height")}), reverse=True)
        res_tags = []
        for h in heights[:6]:
            if h >= 2160:
                res_tags.append("4K (2160p)")
            elif h >= 1440:
                res_tags.append("2K (1440p)")
            elif h >= 1080:
                res_tags.append("1080p")
            elif h >= 720:
                res_tags.append("720p")
            elif h >= 480:
                res_tags.append("480p")
            elif h >= 360:
                res_tags.append("360p")
        res_str = ", ".join(res_tags) if res_tags else "Direct Stream"

        acodecs = sorted(list({f.get("acodec") for f in formats if f.get("acodec") and f.get("acodec") != "none"}))
        clean_audio = [a.split(".")[0] for a in acodecs]
        audio_str = ", ".join(sorted(list(set(clean_audio)))) if clean_audio else "Standard Audio"

        sub_keys = list(info.get("subtitles", {}).keys())
        sub_str = ", ".join(sub_keys[:6]) + ("..." if len(sub_keys) > 6 else "") if sub_keys else "None available"

        print(f"\n{Fore.CYAN}┌───────────────────────────────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Style.BRIGHT}{Fore.YELLOW}ℹ️  MEDIA SPECIFICATIONS{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Title    :{Style.RESET_ALL} {Fore.LIGHTGREEN_EX}{title[:58]}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Channel  :{Style.RESET_ALL} {Fore.CYAN}{uploader}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Duration :{Style.RESET_ALL} {dur_str}  |  {Fore.WHITE}Views:{Style.RESET_ALL} {views}  |  {Fore.WHITE}Date:{Style.RESET_ALL} {date_str}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Formats  :{Style.RESET_ALL} {Fore.LIGHTMAGENTA_EX}{res_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Audio    :{Style.RESET_ALL} {Fore.LIGHTBLUE_EX}{audio_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Fore.WHITE}Subs     :{Style.RESET_ALL} {Fore.YELLOW}{sub_str}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}└───────────────────────────────────────────────────────────────┘{Style.RESET_ALL}")

        print(f"{Fore.WHITE}Quick Action:{Style.RESET_ALL} [1] Best Video [2] 1080p [3] MP3 Audio [s] Skip")
        choice = read_single_choice({"1", "2", "3", "s"}, default_val="s")
        if choice == "1":
            STATE.enqueue_job({"url": url, "preset_override": 1, "needs_quality_prompt": False})
            print(f"{Fore.GREEN}[+] Queued in Best Available Quality!{Style.RESET_ALL}\n")
        elif choice == "2":
            STATE.enqueue_job({"url": url, "preset_override": 3, "needs_quality_prompt": False})
            print(f"{Fore.GREEN}[+] Queued in 1080p Full HD!{Style.RESET_ALL}\n")
        elif choice == "3":
            STATE.enqueue_job({"url": url, "preset_override": 7, "force_audio": True, "needs_quality_prompt": False})
            print(f"{Fore.GREEN}[+] Queued as 320kbps MP3 Audio!{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.LIGHTBLACK_EX}Skipped.{Style.RESET_ALL}\n")

    except Exception as e:
        print(f"{Fore.RED}[!] Inspector error: {e}{Style.RESET_ALL}\n")


def cmd_sponsorblock(raw: str = ""):
    """Handle SponsorBlock toggle: sb [on/off]"""
    parts = raw.split()
    if len(parts) > 1:
        val = parts[1].lower()
        if val in ("on", "1", "enable", "true"):
            STATE.config["sponsorblock"] = True
        elif val in ("off", "0", "disable", "false"):
            STATE.config["sponsorblock"] = False
    else:
        STATE.config["sponsorblock"] = not STATE.config.get("sponsorblock", False)
    STATE.save_config()
    status = "ON (Auto-skips sponsors & self-promos)" if STATE.config["sponsorblock"] else "OFF"
    color = Fore.GREEN if STATE.config["sponsorblock"] else Fore.RED
    print(f"\n{color}[✓] SponsorBlock set to: {status}{Style.RESET_ALL}\n")


def cmd_spotify(raw: str):
    """Handle 'spotify <url>' or interactive Spotify downloader prompt"""
    parts = raw.split(maxsplit=1)
    if len(parts) > 1:
        enqueue_spotify_download(parts[1].strip("\"'"))
    else:
        print(f"\n{Fore.CYAN}═══ 🎵 Spotify Studio Downloader ═══{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Paste Spotify track, album, or playlist URL:{Style.RESET_ALL}")
        s_url = input("Spotify URL >>> ").strip().strip("\"'")
        if s_url:
            enqueue_spotify_download(s_url)
        else:
            print(f"{Fore.LIGHTBLACK_EX}[!] Cancelled.{Style.RESET_ALL}\n")


def cmd_cookies(raw: str):
    """Handle 'cookies <browser|off>' command"""
    browser = raw.split(maxsplit=1)[1].strip().lower()
    if browser in ("off", "none", "disable"):
        STATE.config["browser_cookies"] = "none"
    else:
        STATE.config["browser_cookies"] = browser
    STATE.save_config()


def cmd_site(raw: str):
    """Handle active streaming site command: site [url_or_alias]"""
    parts = raw.split(maxsplit=1)
    if len(parts) == 1:
        cur_site = getattr(STATE, "last_seen_website", None) or STATE.config.get("default_stream_referer", "https://movy.sx/")
        print(f"\n{Fore.CYAN}═══ 🌐 ACTIVE STREAMING SITE ═══{Style.RESET_ALL}")
        print(f"Current Auto-Referer: {Fore.GREEN}{cur_site}{Style.RESET_ALL}")
        print("Quick Presets:")
        print(f"  {Fore.YELLOW}site movy{Style.RESET_ALL}       -> https://movy.sx/")
        print(f"  {Fore.YELLOW}site cinejoy{Style.RESET_ALL}    -> https://cinejoy.pk/")
        print(f"  {Fore.YELLOW}site bingebox{Style.RESET_ALL}   -> https://bingebox.ac/")
        print(f"  {Fore.YELLOW}site popcorn{Style.RESET_ALL}    -> https://popcornmovies.ac/")
        print(f"  {Fore.YELLOW}site <any_site>{Style.RESET_ALL}  -> any custom site URL\n")
    else:
        arg = parts[1].strip().lower()
        alias_map = {
            "movy": "https://movy.sx/",
            "cinejoy": "https://cinejoy.pk/",
            "bingebox": "https://bingebox.ac/",
            "popcorn": "https://popcornmovies.ac/",
            "popcornmovies": "https://popcornmovies.ac/",
            "vidsrc": "https://vidsrc.to/",
        }
        new_site = alias_map.get(arg)
        if not new_site:
            new_site = arg if arg.startswith(("http://", "https://")) else f"https://{arg}/"
            if not new_site.endswith("/"):
                new_site += "/"
        STATE.last_seen_website = new_site
        STATE.config["default_stream_referer"] = new_site
        STATE.save_config()
        print(f"{Fore.GREEN}[✓] Active streaming site set to:{Style.RESET_ALL} {new_site}\n")


def cmd_ref(raw: str):
    """Handle referer streaming helper command: ref [referer] [stream_url]"""
    tokens = raw.split(maxsplit=2)
    ref_presets = {
        "1": "https://movy.sx/",
        "2": "https://cinejoy.pk/",
        "3": "https://bingebox.ac/",
        "4": "https://popcornmovies.ac/",
        "5": "https://vidsrc.to/"
    }

    def _clean_ref(val: str) -> str:
        val = val.strip().strip("\"'")
        if not val or val == "1":
            return ref_presets["1"]
        if val in ref_presets:
            return ref_presets[val]
        if not val.startswith(("http://", "https://")):
            return "https://" + val
        return val

    if len(tokens) == 1:
        print(f"\n{Fore.CYAN}═══ ☁️ Cloud Server / Embed Referer Helper ═══{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Choose a quick preset or type ANY streaming website:{Style.RESET_ALL}")
        print(f"  {Fore.LIGHTGREEN_EX}[1]{Style.RESET_ALL} https://movy.sx/ {Fore.LIGHTBLACK_EX}(Default - press Enter){Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}[2]{Style.RESET_ALL} https://cinejoy.pk/")
        print(f"  {Fore.YELLOW}[3]{Style.RESET_ALL} https://bingebox.ac/")
        print(f"  {Fore.YELLOW}[4]{Style.RESET_ALL} https://popcornmovies.ac/")
        print(f"  {Fore.YELLOW}[5]{Style.RESET_ALL} https://vidsrc.to/")
        print(f"  {Fore.CYAN}[Any]{Style.RESET_ALL} Type any website URL (e.g. {Fore.WHITE}netflix.com{Style.RESET_ALL}, {Fore.WHITE}site.to{Style.RESET_ALL})")
        ref_input = input("Referer [1-5 or custom] >>> ").strip()
        ref_url = _clean_ref(ref_input)

        print(f"{Fore.WHITE}Paste stream URL (.m3u8):{Style.RESET_ALL}")
        stream_input = input("Stream URL >>> ").strip().strip("\"'")
        if stream_input:
            media_url = extract_media_url(stream_input) or stream_input
            with STATE.lock:
                STATE.download_queue.append({
                    "url": media_url,
                    "referer": ref_url,
                    "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
                })
            print(f"{Fore.GREEN}[+] Queued with Referer [{ref_url}]:{Style.RESET_ALL} {media_url}\n")
        else:
            print(f"{Fore.LIGHTBLACK_EX}[!] Cancelled.{Style.RESET_ALL}\n")

    elif len(tokens) == 2:
        target_url = tokens[1].strip("\"'")
        print(f"\n{Fore.WHITE}Choose a quick preset or type ANY streaming website:{Style.RESET_ALL}")
        print(f"  {Fore.LIGHTGREEN_EX}[1]{Style.RESET_ALL} https://movy.sx/ {Fore.LIGHTBLACK_EX}(Default - press Enter){Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}[2]{Style.RESET_ALL} https://cinejoy.pk/")
        print(f"  {Fore.YELLOW}[3]{Style.RESET_ALL} https://bingebox.ac/")
        print(f"  {Fore.YELLOW}[4]{Style.RESET_ALL} https://popcornmovies.ac/")
        print(f"  {Fore.YELLOW}[5]{Style.RESET_ALL} https://vidsrc.to/")
        print(f"  {Fore.CYAN}[Any]{Style.RESET_ALL} Type any website URL:")
        ref_input = input("Referer [1-5 or custom] >>> ").strip()
        ref_url = _clean_ref(ref_input)

        media_url = extract_media_url(target_url) or target_url
        with STATE.lock:
            STATE.download_queue.append({
                "url": media_url,
                "referer": ref_url,
                "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
            })
        print(f"{Fore.GREEN}[+] Queued with Referer [{ref_url}]:{Style.RESET_ALL} {media_url}\n")

    elif len(tokens) >= 3:
        arg1 = tokens[1].strip("\"'")
        arg2 = tokens[2].strip("\"'")

        if ".m3u8" in arg1.lower() or "vd/" in arg1.lower() or "top/" in arg1.lower():
            media_url = extract_media_url(arg1) or arg1
            ref_url = _clean_ref(arg2)
        else:
            ref_url = _clean_ref(arg1)
            media_url = extract_media_url(arg2) or arg2

        with STATE.lock:
            STATE.download_queue.append({
                "url": media_url,
                "referer": ref_url,
                "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
            })
        print(f"{Fore.GREEN}[+] Queued with Referer [{ref_url}]:{Style.RESET_ALL} {media_url}")


def cmd_limit(raw: str):
    """Handle speed limit shortcut: limit 5M / limit off"""
    lim = raw.split(maxsplit=1)[1].strip().lower()
    STATE.config["speed_limit"] = "none" if lim in ("off", "none", "0") else lim
    STATE.save_config()
    print(f"{Fore.GREEN}[✓] Speed limit set to: {STATE.config['speed_limit'].upper()}{Style.RESET_ALL}")


def cmd_trim(raw: str):
    """Handle video trimming: trim <start>-<end> <URL>"""
    tokens = raw.split(maxsplit=2)
    if len(tokens) >= 3 and is_valid_media_url(tokens[2]):
        time_range = tokens[1]
        url = extract_media_url(tokens[2])
        with STATE.lock:
            STATE.download_queue.append({
                "url": url,
                "download_section": time_range,
                "needs_quality_prompt": False
            })
        print(f"{Fore.GREEN}[+] Queued clip [{time_range}]:{Style.RESET_ALL} {url}")
    else:
        print(f"{Fore.RED}[!] Usage: trim <start>-<end> <URL>  (e.g. trim 01:15-02:30 https://...){Style.RESET_ALL}")


def cmd_items(raw: str):
    """Handle playlist selective items: items 1-5 <URL>"""
    tokens = raw.split(maxsplit=2)
    if len(tokens) >= 3 and is_valid_media_url(tokens[2]):
        items_range = tokens[1]
        url = extract_media_url(tokens[2])
        with STATE.lock:
            STATE.download_queue.append({
                "url": url,
                "playlist_items": items_range,
                "needs_quality_prompt": False
            })
        print(f"{Fore.GREEN}[+] Queued playlist tracks [{items_range}]:{Style.RESET_ALL} {url}")
    else:
        print(f"{Fore.RED}[!] Usage: items <range> <URL>  (e.g. items 1-5 https://...){Style.RESET_ALL}")


QUALITY_SHORTCUT_MAP = {
    "1080p": (3, False, "1080p Full HD"),
    "1080": (3, False, "1080p Full HD"),
    "720p": (4, False, "720p HD"),
    "720": (4, False, "720p HD"),
    "4k": (1, False, "4K / Best Quality"),
    "2160p": (1, False, "4K / Best Quality"),
    "best": (1, False, "4K / Best Quality"),
    "1440p": (2, False, "1440p 2K"),
    "2k": (2, False, "1440p 2K"),
    "480p": (5, False, "480p SD"),
    "480": (5, False, "480p SD"),
    "360p": (6, False, "360p Data Saver"),
    "360": (6, False, "360p Data Saver"),
    "mp3": (7, True, "MP3 Audio (320kbps)"),
    "audio": (7, True, "MP3 Audio (320kbps)"),
    "m4a": (8, True, "M4A Audio (Original AAC)"),
    "aac": (8, True, "M4A Audio (Original AAC)"),
    "flac": (9, False, "Lossless FLAC"),
    "opus": (10, False, "OPUS Audio"),
    "wav": (11, False, "Raw WAV Audio"),
}


def handle_preset_shortcut(keyword: str, arg: str) -> bool:
    """Handle resolution and audio shortcut commands (1080p, 720p, mp3, flac, etc.)"""
    if keyword not in QUALITY_SHORTCUT_MAP:
        return False
    if not arg or not is_valid_media_url(arg):
        print(f"{Fore.RED}[!] Usage: {keyword} <URL>{Style.RESET_ALL}")
        return True

    preset_id, force_audio, label = QUALITY_SHORTCUT_MAP[keyword]
    url = extract_media_url(arg)
    job = STATE.enqueue_job({
        "url": url,
        "preset_override": preset_id,
        "force_audio": force_audio,
        "needs_quality_prompt": False
    })
    ref_txt = f" {Fore.LIGHTBLACK_EX}(Auto-Referer: {job.get('referer')}){Style.RESET_ALL}" if job.get("referer") else ""
    print(f"{Fore.GREEN}[+] Queued in {label}:{Style.RESET_ALL} {url}{ref_txt}")
    return True


def handle_subs_command(raw: str):
    """Handle subtitles command: subs <url> or subs <lang> <url> or subs list <url>"""
    tokens = raw.split(maxsplit=2)
    if len(tokens) == 1:
        modes = ["off", "en", "all"]
        cur = STATE.config.get("subtitles_mode", "off")
        nxt = modes[(modes.index(cur) + 1) % len(modes)] if cur in modes else "off"
        STATE.config["subtitles_mode"] = nxt
        STATE.save_config()
        print(f"\n{Fore.GREEN}[✓] Subtitles mode set to: {nxt.upper()}{Style.RESET_ALL}\n")
        return

    if len(tokens) == 2:
        arg = tokens[1].strip("\"'")
        if is_valid_media_url(arg):
            url = extract_media_url(arg)
            with STATE.lock:
                STATE.download_queue.append({"url": url, "force_subs": True, "needs_quality_prompt": False})
            print(f"{Fore.GREEN}[+] Queued with subtitles:{Style.RESET_ALL} {url}")
        else:
            print(f"{Fore.RED}[!] Usage: subs <URL> or subs <lang> <URL> (e.g. subs en URL){Style.RESET_ALL}")
        return

    if len(tokens) >= 3:
        sub_arg = tokens[1].lower().strip()
        url_arg = tokens[2].strip("\"'")
        if sub_arg == "list":
            if is_valid_media_url(url_arg):
                url = extract_media_url(url_arg)
                print(f"\n{Fore.CYAN}[*] Fetching available subtitles for: {url}...{Style.RESET_ALL}")
                subprocess.run([str(YTDLP_EXE if YTDLP_EXE.exists() else "yt-dlp"), "--list-subs", url])
            else:
                print(f"{Fore.RED}[!] Invalid media URL: {url_arg}{Style.RESET_ALL}")
            return

        if is_valid_media_url(url_arg):
            url = extract_media_url(url_arg)
            with STATE.lock:
                STATE.download_queue.append({
                    "url": url,
                    "force_subs": True,
                    "sub_lang": sub_arg,
                    "needs_quality_prompt": False
                })
            print(f"{Fore.GREEN}[+] Queued with [{sub_arg.upper()}] subtitles:{Style.RESET_ALL} {url}")
        else:
            print(f"{Fore.RED}[!] Invalid media URL: {url_arg}{Style.RESET_ALL}")


def handle_formats_command(arg: str):
    """Handle format inspector command: f <URL> or formats <URL>"""
    if not arg or not is_valid_media_url(arg):
        print(f"{Fore.RED}[!] Usage: f <URL> or formats <URL>{Style.RESET_ALL}")
        return
    url = extract_media_url(arg)
    custom_fmt = inspect_and_pick_formats(url)
    if custom_fmt:
        with STATE.lock:
            STATE.download_queue.append({"url": url, "custom_format_str": custom_fmt, "needs_quality_prompt": False})
        print(f"{Fore.GREEN}[+] Queued with custom format ({custom_fmt}):{Style.RESET_ALL} {url}")


def handle_list_command(arg: str):
    """Handle full playlist download command: list <URL>"""
    if not arg or not is_valid_media_url(arg):
        print(f"{Fore.RED}[!] Usage: list <URL>{Style.RESET_ALL}")
        return
    url = extract_media_url(arg)
    with STATE.lock:
        STATE.download_queue.append({
            "url": url,
            "force_playlist": True,
            "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
        })
    print(f"{Fore.GREEN}[+] Queued entire playlist:{Style.RESET_ALL} {url}")


def handle_batch_file(file_path: Path):
    """Handle drag-and-drop or path of a .txt file containing URLs"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        valid_count = 0
        with STATE.lock:
            for u in urls:
                if is_valid_media_url(u):
                    STATE.download_queue.append({"url": extract_media_url(u), "needs_quality_prompt": False})
                    valid_count += 1
        print(f"{Fore.GREEN}[✓] Loaded {valid_count} URLs from {file_path.name} into download queue!{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[!] Error reading file: {e}{Style.RESET_ALL}")


def handle_raw_urls(raw: str):
    """Handle direct URLs, space-separated URL batches, or streaming site addresses"""
    lower_raw = raw.strip().lower()
    matched_site = None
    for s_domain, s_url in KNOWN_STREAMING_DOMAINS.items():
        if s_domain in lower_raw and not any(ext in lower_raw for ext in (".mp4", ".m3u8", ".webm", ".mkv", ".mpd", ".ts")):
            matched_site = s_url
            break
    if matched_site:
        STATE.last_seen_website = matched_site
        STATE.config["default_stream_referer"] = matched_site
        STATE.save_config()
        print(f"\n{Fore.GREEN}[⚡] Active Streaming Site updated to:{Style.RESET_ALL} {Fore.CYAN}{matched_site}{Style.RESET_ALL}")
        print(f"{Fore.LIGHTYELLOW_EX}    Ready! Stream links (.m3u8) will automatically use this referer.{Style.RESET_ALL}\n")
        return

    tokens = raw.split()
    added = 0
    for tok in tokens:
        if is_spotify_url(tok):
            enqueue_spotify_download(tok)
            added += 1
        elif is_valid_media_url(tok) or GENERIC_URL_REGEX.match(tok):
            m_url = extract_media_url(tok)
            job = STATE.enqueue_job({
                "url": m_url,
                "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
            })
            ref_txt = f" {Fore.LIGHTBLACK_EX}(Auto-Referer: {job.get('referer')}){Style.RESET_ALL}" if job.get("referer") else ""
            print(f"{Fore.GREEN}[+] Queued for download:{Style.RESET_ALL} {m_url}{ref_txt}")
            added += 1
    if added == 0:
        print(f"{Fore.RED}[!] Could not extract valid media URL.{Style.RESET_ALL}")


STATIC_COMMANDS = {
    "q": lambda: sys.exit(0),
    "exit": lambda: sys.exit(0),
    "quit": lambda: sys.exit(0),
    "c": toggle_clipboard_mode,
    "clip": toggle_clipboard_mode,
    "p": select_preset_menu,
    "preset": select_preset_menu,
    "qmode": toggle_quality_prompt,
    "ask": toggle_quality_prompt,
    "quality": toggle_quality_prompt,
    "o": open_downloads_folder,
    "open": open_downloads_folder,
    "d": change_downloads_folder,
    "dir": change_downloads_folder,
    "h": show_history,
    "history": show_history,
    "s": toggle_settings_menu,
    "settings": toggle_settings_menu,
    "sb": cmd_sponsorblock,
    "sponsorblock": cmd_sponsorblock,
    "u": update_ytdlp,
    "update": update_ytdlp,
    "cls": print_banner,
    "clear": print_banner,
    "?": print_banner,
    "help": print_banner,
}


def handle_user_command(user_input: str):
    """Process an entered line from the terminal prompt using clean command dispatch"""
    raw = user_input.strip()
    if not raw:
        return

    cmd_lower = raw.lower()

    if cmd_lower in STATIC_COMMANDS:
        if cmd_lower in ("q", "exit", "quit"):
            print(f"{Fore.YELLOW}Exiting YT-DLP Terminal. Goodbye!{Style.RESET_ALL}")
            STATE.stop_requested = True
        STATIC_COMMANDS[cmd_lower]()
        return

    first_word = raw.split()[0].lower() if " " in raw else raw.lower()
    arg_part = raw.split(maxsplit=1)[1] if " " in raw else ""

    if first_word in ("play", "song", "music"):
        cmd_play(raw)
    elif first_word in ("yt", "search", "find"):
        cmd_search(raw)
    elif first_word in ("info", "inspect", "details"):
        cmd_inspect(raw)
    elif first_word in ("sb", "sponsorblock"):
        cmd_sponsorblock(raw)
    elif first_word in ("h", "history"):
        show_history(arg_part)
    elif first_word == "spotify":
        cmd_spotify(raw)
    elif first_word == "cookies":
        cmd_cookies(raw)
    elif first_word in ("site", "website"):
        cmd_site(raw)
    elif first_word in ("ref", "referer"):
        cmd_ref(raw)
    elif first_word in ("limit", "speed"):
        cmd_limit(raw)
    elif first_word in ("trim", "clip") and any(ch.isdigit() for ch in arg_part):
        cmd_trim(raw)
    elif first_word in ("items", "range"):
        cmd_items(raw)
    elif handle_preset_shortcut(first_word, arg_part):
        pass
    elif first_word == "subs":
        handle_subs_command(raw)
    elif first_word in ("f", "formats"):
        handle_formats_command(arg_part)
    elif first_word == "list":
        handle_list_command(arg_part)
    elif Path(raw.strip('"\'')).is_file() and raw.strip('"\'').lower().endswith(".txt"):
        handle_batch_file(Path(raw.strip('"\'')))
    elif is_spotify_url(raw):
        enqueue_spotify_download(raw.strip("\"'"))
    elif is_valid_media_url(raw) or GENERIC_URL_REGEX.search(raw):
        handle_raw_urls(raw)
    else:
        print(f"{Fore.RED}[!] Unrecognized command or invalid URL.{Style.RESET_ALL}")
        print(f"{Fore.LIGHTBLACK_EX}Type 'help' for command list, or paste a valid link directly.{Style.RESET_ALL}")


def process_pending_events(prompt: str, line_buffer: list = None, interactive_confirm: bool = True) -> bool:
    """
    Checks and processes pending clipboard prompts or queued download jobs.
    Returns True if an event was handled, False otherwise.
    """
    with STATE.lock:
        has_job = bool(STATE.download_queue)
        pending_prompt = STATE.pending_prompt_url
        pending_ref = getattr(STATE, "pending_prompt_ref", None)
        if pending_prompt:
            STATE.pending_prompt_url = None
            STATE.pending_prompt_ref = None

    if pending_prompt:
        if line_buffer is not None:
            sys.stdout.write("\r" + " " * (len(prompt) + len(line_buffer) + 5) + "\r")
        else:
            sys.stdout.write("\n")
        sys.stdout.flush()

        print(f"{Fore.LIGHTYELLOW_EX}[?] Clipboard detected link:{Style.RESET_ALL} {Fore.CYAN}{pending_prompt}{Style.RESET_ALL}")

        do_download = True
        if interactive_confirm and sys.stdin.isatty():
            sys.stdout.write(f"{Fore.YELLOW}    Download now? ([Enter] to Download, [s] to Skip): {Style.RESET_ALL}")
            sys.stdout.flush()
            ans = sys.stdin.readline().strip().lower()
            if ans in ("s", "skip", "n", "no"):
                do_download = False
                print(f"{Fore.LIGHTBLACK_EX}    Skipped.{Style.RESET_ALL}")

        if do_download:
            if is_spotify_url(pending_prompt):
                enqueue_spotify_download(pending_prompt)
            else:
                STATE.enqueue_job({
                    "url": pending_prompt,
                    "referer": pending_ref,
                    "needs_quality_prompt": STATE.config.get("ask_quality_each_time", True)
                })

        sys.stdout.write(prompt + ("".join(line_buffer) if line_buffer else ""))
        sys.stdout.flush()
        return True

    if has_job:
        if line_buffer is not None:
            sys.stdout.write("\r" + " " * (len(prompt) + len(line_buffer) + 5) + "\r")
        sys.stdout.flush()

        with STATE.lock:
            job = STATE.download_queue.popleft()
            STATE.is_downloading = True

        if job.get("needs_quality_prompt", False):
            chosen_preset, custom_fmt = prompt_video_quality(job["url"], referer=job.get("referer"))
            if chosen_preset is None and custom_fmt is None:
                with STATE.lock:
                    STATE.is_downloading = False
                sys.stdout.write(prompt + ("".join(line_buffer) if line_buffer else ""))
                sys.stdout.flush()
                return True
            job["preset_override"] = chosen_preset
            job["custom_format_str"] = custom_fmt

        execute_download(job)

        with STATE.lock:
            STATE.is_downloading = False

        sys.stdout.write(prompt + ("".join(line_buffer) if line_buffer else ""))
        sys.stdout.flush()
        return True

    return False


COMMAND_HISTORY = []


def get_nonblocking_line(prompt: str) -> str:
    """Non-blocking line reader using msvcrt with Up/Down arrow command history navigation"""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line_buffer = []
    history_idx = len(COMMAND_HISTORY)
    saved_current = ""

    def _replace_line(new_text: str):
        nonlocal line_buffer
        sys.stdout.write("\r" + " " * (len(prompt) + len(line_buffer) + 5) + "\r")
        line_buffer = list(new_text)
        sys.stdout.write(prompt + new_text)
        sys.stdout.flush()

    while not STATE.stop_requested:
        if process_pending_events(prompt, line_buffer=line_buffer, interactive_confirm=True):
            continue

        if HAS_MSVCRT and sys.stdin.isatty():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    line_str = "".join(line_buffer)
                    if line_str.strip():
                        if not COMMAND_HISTORY or COMMAND_HISTORY[-1] != line_str.strip():
                            COMMAND_HISTORY.append(line_str.strip())
                    return line_str
                elif ch == "\x08":  # Backspace
                    if line_buffer:
                        line_buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                elif ch == "\x03":  # Ctrl+C
                    print(f"\n{Fore.YELLOW}Cancelled line.{Style.RESET_ALL}")
                    return ""
                elif ch == "\x16":  # Ctrl+V
                    pasted = get_clipboard_text()
                    for c in pasted:
                        if c not in ("\r", "\n"):
                            line_buffer.append(c)
                            sys.stdout.write(c)
                    sys.stdout.flush()
                elif ch in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        code = msvcrt.getwch()
                        if code == "H":  # Up Arrow
                            if COMMAND_HISTORY:
                                if history_idx == len(COMMAND_HISTORY):
                                    saved_current = "".join(line_buffer)
                                if history_idx > 0:
                                    history_idx -= 1
                                    _replace_line(COMMAND_HISTORY[history_idx])
                        elif code == "P":  # Down Arrow
                            if history_idx < len(COMMAND_HISTORY) - 1:
                                history_idx += 1
                                _replace_line(COMMAND_HISTORY[history_idx])
                            elif history_idx == len(COMMAND_HISTORY) - 1:
                                history_idx += 1
                                _replace_line(saved_current)
                elif ord(ch) >= 32:
                    line_buffer.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
            else:
                time.sleep(0.04)
        else:
            time.sleep(0.04)

    return "".join(line_buffer)


class TerminalLineReader:
    """Background stdin reader for non-TTY or piped terminals (VS Code, PyCharm, Git Bash)"""
    def __init__(self):
        self.input_queue = collections.deque()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not STATE.stop_requested:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                self.input_queue.append(line.rstrip("\r\n"))
            except Exception:
                break


def get_fallback_line(prompt: str, reader: TerminalLineReader) -> str:
    """Non-blocking line reader for non-TTY/IDE terminals that continuously processes the download queue"""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while not STATE.stop_requested:
        if process_pending_events(prompt, line_buffer=None, interactive_confirm=False):
            continue

        if reader.input_queue:
            return reader.input_queue.popleft()

        time.sleep(0.04)

    return ""


def bootstrap_workstation_environment():
    """Auto-detects missing core dependencies and bootstraps them so the workstation runs smoothly"""
    missing_pkgs = []
    try:
        import colorama
    except ImportError:
        missing_pkgs.append("colorama")
    try:
        import pyperclip
    except ImportError:
        missing_pkgs.append("pyperclip")

    if missing_pkgs:
        try:
            print(f"[*] Installing recommended Python libraries: {', '.join(missing_pkgs)}...")
            subprocess.run([sys.executable, "-m", "pip", "install", *missing_pkgs, "--quiet"], check=False)
        except Exception:
            pass

    has_ytdlp = YTDLP_EXE.exists() or shutil.which("yt-dlp")
    if not has_ytdlp:
        print("[*] yt-dlp binary not found. Downloading latest official yt-dlp.exe from GitHub...")
        try:
            import urllib.request
            url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
            urllib.request.urlretrieve(url, str(YTDLP_EXE))
            print("[✓] yt-dlp.exe downloaded successfully.")
        except Exception as e:
            print(f"[!] Note: yt-dlp.exe could not be auto-downloaded: {e}")
            print("    Please run setup.bat or install yt-dlp manually.")

    has_ffmpeg = FFMPEG_EXE.exists() or shutil.which("ffmpeg")
    if not has_ffmpeg:
        print("[!] Note: FFmpeg is not detected in this folder or in system PATH.")
        print("    Run 'setup.bat' to auto-download and install FFmpeg.")


def main():
    if os.name == "nt":
        os.system("title YT-DLP Supercharged Downloader Workstation")

    # Ensure required dependencies & binaries exist
    bootstrap_workstation_environment()

    print_banner()

    # Clean up any dangling fragments from interrupted sessions
    cleanup_orphaned_fragments()

    # Start update checker in background
    check_for_updates_background()

    # Start clipboard watcher background thread
    watcher_t = threading.Thread(target=clipboard_watcher_thread, daemon=True)
    watcher_t.start()

    # Main interactive loop
    prompt = f"{Fore.CYAN}>>> {Style.RESET_ALL}"
    fallback_reader = None
    if not (HAS_MSVCRT and sys.stdin.isatty()):
        fallback_reader = TerminalLineReader()

    try:
        while not STATE.stop_requested:
            if HAS_MSVCRT and sys.stdin.isatty():
                line = get_nonblocking_line(prompt)
            else:
                line = get_fallback_line(prompt, fallback_reader)

            handle_user_command(line)
    except (KeyboardInterrupt, EOFError):
        print(f"\n{Fore.YELLOW}Exiting YT-DLP Terminal. Goodbye!{Style.RESET_ALL}")
    finally:
        STATE.stop_requested = True


if __name__ == "__main__":
    main()
