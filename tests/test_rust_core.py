"""Comprehensive tests and Rust-vs-Python parity suite for `ytdlp_rust_core` v0.2.0."""

import json
import struct
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdlp_workstation.cli.command_dispatcher import handle_user_command
from ytdlp_workstation.cli.commands import cmd_rust
from ytdlp_workstation.cli.completion import get_completion_candidates
from ytdlp_workstation.core.history import HistoryManager
from ytdlp_workstation.core.state import AppState, DownloadJob
from ytdlp_workstation.engine import fragment_registry
from ytdlp_workstation.engine.fragment_merger import (
    _find_embedded_second_ftyp_offset,
    find_fragment_groups,
    inspect_mp4_boxes,
    merge_fragment_group,
)
from ytdlp_workstation.engine.hls_turbo import (
    is_hls_turbo_candidate,
    parse_m3u8_playlist,
    run_hls_turbo_download,
)
from ytdlp_workstation.engine.rust_accel import (
    HAS_RUST_CORE,
    RUST_CORE_VERSION,
    force_python_fallback,
    get_rust_capabilities,
    is_rust_enabled,
    rust_core,
    set_rust_enabled,
)
from ytdlp_workstation.extractors.no_watermark import (
    clean_douyin_watermark_url,
    follow_redirects,
)
from ytdlp_workstation.extractors.url_detector import (
    clean_url,
    clean_urls_batch,
    extract_media_url,
    filter_valid_media_urls_batch,
    is_valid_media_url,
)
from ytdlp_workstation.extractors.web_sniffer import (
    _resolve_relative_url,
    extract_all_media_from_html,
    extract_media_from_html,
    sniff_webpages_batch,
)
from ytdlp_workstation.utils.system import cleanup_orphaned_fragments


def _mp4_box(fourcc: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), fourcc) + payload


