"""
HLS / DASH Fragment Stitcher and FFmpeg Container Remuxer.

Stitches numbered `*-Frag<N>` files into a single contiguous media file with
real-time terminal progress reporting, handles split/appended `ftyp` streams
caused by `--no-part` filename collisions, and runs `ffmpeg -c copy` to build
a clean, fast-seeking MP4 container.

Automatically accelerates directory scanning, MP4 ISO BMFF box walking, stream
splitting, and 16 MiB zero-GIL buffered stitching via `ytdlp_rust_core` when
compiled, with a seamless pure-Python fallback.
"""

__all__ = [
    "find_fragment_groups",
    "inspect_mp4_boxes",
    "merge_fragment_group",
    "merge_all_pending_fragments",
]

import re
import time
import struct
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..core.config import DEFAULT_DOWNLOAD_DIR, FFMPEG_EXE
from ..core.state import DownloadJob
from ..utils.system import sanitize_filename, set_console_title, reset_console_title
from .fragment_registry import claimed_by_others
from .rust_accel import is_rust_enabled, rust_core

_FRAG_RE = re.compile(r"^(?P<base>.+?)-Frag(?P<num>\d+)$")


def find_fragment_groups(
    directory: Path = DEFAULT_DOWNLOAD_DIR,
    for_job: Optional[str] = None,
) -> Dict[str, List[Tuple[int, Path]]]:
    """
    Scan `directory` for `*-Frag<N>` files and group them by base filename.
    Returns `{base_filename: [(frag_num, Path), ...]}` sorted by `frag_num`.

    Groups whose base is claimed by another active job (see fragment_registry)
    are skipped, so concurrent workers never stitch each other's live fragments.
    """
    directory = Path(directory)
    if not directory.exists():
        return {}

    protected = claimed_by_others(for_job)

    if is_rust_enabled() and rust_core is not None:
        raw_groups = rust_core.find_fragment_groups(str(directory), list(protected))
        return {
            base: [(int(num), Path(p_str)) for num, p_str in items]
            for base, items in raw_groups.items()
        }

    groups: Dict[str, List[Tuple[int, Path]]] = {}
    for p in directory.iterdir():
        m = _FRAG_RE.match(p.name)
        if not m:
            continue
        base = m.group("base")
        if base in protected or not p.is_file():
            continue
        num = int(m.group("num"))
        groups.setdefault(base, []).append((num, p))

    for base in groups:
        groups[base].sort(key=lambda item: item[0])

    return groups


def inspect_mp4_boxes(file_path: Path) -> List[Tuple[str, int, int]]:
    """
    Inspect top-level ISO BMFF (MP4/MOV) boxes in `file_path`.
    Returns `[(fourcc, byte_offset, byte_size), ...]`.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []

    if is_rust_enabled() and rust_core is not None:
        try:
            return [
                (str(fourcc), int(offset), int(size))
                for fourcc, offset, size in rust_core.inspect_mp4_boxes(str(file_path))
            ]
        except Exception:
            return []

    total_size = file_path.stat().st_size
    boxes: List[Tuple[str, int, int]] = []
    try:
        with open(file_path, "rb") as f:
            pos = 0
            while pos + 8 <= total_size:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                sz, btype = struct.unpack(">I4s", hdr)
                fourcc = btype.decode("utf-8", errors="replace")
                raw_sz = sz
                if sz == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    sz = struct.unpack(">Q", ext)[0]
                    if sz < 16:
                        break
                elif sz == 0:
                    sz = total_size - pos
                elif sz < 8:
                    break

                boxes.append((fourcc, pos, sz))
                if raw_sz == 0 or pos + sz > total_size:
                    break
                pos += sz
    except Exception:
        return []
    return boxes


def _find_embedded_second_ftyp_offset(file_path: Path) -> Optional[int]:
    """
    Check if `file_path` contains a second concatenated MP4 stream (`ftypisom`)
    appended onto an existing MP4 file (caused by `--no-part` filename collision).
    Walks top-level MP4 boxes from byte 0; if a second `ftyp` box is encountered
    after `moov`/`mdat`, returns its exact byte offset.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return None

    if is_rust_enabled() and rust_core is not None:
        res = rust_core.find_embedded_second_ftyp_offset(str(file_path))
        return int(res) if res is not None else None

    total_size = file_path.stat().st_size
    if total_size < 1024:
        return None

    try:
        with open(file_path, "rb") as f:
            pos = 0
            seen_first_ftyp = False
            seen_media_box = False
            while pos + 8 <= total_size:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                sz, btype = struct.unpack(">I4s", hdr)
                if sz == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    sz = struct.unpack(">Q", ext)[0]
                    if sz < 16:
                        break
                elif sz == 0:
                    break
                elif sz < 8:
                    break

                if btype == b"ftyp":
                    if not seen_first_ftyp:
                        seen_first_ftyp = True
                    elif seen_media_box and pos > 0:
                        return pos
                elif btype in (b"moov", b"mdat", b"moof"):
                    seen_media_box = True

                pos += sz
    except Exception:
        return None

    return None


