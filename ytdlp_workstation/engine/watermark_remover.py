"""
Watermark remover and video delogo / crop post-processor using FFmpeg.
Provides filters to remove burned-in logos, watermarks, or cropped banner strips.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Callable

from ..core.config import FFMPEG_EXE

__all__ = [
    "build_delogo_cmd",
    "build_crop_cmd",
    "build_crop_bottom_cmd",
    "run_ffmpeg_filter",
    "delogo_video",
    "crop_video",
    "clean_video",
]


def build_delogo_cmd(
    input_file: Path,
    output_file: Path,
    x: int,
    y: int,
    w: int,
    h: int,
) -> List[str]:
    """Build FFmpeg command to remove a static watermark using delogo filter."""
    return [
        str(FFMPEG_EXE),
        "-y",
        "-i",
        str(input_file),
        "-vf",
        f"delogo=x={x}:y={y}:w={w}:h={h}",
        "-c:a",
        "copy",
        str(output_file),
    ]


def build_crop_cmd(
    input_file: Path,
    output_file: Path,
    crop_w: str,
    crop_h: str,
    x: str = "0",
    y: str = "0",
) -> List[str]:
    """Build FFmpeg command to crop video dimensions."""
    return [
        str(FFMPEG_EXE),
        "-y",
        "-i",
        str(input_file),
        "-vf",
        f"crop={crop_w}:{crop_h}:{x}:{y}",
        "-c:a",
        "copy",
        str(output_file),
    ]


def build_crop_bottom_cmd(
    input_file: Path,
    output_file: Path,
    crop_bottom_pixels: int = 60,
) -> List[str]:
    """Build FFmpeg command to crop away bottom pixels (e.g. watermark bar)."""
    return build_crop_cmd(
        input_file=input_file,
        output_file=output_file,
        crop_w="in_w",
        crop_h=f"in_h-{crop_bottom_pixels}",
        x="0",
        y="0",
    )


def run_ffmpeg_filter(
    cmd: List[str],
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """Execute FFmpeg filter command synchronously."""
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        if proc.stdout:
            for line in proc.stdout:
                line_str = line.strip()
                if line_str and on_progress:
                    on_progress(line_str)
        proc.wait()
        return proc.returncode == 0
    except Exception as e:
        if on_progress:
            on_progress(f"FFmpeg execution failed: {e}")
        return False


def delogo_video(
    input_path: str | Path,
    output_path: Optional[str | Path] = None,
    x: int = 0,
    y: int = 0,
    w: int = 120,
    h: int = 60,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Apply FFmpeg delogo filter on input video."""
    inp = Path(input_path).resolve()
    if not inp.exists():
        return None
    out = Path(output_path).resolve() if output_path else inp.parent / f"{inp.stem}_clean{inp.suffix}"

    cmd = build_delogo_cmd(inp, out, x=x, y=y, w=w, h=h)
    success = run_ffmpeg_filter(cmd, on_progress=on_progress)
    return out if success and out.exists() else None


def crop_video(
    input_path: str | Path,
    output_path: Optional[str | Path] = None,
    crop_bottom_pixels: int = 60,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Apply FFmpeg crop filter on input video."""
    inp = Path(input_path).resolve()
    if not inp.exists():
        return None
    out = Path(output_path).resolve() if output_path else inp.parent / f"{inp.stem}_cropped{inp.suffix}"

    cmd = build_crop_bottom_cmd(inp, out, crop_bottom_pixels=crop_bottom_pixels)
    success = run_ffmpeg_filter(cmd, on_progress=on_progress)
    return out if success and out.exists() else None


def clean_video(
    input_path: str | Path,
    mode: str = "delogo",
    output_path: Optional[str | Path] = None,
    **kwargs,
) -> Optional[Path]:
    """Unified video watermark cleanup entry point."""
    if mode == "crop":
        crop_bottom_pixels = kwargs.get("crop_bottom_pixels", kwargs.get("pixels", 60))
        return crop_video(input_path, output_path=output_path, crop_bottom_pixels=crop_bottom_pixels)
    else:
        x = kwargs.get("x", 0)
        y = kwargs.get("y", 0)
        w = kwargs.get("w", 120)
        h = kwargs.get("h", 60)
        return delogo_video(input_path, output_path=output_path, x=x, y=y, w=w, h=h)
