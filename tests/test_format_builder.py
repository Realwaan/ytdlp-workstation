"""Tests for Format and Options Builder."""

from pathlib import Path
from ytdlp_workstation.core.state import DownloadJob
from ytdlp_workstation.engine.format_builder import (
    build_native_ytdlp_opts,
    build_subprocess_command
)


def test_build_native_audio_preset():
    job = DownloadJob(
        url="https://www.youtube.com/watch?v=123",
        force_audio=True
    )
    config = {
        "preset": 1,
        "download_dir": "downloads",
        "sponsorblock": True,
        "subtitles_mode": "off"
    }

    opts, preset_name = build_native_ytdlp_opts(job, config)
    assert "ba/b" in opts["format"]
    pp_keys = [pp.get("key") for pp in opts["postprocessors"]]
    assert "FFmpegExtractAudio" in pp_keys
    assert "SponsorBlock" in pp_keys


def test_build_native_video_with_subs_and_archive(tmp_path):
    arch_file = tmp_path / "archive.txt"
    job = DownloadJob(
        url="https://www.youtube.com/watch?v=123",
        preset_override=3,  # 1080p
        force_subs=True,
        sub_lang="en"
    )
    config = {
        "download_dir": str(tmp_path),
        "use_download_archive": True,
        "codec_preference": "compatibility"
    }

    opts, preset_name = build_native_ytdlp_opts(job, config, archive_path=arch_file)
    assert "height<=1080" in opts["format"]
    assert opts["writesubtitles"] is True
    assert opts["download_archive"] == str(arch_file)
    assert "vcodec:h264" in opts["format_sort"]


def test_build_subprocess_command():
    job = DownloadJob(
        url="https://www.youtube.com/watch?v=123",
        preset_override=4,  # 720p
        download_section="01:00-02:00"
    )
    config = {
        "download_dir": "downloads",
        "speed_limit": "5M"
    }

    cmd, preset_name = build_subprocess_command(job, config)
    assert any("720" in arg for arg in cmd)
    assert "--download-sections" in cmd
    assert "*01:00-02:00" in cmd
    assert "--limit-rate" in cmd
    assert "5M" in cmd


def test_generic_m3u8_stream_unique_filename_and_no_archive(tmp_path):
    arch_file = tmp_path / "archive.txt"
    url1 = "https://moon.zenoak.top/vd/AAA111/index-s2160p-v1-a1.m3u8"
    url2 = "https://moon.zenoak.top/vd/BBB222/index-s2160p-v1-a1.m3u8"

    job1 = DownloadJob(url=url1)
    job2 = DownloadJob(url=url2)
    config = {"download_dir": str(tmp_path), "use_download_archive": True}

    opts1, _ = build_native_ytdlp_opts(job1, config, archive_path=arch_file)
    opts2, _ = build_native_ytdlp_opts(job2, config, archive_path=arch_file)

    assert "download_archive" not in opts1
    assert "download_archive" not in opts2
    assert opts1["outtmpl"]["default"] != opts2["outtmpl"]["default"]
    assert "%(id)s" not in opts1["outtmpl"]["default"]


def test_generic_stream_with_detected_movie_title(tmp_path):
    from ytdlp_workstation.extractors.title_detector import (
        clean_browser_tab_title,
        detect_stream_title,
        extract_resolution_tag,
    )

    assert clean_browser_tab_title("Watch The Odyssey (2026) Online Free - Movy - Brave") == "The Odyssey (2026)"
    assert clean_browser_tab_title("🔊 Spider-Man: Brand New Day | CineJoy - Google Chrome") == "Spider-Man Brand New Day"
    assert extract_resolution_tag("https://moon.zenoak.top/vd/ABC/index-s2160p-v1-a1.m3u8") == "2160p"
    assert detect_stream_title("https://cdn.example.com/hls/the-odyssey-2026/master.m3u8") == "The Odyssey 2026"

    url = "https://moon.zenoak.top/vd/MUNQMG/index-s2160p-v1-a1.m3u8"
    job = DownloadJob(url=url, display_title="The Odyssey (2026)")
    opts, _ = build_native_ytdlp_opts(job, {"download_dir": str(tmp_path)})
    assert Path(opts["outtmpl"]["default"]).name == "The Odyssey (2026) [2160p].%(ext)s"


def test_no_watermark_opts_injection(tmp_path):
    job = DownloadJob(url="https://www.tiktok.com/@user/video/123456789")
    config = {"download_dir": str(tmp_path), "preset": 2}
    opts, _ = build_native_ytdlp_opts(job, config)
    assert "format_note!*=watermarked" in opts["format"]
    assert "extractor_args" in opts
    assert "tiktok" in opts["extractor_args"]

    cmd, _ = build_subprocess_command(job, config)
    cmd_str = " ".join(cmd)
    assert "format_note!*=watermarked" in cmd_str
    assert "--extractor-args" in cmd_str



