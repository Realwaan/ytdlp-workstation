import pytest
from unittest.mock import MagicMock
from ytdlp_workstation.queue.manager import QueueManager
from ytdlp_workstation.core.state import AppState, DownloadJob
from ytdlp_workstation.cli.command_dispatcher import handle_user_command


def test_resolve_job_by_index_and_id():
    state = AppState()
    qm = QueueManager(max_workers=2, state=state)
    qm.is_paused = True
    j1 = DownloadJob(url="https://test.com/1")
    j2 = DownloadJob(url="https://test.com/2")
    qm.active_jobs[j1.id] = j1
    qm.pending_queue.append(j2)

    # 1 refers to first active job
    assert qm.resolve_job("1") == j1
    # 2 refers to first pending job
    assert qm.resolve_job("2") == j2
    # ID resolution
    assert qm.resolve_job(j1.id) == j1
    assert qm.resolve_job(j1.id[:8]) == j1
    # Out of range
    assert qm.resolve_job("99") is None

    qm.stop_requested = True


def test_cancel_job_by_index():
    state = AppState()
    qm = QueueManager(max_workers=2, state=state)
    qm.is_paused = True
    j1 = DownloadJob(url="https://test.com/1")
    j2 = DownloadJob(url="https://test.com/2")
    qm.active_jobs[j1.id] = j1
    qm.pending_queue.append(j2)

    # Cancel 2 (the pending job)
    assert qm.cancel_job("2") is True
    assert j2 not in qm.pending_queue
    assert j2.status == "CANCELLED"

    # Cancel 1 (the active job)
    assert qm.cancel_job("1") is True
    assert j1.is_cancelled.is_set()

    qm.stop_requested = True


def test_cancel_all():
    state = AppState()
    qm = QueueManager(max_workers=2, state=state)
    qm.is_paused = True
    j1 = DownloadJob(url="https://test.com/1")
    j2 = DownloadJob(url="https://test.com/2")
    j3 = DownloadJob(url="https://test.com/3")
    qm.active_jobs[j1.id] = j1
    qm.pending_queue.append(j2)
    qm.pending_queue.append(j3)

    count = qm.cancel_all()
    assert count == 3
    assert len(qm.pending_queue) == 0
    assert j1.is_cancelled.is_set()

    qm.stop_requested = True


def test_cancel_all_command_dispatcher(capsys):
    state = AppState()
    qm = QueueManager(max_workers=2, state=state)
    j1 = DownloadJob(url="https://test.com/1")
    qm.active_jobs[j1.id] = j1

    handle_user_command("cancel all", qm, state=state)
    captured = capsys.readouterr()
    assert "Cancelled all" in captured.out
    assert j1.is_cancelled.is_set()

    qm.stop_requested = True


def test_cancel_index_command_dispatcher(capsys):
    state = AppState()
    qm = QueueManager(max_workers=2, state=state)
    j1 = DownloadJob(url="https://test.com/1")
    qm.pending_queue.append(j1)

    handle_user_command("cancel 1", qm, state=state)
    captured = capsys.readouterr()
    assert "Cancelled job 1" in captured.out
    assert j1 not in qm.pending_queue

    qm.stop_requested = True
