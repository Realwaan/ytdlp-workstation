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
