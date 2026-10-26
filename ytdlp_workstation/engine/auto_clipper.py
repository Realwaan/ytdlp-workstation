"""
Auto-Clipper & Short-Form Video Engine for YT-DLP Workstation.
Converts horizontal 16:9 streams into high-retention 9:16 vertical shorts,
applies dynamic blurred-backdrop scaling, top title hooks, and automated sound-effects / meme mixing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..core.config import FFMPEG_EXE, DATA_DIR

__all__ = [
    "create_vertical_short",
    "generate_anti_spam_variants",
    "get_sfx_path",
]

SFX_DIR = DATA_DIR / "sfx"


def get_sfx_path(name: str) -> Optional[Path]:
    """Retrieve path to a built-in or cached SFX asset."""
    p = SFX_DIR / f"{name}.wav"
    if p.exists():
        return p
    p2 = SFX_DIR / f"{name}.mp3"
    if p2.exists():
        return p2
    return None


def create_vertical_short(
    input_file: Path,
    output_file: Path,
    title_hook: str = "FaZe Clan Pulled A 1ST EDITION GRAIL On BOXED",
    sfx_cues: Optional[List[Dict[str, Any]]] = None,
    max_duration: float = 32.0,
    font_path: str = "C\\:/Windows/Fonts/impact.ttf",
) -> Optional[Path]:
    """
    Render a horizontal (16:9) video into a 1080x1920 vertical short.
    - Blurred background expansion
    - Crisp centered foreground
    - Clean top Impact title hook with black outline
    - Automated audio mixing with SFX triggers at specified timestamps
    """
    if not input_file.exists():
        return None

    output_file.parent.mkdir(parents=True, exist_ok=True)
    sfx_cues = sfx_cues or []

    # 1. Video filter chain
    filter_v = (
        "[0:v]split=2[v_bg][v_fg];"
        "[v_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:28[bg];"
        "[v_fg]scale=1080:-1[fg];"
        "[bg][fg]overlay=0:(H-h)/2[composed];"
        f"[composed]drawtext=fontfile='{font_path}':text='{title_hook}':"
        "fontsize=50:fontcolor=white:bordercolor=black:borderw=5:x=(w-text_w)/2:y=260[outv]"
    )

    # 2. Audio filter chain
    audio_inputs = []
    audio_filter_parts = []
    input_index = 1

    valid_cues = []
    for cue in sfx_cues:
        sfx_name = cue.get("sfx")
        timestamp_ms = int(cue.get("time_s", 0) * 1000)
        volume = cue.get("volume", 1.0)
        sfx_path = get_sfx_path(sfx_name)
        if sfx_path and sfx_path.exists():
            audio_inputs.extend(["-i", str(sfx_path)])
            audio_filter_parts.append(f"[{input_index}:a]adelay={timestamp_ms}|{timestamp_ms},volume={volume:.2f}[sfx{input_index}]")
            valid_cues.append(f"[sfx{input_index}]")
            input_index += 1

    if valid_cues:
        amix_inputs = "[0:a]" + "".join(valid_cues)
        filter_a = ";".join(audio_filter_parts) + f";{amix_inputs}amix=inputs={len(valid_cues) + 1}:duration=first:dropout_transition=2[outa]"
    else:
        filter_a = "[0:a]acopy[outa]"

    cmd = [
        str(FFMPEG_EXE), "-y",
        "-t", str(max_duration),
        "-i", str(input_file),
        *audio_inputs,
        "-filter_complex", f"{filter_v};{filter_a}",
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
        "-c:a", "aac", "-b:a", "192k",
        str(output_file)
    ]

    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
    if proc.returncode == 0 and output_file.exists():
        return output_file
    return None


def generate_anti_spam_variants(
    input_file: Path,
    output_dir: Path,
    base_name: str = "FAZE_CLIP",
    sfx_cues: Optional[List[Dict[str, Any]]] = None,
) -> List[Path]:
    """
    Generate 3 uniquely varied edits of the same clip to satisfy platform duplicate-content rules
    and avoid Clipfarm's 'Spam (same video on many pages)' rejection flag.
    - Variant 1: Primary hook + standard SFX pacing
    - Variant 2: Alternative mystery hook + 1.5s trim offset
    - Variant 3: Collector hype hook + higher bass punch
    """
    variants_meta = [
        {
            "suffix": "V1_GRAIL",
            "hook": "FaZe Clan Pulled A 1ST EDITION GRAIL On BOXED",
            "duration": 32.0,
            "cues": sfx_cues or [{"sfx": "ding", "time_s": 2.5, "volume": 0.9}, {"sfx": "bass_drop", "time_s": 16.0, "volume": 1.2}],
        },
        {
            "suffix": "V2_REACTION",
            "hook": "WAIT FOR THE ENDING... FaZe House Goes Insane On BOXED",
            "duration": 30.5,
            "cues": [{"sfx": "ding", "time_s": 2.2, "volume": 1.0}, {"sfx": "vine_boom", "time_s": 15.8, "volume": 1.1}],
        },
        {
            "suffix": "V3_HOLY_GRAIL",
            "hook": "HE REALLY PULLED THIS IN FRONT OF EVERYONE On BOXED",
            "duration": 33.0,
            "cues": [{"sfx": "ding", "time_s": 2.5, "volume": 0.8}, {"sfx": "bass_drop", "time_s": 16.0, "volume": 1.4}, {"sfx": "vine_boom", "time_s": 16.2, "volume": 0.9}],
        },
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for item in variants_meta:
        target_path = output_dir / f"{base_name}_{item['suffix']}.mp4"
        out = create_vertical_short(
            input_file=input_file,
            output_file=target_path,
            title_hook=item["hook"],
            sfx_cues=item["cues"],
            max_duration=item["duration"],
        )
        if out and out.exists():
            results.append(out)

    return results
