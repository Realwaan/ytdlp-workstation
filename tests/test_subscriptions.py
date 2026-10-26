"""Tests for SubscriptionScheduler."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from ytdlp_workstation.core.database import DatabaseEngine
from ytdlp_workstation.core.state import AppState
from ytdlp_workstation.queue.subscription_scheduler import SubscriptionScheduler


def test_subscription_scheduler_lifecycle(tmp_path: Path):
    db = DatabaseEngine(db_path=tmp_path / "sub_test.db")
    qm = MagicMock()
    state = AppState()
    scheduler = SubscriptionScheduler(qm, state=state, db=db, poll_interval_seconds=1.0)

    scheduler.start()
    assert scheduler._thread is not None
    assert scheduler._thread.is_alive()

    scheduler.stop()
    assert scheduler.stop_event.is_set()
    assert scheduler._thread is None


def test_check_subscription_enqueues_new_videos_and_skips_archived(tmp_path: Path):
    db = DatabaseEngine(db_path=tmp_path / "sub_test2.db")
    qm = MagicMock()
    state = AppState()
    scheduler = SubscriptionScheduler(qm, state=state, db=db)

    # Pre-archive vid_001
    db.add_archive_entry("subscription", "vid_001", "Old Video 1")

    # Mock yt-dlp flat playlist json output (2 videos: vid_001 already archived, vid_002 new)
    mock_lines = [
        json.dumps({"id": "vid_001", "title": "Old Video 1", "channel": "Cool Creator"}),
        json.dumps({"id": "vid_002", "title": "New Upload 2", "channel": "Cool Creator"}),
    ]
    mock_stdout = "\n".join(mock_lines)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = mock_stdout

    sub = {
        "id": 1,
        "url": "https://youtube.com/@CoolCreator",
        "title": "Cool Creator",
        "preset_id": 3,
        "custom_folder": "CreatorVideos",
    }

    with patch("subprocess.run", return_value=mock_proc):
        new_cnt = scheduler.check_subscription(sub)

        # Only vid_002 should be enqueued
        assert new_cnt == 1
        qm.enqueue.assert_called_once()
        enqueued_job = qm.enqueue.call_args[0][0]
        assert "vid_002" in enqueued_job.url
        assert enqueued_job.display_title == "New Upload 2"
        assert enqueued_job.preset_override == 3
        assert "CreatorVideos" in enqueued_job.target_dir

        # vid_002 should now be archived in DB
        assert db.is_archived("vid_002") is True


def test_check_all_aggregates_new_counts(tmp_path: Path):
    db = DatabaseEngine(db_path=tmp_path / "sub_test3.db")
    qm = MagicMock()
    state = AppState()
    scheduler = SubscriptionScheduler(qm, state=state, db=db)

    sub_id1 = db.add_subscription("https://youtube.com/@Channel1", "Channel 1")
    sub_id2 = db.add_subscription("https://youtube.com/@Channel2", "Channel 2")

    with patch.object(scheduler, "check_subscription", side_effect=[2, 3]):
        total = scheduler.check_all()
        assert total == 5
