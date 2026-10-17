"""
Presets definitions and format sorting rules.
Supports multi-resolution video, high-resolution lossless audio, and codec compatibility strategies.
"""

from typing import Dict, Any, Tuple, Optional

PRESETS: Dict[int, Dict[str, Any]] = {
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

QUALITY_SHORTCUT_MAP: Dict[str, Tuple[int, bool, str]] = {
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
    "mkv": (12, False, "Universal MKV")
}


def get_preset(preset_id: int) -> Dict[str, Any]:
    """Return preset configuration by ID with safe fallback to preset 1."""
    return PRESETS.get(preset_id, PRESETS[1])


def resolve_format_sort(codec_preference: str = "auto") -> Optional[str]:
    """
    Returns yt-dlp format sorting string based on user codec preference:
    - 'compatibility': Prioritize H.264 (AVC) and AAC for maximum smart TV/editor compatibility.
    - 'quality': Prioritize modern codecs (AV1, VP9, Opus).
    - 'auto': Default yt-dlp resolution/bitrate ordering.
    """
    if codec_preference == "compatibility":
        return "vcodec:h264,acodec:aac,res,fps"
    elif codec_preference == "quality":
        return "vcodec:av01,vcodec:vp9.2,vcodec:vp9,res,fps"
    return None
