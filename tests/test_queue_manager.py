"""Tests for Queue Manager and Concurrency."""

import time
from unittest.mock import patch

from ytdlp_workstation.core.state import DownloadJob
from ytdlp_workstation.queue.manager import QueueManager


def test_queue_lifecycle():
    # Instantiate QueueManager with workers paused for unit testing
    qm = QueueManager(max_workers=2)
    qm.pause_queue()

    job1 = DownloadJob(url="https://www.youtube.com/watch?v=111", display_title="Track 1")
    job2 = DownloadJob(url="https://www.youtube.com/watch?v=222", display_title="Track 2")

    qm.enqueue(job1)
    qm.enqueue(job2)

    status = qm.list_jobs()
    assert len(status["pending"]) == 2
    assert status["pending"][0].display_title == "Track 1"

    # Cancel job1
    assert qm.cancel_job(job1.id) is True
    status_after_cancel = qm.list_jobs()
    assert len(status_after_cancel["pending"]) == 1
    assert status_after_cancel["pending"][0].id == job2.id

    # Clear remaining
    cleared = qm.clear_pending()
    assert cleared == 1
    assert len(qm.list_jobs()["pending"]) == 0

    qm.stop_requested = True


def test_worker_concurrency_adjustment():
    from ytdlp_workstation.core.events import BUS, EventType

    events = []
    BUS.subscribe(EventType.JOB_ENQUEUED, lambda ev: events.append(ev))

    qm = QueueManager(max_workers=2)
    qm.pause_queue()
    assert len(qm._worker_threads) == 2

    qm.set_max_workers(4)
    assert qm.max_workers == 4
    assert len(qm._worker_threads) == 4

    # Boundaries capping (1-5)
    qm.set_max_workers(10)
    assert qm.max_workers == 5
    assert len(qm._worker_threads) == 5
    qm.set_max_workers(0)
    assert qm.max_workers == 1

    job = DownloadJob(url="https://www.youtube.com/watch?v=999")
    qm.enqueue(job)
    assert any(e.data.get("job_id") == job.id for e in events)

    qm.stop_requested = True


def test_process_job_records_skipped_when_archive_hit():
    """A job flagged was_archive_skipped must log history as 'Skipped', not 'Success'."""
    qm = QueueManager(max_workers=1)
    qm.pause_queue()

    job = DownloadJob(url="https://www.youtube.com/watch?v=444", display_title="Already Have It")
    job.was_archive_skipped = True
    job.start_time = time.time()
    job.finish_time = time.time()

    with patch("ytdlp_workstation.queue.manager.execute_download_job", return_value=True):
        qm._process_job(job)

    entries = qm.state.history_manager.get_entries(limit=5)
    assert entries, "expected a history entry to be written"
    assert entries[-1]["status"] == "Skipped"
    qm.stop_requested = True


def test_process_job_success_logs_success_when_not_skipped():
    qm = QueueManager(max_workers=1)
    qm.pause_queue()

    job = DownloadJob(url="https://www.youtube.com/watch?v=445", display_title="Fresh Video")
    job.saved_filename = "Fresh Video.mp4"
    job.start_time = time.time()
    job.finish_time = time.time()

    with patch("ytdlp_workstation.queue.manager.execute_download_job", return_value=True):
        qm._process_job(job)

    entries = qm.state.history_manager.get_entries(limit=5)
    assert entries, "expected a history entry to be written"
    assert entries[-1]["status"] == "Success"
    qm.stop_requested = True