def merge_fragment_group(
    directory: Path,
    base_name: str,
    frags: List[Tuple[int, Path]],
    output_title: Optional[str] = None,
    job: Optional[DownloadJob] = None,
    on_progress: Optional[Callable[[DownloadJob], None]] = None,
) -> Optional[Path]:
    """
    Stitch all `(frag_num, frag_path)` for `base_name` into a single `.mp4`,
    reporting live progress via `on_progress(job)`. Deletes `-Frag*` and `.ytdl`
    files once merged and remuxes the MP4 container with FFmpeg `-c copy`.
    """
    directory = Path(directory)
    base_file = directory / base_name
    ytdl_file = directory / f"{base_name}.ytdl"

    if not frags:
        return base_file if base_file.exists() else None

    if job is None:
        job = DownloadJob(
            url=base_name,
            display_title=output_title or base_name,
        )
    elif output_title:
        job.display_title = output_title

    job.status = "DOWNLOADING"

    # Determine output file path
    if output_title:
        clean_title = sanitize_filename(output_title)
        if not clean_title.lower().endswith(".mp4"):
            clean_title = f"{clean_title}.mp4"
        target_file = directory / clean_title
    else:
        target_file = base_file

    # Check if base_file had a second stream appended onto an older completed MP4
    split_offset = _find_embedded_second_ftyp_offset(base_file) if base_file.exists() else None
    if split_offset is not None and split_offset > 0:
        if target_file == base_file:
            stem = base_file.stem
            target_file = directory / f"{stem} [Merged-{int(time.time()) % 100000}].mp4"

        if is_rust_enabled() and rust_core is not None:
            rust_core.split_appended_mp4_stream(str(base_file), str(target_file), int(split_offset))
        else:
            # Extract the appended prefix (Frag 0..K) into target_file, then truncate base_file
            with open(base_file, "rb") as src, open(target_file, "wb") as dst:
                src.seek(split_offset)
                while True:
                    chunk = src.read(16 * 1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            with open(base_file, "r+b") as src_trunc:
                src_trunc.truncate(split_offset)
    elif target_file != base_file and base_file.exists() and not target_file.exists():
        base_file.rename(target_file)

    def _emit_merge_progress(
        written_bytes: int,
        grand_total_bytes: int,
        prefix_bytes: int,
        elapsed_secs: float,
        idx: int,
        total_frags: int,
    ) -> None:
        elapsed = max(0.001, elapsed_secs)
        speed_bps = max(0, written_bytes - prefix_bytes) / elapsed
        rem_bps = max(0, grand_total_bytes - written_bytes)
        eta_s = int(rem_bps / speed_bps) if speed_bps > 0 else 0

        job.progress_pct = round((written_bytes / max(1, grand_total_bytes)) * 100.0, 1)
        if grand_total_bytes >= 1024 ** 3:
            job.downloaded_str = f"{written_bytes / (1024 ** 3):.2f}GiB"
            job.total_str = f"{grand_total_bytes / (1024 ** 3):.2f}GiB"
        else:
            job.downloaded_str = f"{written_bytes / (1024 ** 2):.1f}MiB"
            job.total_str = f"{grand_total_bytes / (1024 ** 2):.1f}MiB"
        job.speed_str = f"{speed_bps / (1024 ** 2):.0f}MiB/s"
        m, s = divmod(eta_s, 60)
        job.eta_str = f"{m:02d}:{s:02d}"
        job.fragment_str = f"{idx}/{total_frags}"

        set_console_title(f"[Merging {job.progress_pct:.1f}% ({idx}/{total_frags})] YT-DLP Workstation")
        if on_progress:
            on_progress(job)

    if is_rust_enabled() and rust_core is not None:
        frag_path_strs = [str(p) for _, p in frags]
        _, was_cancelled = rust_core.stitch_fragments(
            str(target_file),
            frag_path_strs,
            True,
            100,
            job.is_cancelled.is_set,
            _emit_merge_progress,
        )
        if was_cancelled:
            job.status = "CANCELLED"
            return None
    else:
        total_frags = len(frags)
        prefix_bytes = target_file.stat().st_size if target_file.exists() else 0
        remaining_bytes = sum(p.stat().st_size for _, p in frags if p.exists())
        grand_total_bytes = prefix_bytes + remaining_bytes
        written_bytes = prefix_bytes

        start_t = time.time()
        last_ui_ts = 0.0

        with open(target_file, "ab") as out_f:
            for idx, (frag_num, frag_path) in enumerate(frags, 1):
                if job.is_cancelled.is_set():
                    job.status = "CANCELLED"
                    return None
                if not frag_path.exists():
                    continue

                with open(frag_path, "rb") as in_f:
                    while True:
                        buf = in_f.read(8 * 1024 * 1024)
                        if not buf:
                            break
                        out_f.write(buf)
                        written_bytes += len(buf)

                try:
                    frag_path.unlink(missing_ok=True)
                except Exception:
                    pass

                now_mono = time.monotonic()
                if idx == 1 or idx == total_frags or (now_mono - last_ui_ts) >= 0.1:
                    last_ui_ts = now_mono
                    _emit_merge_progress(
                        written_bytes=written_bytes,
                        grand_total_bytes=grand_total_bytes,
                        prefix_bytes=prefix_bytes,
                        elapsed_secs=time.time() - start_t,
                        idx=idx,
                        total_frags=total_frags,
                    )

            out_f.flush()

    if ytdl_file.exists():
        try:
            ytdl_file.unlink(missing_ok=True)
        except Exception:
            pass

    # Remux container with FFmpeg (-c copy) so moov/moof index is clean and seekable
    job.status = "PROCESSING"
    job.progress_pct = 100.0
    if on_progress:
        on_progress(job)

    ffmpeg_bin = str(FFMPEG_EXE) if FFMPEG_EXE.exists() else "ffmpeg"
    temp_remux = target_file.with_suffix(".remux.mp4")
    try:
        res = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-loglevel", "error",
                "-i", str(target_file),
                "-c", "copy",
                str(temp_remux),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode == 0 and temp_remux.exists() and temp_remux.stat().st_size > 0:
            temp_remux.replace(target_file)
        elif temp_remux.exists():
            temp_remux.unlink(missing_ok=True)
    except Exception:
        if temp_remux.exists():
            try:
                temp_remux.unlink(missing_ok=True)
            except Exception:
                pass

    job.saved_filename = target_file.name
    job.output_path = str(target_file)
    job.status = "COMPLETED"
    job.progress_pct = 100.0
    if on_progress:
        on_progress(job)
    reset_console_title()
    return target_file


def merge_all_pending_fragments(
    directory: Path = DEFAULT_DOWNLOAD_DIR,
    output_title: Optional[str] = None,
    on_progress: Optional[Callable[[DownloadJob], None]] = None,
) -> List[Path]:
    """Find and merge all pending `*-Frag<N>` groups in `directory`."""
    groups = find_fragment_groups(directory)
    merged_files: List[Path] = []
    for base_name, frags in groups.items():
        out = merge_fragment_group(
            directory=directory,
            base_name=base_name,
            frags=frags,
            output_title=output_title if len(groups) == 1 else None,
            on_progress=on_progress,
        )
        if out is not None:
            merged_files.append(out)
    return merged_files
