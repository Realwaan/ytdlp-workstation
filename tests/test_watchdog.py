"""Tests for the subprocess stall watchdog (Phase 2)."""

import threading
from unittest.mock import patch

from ytdlp_workstation.core.state import DownloadJob
from ytdlp_workstation.engine.subprocess_engine import run_subprocess_download

from tests.test_subprocess_engine import make_config


class _StallProc:
    """Fake Popen that emits one progress line then goes silent forever."""

    def __init__(self):
        self.returncode = None  # still "running"
        self.pid = 42424
        self.killed = False
        self._dead = threading.Event()

    @property
    def stdout(self):
        return self

    def __iter__(self):
        yield "PROGRESS|P=10.0|D=1MB|T=10MB|S=1.0MB/s|E=00:09|F=1/1\n"
        # Simulate an indefinite stall: no more output until killed.
        self._dead.wait(timeout=15)

    def poll(self):
        return self.returncode

    def wait(self):
        self._dead.wait(timeout=5)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -1
        self._dead.set()


def test_stall_watchdog_kills_silent_process(tmp_path):
    job = DownloadJob(url="https://example.com/video.mp4")
    config = make_config(download_dir=str(tmp_path))
    config["stall_timeout"] = 1  # seconds — small so the test is fast

    fake_proc = _StallProc()
    kill_calls = []

    def fake_kill(job_id):
        kill_calls.append(job_id)
        fake_proc.kill()  # unblocks stdout + wait()
        return True

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.kill_job_process",
        side_effect=fake_kill,
    ):
        result = run_subprocess_download(job, config)

    assert result is False
    assert job.status == "FAILED"
    assert "stalled" in job.error_message.lower()
    assert kill_calls == [job.id]


def test_stall_watchdog_disabled_with_zero_timeout(tmp_path):
    """stall_timeout=0 must disable the watchdog entirely (proc completes normally)."""
    from tests.test_subprocess_engine import _FakeProc

    job = DownloadJob(url="https://example.com/video.mp4")
    config = make_config(download_dir=str(tmp_path))
    config["stall_timeout"] = 0

    lines = ["PROGRESS|P=50.0|D=5MB|T=10MB|S=1.0MB/s|E=00:05|F=1/2"]
    fake_proc = _FakeProc(lines=lines, returncode=0)

    with patch(
        "ytdlp_workstation.engine.subprocess_engine.subprocess.Popen",
        return_value=fake_proc,
    ), patch(
        "ytdlp_workstation.engine.subprocess_engine.SUPERVISOR.register",
    ):
        result = run_subprocess_download(job, config)

    assert result is True
    assert job.status == "COMPLETED"
