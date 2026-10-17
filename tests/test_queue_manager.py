"""Tests for Queue Manager and Concurrency."""

import time
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
    qm = QueueManager(max_workers=2)
    qm.set_max_workers(4)
    assert qm.max_workers == 4

    # Boundaries capping (1-5)
    qm.set_max_workers(10)
    assert qm.max_workers == 5
    qm.set_max_workers(0)
    assert qm.max_workers == 1

    qm.stop_requested = True