def _mp4_box64(fourcc: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4sQ", 1, fourcc, 16 + len(payload)) + payload


def test_rust_core_loaded_capabilities_and_fallback_toggle():
    assert HAS_RUST_CORE is True
    assert RUST_CORE_VERSION == "0.2.0"
    assert is_rust_enabled() is True

    caps = get_rust_capabilities()
    assert "tokio_hls_turbo_downloader" in caps
    assert "dfa_media_url_engine" in caps
    assert "zero_copy_progress_parser" in caps

    with force_python_fallback():
        assert is_rust_enabled() is False

    assert is_rust_enabled() is True


def test_mp4_box_scanner_parity_32_and_64_bit(tmp_path: Path):
    box1 = _mp4_box(b"ftyp", b"isom" + b"\x00" * 20)
    box2 = _mp4_box64(b"moov", b"\x11" * 300)
    box3 = _mp4_box(b"mdat", b"\x22" * 900)
    expected_split = len(box1) + len(box2) + len(box3)
    box4 = _mp4_box(b"ftyp", b"isom" + b"\x00" * 20)
    box5 = _mp4_box(b"moof", b"\x33" * 128)

    mp4_file = tmp_path / "collided.mp4"
    mp4_file.write_bytes(box1 + box2 + box3 + box4 + box5)

    rust_offset = _find_embedded_second_ftyp_offset(mp4_file)
    rust_boxes = inspect_mp4_boxes(mp4_file)

    with force_python_fallback():
        py_offset = _find_embedded_second_ftyp_offset(mp4_file)
        py_boxes = inspect_mp4_boxes(mp4_file)

    assert rust_offset == expected_split
    assert py_offset == expected_split
    assert rust_boxes == py_boxes
    assert [b[0] for b in rust_boxes] == ["ftyp", "moov", "mdat", "ftyp", "moof"]


def test_fragment_merger_split_stream_and_stitch_parity(tmp_path: Path):
    def _run_case(case_dir: Path, use_python: bool):
        case_dir.mkdir(parents=True, exist_ok=True)
        first_movie = (
            _mp4_box(b"ftyp", b"isom" + b"\x00" * 20)
            + _mp4_box(b"moov", b"A" * 300)
            + _mp4_box(b"mdat", b"B" * 900)
        )
        second_prefix = _mp4_box(b"ftyp", b"isom" + b"\x00" * 20) + _mp4_box(b"moof", b"C" * 100)

        base = "stream.mp4"
        (case_dir / base).write_bytes(first_movie + second_prefix)
        (case_dir / f"{base}-Frag2").write_bytes(b"_FRAG2_")
        (case_dir / f"{base}-Frag10").write_bytes(b"_FRAG10_END")
        (case_dir / f"{base}.ytdl").write_text("{}", encoding="utf-8")

        def _exec():
            groups = find_fragment_groups(case_dir)
            assert [num for num, _ in groups[base]] == [2, 10]
            with patch("ytdlp_workstation.engine.fragment_merger.subprocess.run") as mock_ff:
                mock_ff.return_value = MagicMock(returncode=1)
                merged = merge_fragment_group(
                    directory=case_dir,
                    base_name=base,
                    frags=groups[base],
                    output_title="Recovered Stream",
                )
            return merged, (case_dir / base).read_bytes()

        if use_python:
            with force_python_fallback():
                return _exec()
        return _exec()

    rust_merged, rust_orig = _run_case(tmp_path / "rust", use_python=False)
    py_merged, py_orig = _run_case(tmp_path / "py", use_python=True)

    assert rust_merged is not None and py_merged is not None
    assert rust_orig == py_orig
    assert rust_merged.read_bytes() == py_merged.read_bytes()
    assert rust_merged.read_bytes().endswith(b"_FRAG2__FRAG10_END")


def test_fragment_merger_respects_cancellation_and_orphan_cleanup(tmp_path: Path):
    base = "cancel_test.mp4"
    other = "active_sibling.mp4"
    (tmp_path / f"{base}-Frag1").write_bytes(b"CHUNK1")
    (tmp_path / f"{base}-Frag2.part").write_bytes(b"CHUNK2")
    (tmp_path / f"{other}-Frag1").write_bytes(b"LIVE")

    job = DownloadJob(url="https://example.com/stream.m3u8")
    job.is_cancelled.set()

    groups = find_fragment_groups(tmp_path)
    res = merge_fragment_group(tmp_path, base, groups[base], job=job)
    assert res is None
    assert job.status == "CANCELLED"
    assert (tmp_path / f"{base}-Frag1").exists()

    fragment_registry.claim("sibling-job", str(tmp_path / other))
    try:
        cleanup_orphaned_fragments(tmp_path, for_job=job.id)
        assert not (tmp_path / f"{base}-Frag1").exists()
        assert not (tmp_path / f"{base}-Frag2.part").exists()
        assert (tmp_path / f"{other}-Frag1").exists()
    finally:
        fragment_registry.release("sibling-job")


def test_dfa_url_validator_cleaner_and_html_sniffer_parity():
    html = """
    <html>
      <head>
        <title>Championship Highlights | Sports Portal</title>
        <meta property="og:video" content="//cdn.sports.example/clip1.mp4" />
        <script type="application/ld+json">
        {
          "@graph": [
            {
              "@type": ["VideoObject", "MediaObject"],
              "name": "Extended Replay",
              "contentUrl": "/streams/replay.m3u8"
            }
          ]
        }
        </script>
      </head>
      <body>
        <video><source src="/fallback/sd.mp4" /></video>
        <script>player.setup({ file: "https://cdn.sports.example/live.m3u8" });</script>
      </body>
    </html>
    """
    page_url = "https://sports.example/watch/finals"

    batch_lines = [
        "# comment line",
        "   ",
        "https://www.youtube.com/watch?si=abc&v=dQw4w9WgXcQ&utm_medium=social#t=10",
        "https://cdn.example.com/master.m3u8?Policy=eyJ0eXAiOiJKV1QifQ%3D%3D&fbclid=xyz123",
        "https://example.com/plain-article",
        "not a url",
    ]
    douyin_raw = "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=999&watermark=1"
    embed_text = "Watch now: https://vt.tiktok.com/ZSjR1234/ awesome clip"

    rust_all = extract_all_media_from_html(html, page_url)
    rust_top = extract_media_from_html(html, page_url)
    rust_rel = _resolve_relative_url(page_url, "../promo.mp4")
    rust_filtered_strict = filter_valid_media_urls_batch(batch_lines, media_filter_only=True)
    rust_filtered_any = filter_valid_media_urls_batch(batch_lines, media_filter_only=False)
    rust_douyin = clean_douyin_watermark_url(douyin_raw)
    rust_ext = extract_media_url(embed_text)
    rust_valid = is_valid_media_url("https://open.spotify.com/track/123", media_filter_only=True)

    with force_python_fallback():
        py_all = extract_all_media_from_html(html, page_url)
        py_top = extract_media_from_html(html, page_url)
        py_rel = _resolve_relative_url(page_url, "../promo.mp4")
        py_filtered_strict = filter_valid_media_urls_batch(batch_lines, media_filter_only=True)
        py_filtered_any = filter_valid_media_urls_batch(batch_lines, media_filter_only=False)
        py_douyin = clean_douyin_watermark_url(douyin_raw)
        py_ext = extract_media_url(embed_text)
        py_valid = is_valid_media_url("https://open.spotify.com/track/123", media_filter_only=True)

    assert rust_all == py_all
    assert len(rust_all) == 4
    assert rust_top == py_top
    assert rust_rel == py_rel == "https://sports.example/promo.mp4"
    assert rust_filtered_strict == py_filtered_strict
    assert len(rust_filtered_strict) == 2
    assert rust_filtered_any == py_filtered_any
    assert len(rust_filtered_any) == 3
    assert rust_douyin == py_douyin
    assert rust_ext == py_ext == "https://vt.tiktok.com/ZSjR1234/"
    assert rust_valid is py_valid is True


def test_archive_loader_and_progress_line_parser_parity(tmp_path: Path):
    archive_a = tmp_path / "archive_rust.txt"
    archive_b = tmp_path / "archive_py.txt"
    payload = "# Archive header\nyoutube dQw4w9WgXcQ\ngeneric index-s1080p\ntiktok 7400001\n"
    archive_a.write_text(payload, encoding="utf-8")
    archive_b.write_text(payload, encoding="utf-8")

    hm_rust = HistoryManager(history_file=tmp_path / "h1.json", archive_file=archive_a)
    with force_python_fallback():
        hm_py = HistoryManager(history_file=tmp_path / "h2.json", archive_file=archive_b)

    assert hm_rust.is_archived("dQw4w9WgXcQ") is True
    assert hm_rust.is_archived("7400001") is True
    assert hm_rust.is_archived("index-s1080p") is False
    assert hm_rust.get_archive_count() == hm_py.get_archive_count() == 2
    assert "generic " not in archive_a.read_text(encoding="utf-8")

    hm_rust.clear_archive()
    assert hm_rust.is_archived("dQw4w9WgXcQ") is False
    assert hm_rust.get_archive_count() == 0

    assert rust_core is not None
    ev = rust_core.parse_progress_line("PROGRESS|P=88.2%|D=88MiB|T=100MiB|S=22MiB/s|E=00:01|F=8/9")
    assert ev is not None
    kind, pct, dl_s, tot_s, spd_s, eta_s, extra = ev
    assert kind == "progress" and pct == pytest.approx(88.2) and extra == "8/9"


def test_hls_turbo_engine_end_to_end_and_encrypted_fallback(tmp_path: Path):
    class _HlsHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_HEAD(self):
            if self.path == "/short":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/video/final")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            port = self.server.server_port
            if self.path == "/master.m3u8":
                body = (
                    "#EXTM3U\n"
                    "#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080\n"
                    f"http://127.0.0.1:{port}/1080p.m3u8\n"
                    "#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\n"
                    "/720p.m3u8\n"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/1080p.m3u8", "/720p.m3u8"):
                tag = "1080P" if "1080" in self.path else "720P"
                lines = [
                    "#EXTM3U",
                    "#EXT-X-TARGETDURATION:4",
                    "#EXT-X-PLAYLIST-TYPE:VOD",
                    f'#EXT-X-MAP:URI="/init_{tag}.bin"',
                ]
                for idx in range(1, 7):
                    lines.append("#EXTINF:4.0,")
                    lines.append(f"/seg/{tag}_{idx}.ts")
                lines.append("#EXT-X-ENDLIST")
                body = ("\n".join(lines) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/init_"):
                tag = self.path.split("_", 1)[1].split(".", 1)[0]
                body = f"INIT[{tag}]|".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/seg/"):
                seg_id = self.path.split("/seg/", 1)[1].split(".", 1)[0]
                body = f"<{seg_id}>".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/encrypted.m3u8":
                body = (
                    b"#EXTM3U\n"
                    b'#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example/key.bin"\n'
                    b"#EXTINF:4.0,\n/seg/1080P_1.ts\n#EXT-X-ENDLIST\n"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/page1":
                body = (
                    b"<html><head><title>Episode 1 - DemoSite</title>"
                    b'<meta property="og:video" content="https://cdn.demo/ep1.m3u8" />'
                    b"</head></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/video/final":
                body = b"OK"
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _HlsHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        cfg = {
            "preset": 4,  # 720p HD -> must select 720P variant from master.m3u8!
            "download_dir": str(tmp_path),
            "rust_hls_turbo": True,
            "subtitles_mode": "off",
            "sponsorblock": False,
            "speed_limit": "none",
            "browser_cookies": "none",
            "cookies_file": "none",
        }
        job = DownloadJob(
            url=f"http://127.0.0.1:{port}/master.m3u8",
            display_title="Turbo Cinema Test",
        )
        assert is_hls_turbo_candidate(job, cfg) is True

        prog_frags = []
        with patch("ytdlp_workstation.engine.hls_turbo.subprocess.run") as mock_ff:
            mock_ff.return_value = MagicMock(returncode=1)  # preserve raw assembled stream for byte check
            ok = run_hls_turbo_download(
                job,
                cfg,
                on_progress=lambda j: prog_frags.append(j.fragment_str),
                concurrency=4,
            )

        assert ok is True
        assert job.status == "COMPLETED"
        out_file = Path(job.output_path)
        assert out_file.exists()
        assert out_file.read_bytes() == b"INIT[720P]|<720P_1><720P_2><720P_3><720P_4><720P_5><720P_6>"
        assert "6/6" in prog_frags
        # Zero *-Frag* files created on disk
        assert list(tmp_path.glob("*-Frag*")) == []

        # Encrypted HLS must cleanly return None so yt-dlp fallback handles decryption
        enc_job = DownloadJob(url=f"http://127.0.0.1:{port}/encrypted.m3u8")
        enc_res = run_hls_turbo_download(enc_job, cfg)
        assert enc_res is None

        # Redirect follower & parallel fetcher check
        resolved_short = follow_redirects(f"http://127.0.0.1:{port}/short", timeout=4.0)
        assert resolved_short.endswith("/video/final")

        batch_sniff = sniff_webpages_batch([f"http://127.0.0.1:{port}/page1"], timeout=4.0)
        assert batch_sniff[0] is not None and batch_sniff[0].media_url == "https://cdn.demo/ep1.m3u8"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_rust_command_and_completion(capsys):
    state = AppState()
    qm = MagicMock()

    # Tab completion
    _, _, _, top_cands = get_completion_candidates("rus", 3)
    assert top_cands == ["rust"]
    _, _, _, sub_cands = get_completion_candidates("rust ", 5)
    assert {"status", "bench", "on", "off", "hls"}.issubset(set(sub_cands))

    # Status & live benchmark via dispatcher
    handle_user_command("rust status", qm, state=state)
    out_status = capsys.readouterr().out
    assert "NATIVE RUST ACCELERATION ENGINE" in out_status
    assert "0.2.0" in out_status

    cmd_rust("rust bench", state=state)
    out_bench = capsys.readouterr().out
    assert "RUST CORE LIVE BENCHMARK RESULTS" in out_bench

    # Toggle off and restore on
    try:
        cmd_rust("rust off", state=state)
        assert is_rust_enabled() is False
        cmd_rust("rust on", state=state)
        assert is_rust_enabled() is True
    finally:
        set_rust_enabled(True)
