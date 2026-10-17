"""Tests for Core State (DownloadJob, AppState)."""

from ytdlp_workstation.core.state import DownloadJob, AppState, STATE


def test_download_job_defaults():
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    assert job.url == "https://www.youtube.com/watch?v=123"
    assert job.id is not None
    assert len(job.id) == 8
    assert job.status == "QUEUED"
    assert job.progress_pct == 0.0
    assert isinstance(job.is_cancelled, type(__import__("threading").Event()))
    assert job.is_cancelled.is_set() is False


def test_download_job_to_dict():
    job = DownloadJob(
        url="https://www.youtube.com/watch?v=123",
        display_title="Test Video",
        preset_override=3,
    )
    d = job.to_dict()
    assert d["url"] == "https://www.youtube.com/watch?v=123"
    assert d["display_title"] == "Test Video"
    assert d["preset_override"] == 3
    # is_cancelled (threading.Event) does not start with "_", so it is included
    assert "is_cancelled" in d


def test_download_job_cancellation_token():
    job = DownloadJob(url="https://www.youtube.com/watch?v=123")
    assert job.is_cancelled.is_set() is False
    job.is_cancelled.set()
    assert job.is_cancelled.is_set() is True


def test_app_state_singleton():
    s1 = AppState()
    s2 = AppState()
    # AppState creates new instances each call, but STATE is the module singleton
    assert s1 is not s2
    assert STATE is not None
    assert hasattr(STATE, "config_manager")
    assert hasattr(STATE, "history_manager")
    assert hasattr(STATE, "lock")
    assert hasattr(STATE, "stop_requested")


def test_set_config_updates_state():
    original = STATE.config.get("preset")
    STATE.set_config("preset", 5)
    assert STATE.config.get("preset") == 5
    STATE.set_config("preset", original)  # restore
