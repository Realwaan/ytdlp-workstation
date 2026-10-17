"""Tests for Native Engine."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ytdlp_workstation.core.state import DownloadJob
from ytdlp_workstation.engine.native_engine import (
    execute_download_job,
    HAS_YTDLP_MODULE,
)


def make_config(**overrides):
    cfg = {
        "preset": 1,
        "download_dir": "downloads",
        "use_download_archive": False,
        "codec_preference": "auto",
        "browser_cookies": "none",
        "cookies_file": "none",
        "speed_limit": "none",
        "sponsorblock": False,
        "subtitles_mode": "off",
    }
    cfg.update(overrides)
    return cfg


def test_native_falls_back_to_subprocess_when_aria2c_exists(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    with patch(
        "ytdlp_workstation.engine.native_engine.ARIA2C_EXE",
        new=Path("bin/aria2c.exe"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.run_subprocess_download",
        return_value=True,
    ) as mock_sub:
        result = execute_download_job(job, config, archive_path=None)
        assert result is True
        mock_sub.assert_called_once()


def test_native_falls_back_to_subprocess_when_yt_dlp_missing(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    with patch(
        "ytdlp_workstation.engine.native_engine.HAS_YTDLP_MODULE",
        new=False,
    ), patch(
        "ytdlp_workstation.engine.native_engine.ARIA2C_EXE",
        new=Path("nonexistent.exe"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.run_subprocess_download",
        return_value=True,
    ) as mock_sub:
        result = execute_download_job(job, config)
        assert result is True
        mock_sub.assert_called_once()


def test_native_download_success(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    mock_ydl = MagicMock()
    # YoutubeDL(opts) returns mock_ydl; `with mock_ydl as ydl` -> ydl = mock_ydl.__enter__().return_value
    mock_ydl.return_value.__enter__.return_value.download.return_value = 0

    progress_calls = []

    def on_progress(j):
        progress_calls.append(j.progress_pct)

    with patch(
        "ytdlp_workstation.engine.native_engine.HAS_YTDLP_MODULE",
        new=True,
    ), patch(
        "ytdlp_workstation.engine.native_engine.ARIA2C_EXE",
        new=Path("nonexistent.exe"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.yt_dlp.YoutubeDL",
        mock_ydl,
    ), patch(
        "ytdlp_workstation.engine.native_engine.run_subprocess_download",
        return_value=True,
    ) as mock_sub:
        result = execute_download_job(
            job, config, archive_path=None, on_progress=on_progress
        )

    assert result is True
    assert job.status == "COMPLETED"
    assert job.progress_pct == 100.0
    mock_sub.assert_not_called()


def test_native_download_failure(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    mock_ydl = MagicMock()
    mock_ydl.return_value.__enter__.return_value.download.return_value = 1

    with patch(
        "ytdlp_workstation.engine.native_engine.HAS_YTDLP_MODULE",
        new=True,
    ), patch(
        "ytdlp_workstation.engine.native_engine.ARIA2C_EXE",
        new=Path("nonexistent.exe"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.yt_dlp.YoutubeDL",
        mock_ydl,
    ):
        result = execute_download_job(job, config)

    assert result is False
    assert job.status == "FAILED"


def test_native_exception_falls_back_to_subprocess(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    with patch(
        "ytdlp_workstation.engine.native_engine.HAS_YTDLP_MODULE",
        new=True,
    ), patch(
        "ytdlp_workstation.engine.native_engine.ARIA2C_EXE",
        new=Path("nonexistent.exe"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.yt_dlp.YoutubeDL",
        side_effect=Exception("boom"),
    ), patch(
        "ytdlp_workstation.engine.native_engine.run_subprocess_download",
        return_value=False,
    ) as mock_sub:
        result = execute_download_job(job, config)
        assert result is False
        mock_sub.assert_called_once()
