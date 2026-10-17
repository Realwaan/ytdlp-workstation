"""Tests for Subprocess Engine."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ytdlp_workstation.core.state import DownloadJob
from ytdlp_workstation.engine.subprocess_engine import run_subprocess_download


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


class _FakeProc:
    """Fake subprocess.Popen for testing."""

    def __init__(self, lines=None, returncode=0, pid=12345):
        self.lines = lines or []
        self.returncode = returncode
        self.pid = pid
        self.stdout = iter(self.lines)
        self.killed = False

    def wait(self):
        pass

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


def test_subprocess_success_with_progress_parsing(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    lines = [
        "PROGRESS|P=50.0|D=50MB|T=100MB|S=5.0MB/s|E=00:10|F=2/4",
        "[download] Destination: /path/to/video.mp4",
    ]

    fake_proc = _FakeProc(lines=lines, returncode=0)

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ):
        progress_calls = []
        result = run_subprocess_download(
            job, config, on_progress=lambda j: progress_calls.append(j.progress_pct)
        )

    assert result is True
    assert job.status == "COMPLETED"
    assert job.progress_pct == 100.0
    assert job.saved_filename == "video.mp4"
    assert len(progress_calls) == 2
    assert progress_calls[0] == 50.0
    assert progress_calls[1] == 100.0


def test_subprocess_lenient_success_at_99_percent(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    lines = ["PROGRESS|P=99.5|D=99MB|T=100MB|S=1.0MB/s|E=00:01|F=1/1"]
    fake_proc = _FakeProc(lines=lines, returncode=1)  # nonzero but >= 99%

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ):
        result = run_subprocess_download(job, config)

    assert result is True
    assert job.status == "COMPLETED"


def test_subprocess_cancellation_via_is_cancelled(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    lines = ["PROGRESS|P=10.0|D=10MB|T=100MB|S=1.0MB/s|E=01:00|F=1/5"]
    fake_proc = _FakeProc(lines=lines, returncode=0)

    kill_called = []

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.kill_job_process",
        side_effect=lambda jid: kill_called.append(jid),
    ):
        # Simulate cancellation mid-iteration
        job.is_cancelled.set()
        result = run_subprocess_download(job, config)

    assert result is False
    assert job.status == "CANCELLED"
    assert kill_called == [job.id]  # kill_job_process is called with job.id


def test_subprocess_failure_nonzero_returncode(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    lines = ["ERROR: something went wrong"]
    fake_proc = _FakeProc(lines=lines, returncode=1)

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ):
        result = run_subprocess_download(job, config)

    assert result is False
    assert job.status == "FAILED"
    assert "something went wrong" in job.error_message


def test_subprocess_exception_sets_failed(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        side_effect=OSError("no such file"),
    ):
        result = run_subprocess_download(job, config)

    assert result is False
    assert job.status == "FAILED"
    assert "no such file" in job.error_message


def test_subprocess_aria2c_progress_parsing(tmp_path):
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    config = make_config(download_dir=str(tmp_path))

    lines = [
        "[#408b72 15MiB/42MiB(35%) CN:16 DL:12MiB ETA:2s]",
        "[Merger] Merging formats into \"video.mp4\"",
    ]
    fake_proc = _FakeProc(lines=lines, returncode=0)

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ):
        progress_snapshots = []
        result = run_subprocess_download(
            job,
            config,
            on_progress=lambda j: progress_snapshots.append((j.status, j.progress_pct, j.speed_str)),
        )

    assert result is True
    assert ("DOWNLOADING", 35.0, "12MiB/s") in progress_snapshots
    assert ("PROCESSING", 100.0, "12MiB/s") in progress_snapshots

