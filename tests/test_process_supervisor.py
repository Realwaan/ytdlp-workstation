"""Tests for Process Supervisor."""

import subprocess
from unittest.mock import MagicMock, patch

from ytdlp_workstation.engine.process_supervisor import (
    ProcessSupervisor,
    SUPERVISOR,
)


def test_register_and_is_running():
    sup = ProcessSupervisor()
    proc = MagicMock()
    proc.pid = 12345
    proc.poll.return_value = None

    sup.register("job-1", proc)
    assert sup.is_running("job-1") is True
    assert sup.get_pid("job-1") == 12345

    sup.unregister("job-1")
    assert sup.is_running("job-1") is False


def test_register_not_running_when_polled_none():
    sup = ProcessSupervisor()
    proc = MagicMock()
    proc.pid = 99999
    proc.poll.return_value = 0  # already finished

    sup.register("job-2", proc)
    assert sup.is_running("job-2") is False


@patch("ytdlp_workstation.engine.process_supervisor.subprocess.run")
def test_kill_pid_tree_windows(mock_run):
    mock_run.return_value = MagicMock(returncode=0)

    sup = ProcessSupervisor()
    result = sup.kill_pid_tree(12345)

    assert result is True
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == ["taskkill", "/F", "/T", "/PID", "12345"]


@patch("ytdlp_workstation.engine.process_supervisor.subprocess.run")
def test_kill_pid_tree_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1)

    sup = ProcessSupervisor()
    result = sup.kill_pid_tree(12345)

    assert result is False


def test_kill_job_process_registered(mock_supervisor=None):
    sup = ProcessSupervisor()
    proc = MagicMock()
    proc.pid = 55555
    proc.poll.return_value = None
    sup.register("job-x", proc)

    with patch.object(sup, "kill_pid_tree", return_value=True) as mock_kill:
        result = sup.kill_job_process("job-x")
        assert result is True
        mock_kill.assert_called_once_with(55555)

    assert sup.is_running("job-x") is False


def test_kill_job_process_not_registered():
    sup = ProcessSupervisor()
    assert sup.kill_job_process("nonexistent") is False


@patch("ytdlp_workstation.engine.process_supervisor.ProcessSupervisor.kill_pid_tree")
def test_reap_all(mock_kill_tree):
    mock_kill_tree.return_value = True

    sup = ProcessSupervisor()
    p1 = MagicMock(); p1.pid = 1
    p2 = MagicMock(); p2.pid = 2
    sup.register("a", p1)
    sup.register("b", p2)

    reaped = sup.reap_all()
    assert reaped == 2
    assert sup.is_running("a") is False
    assert sup.is_running("b") is False


def test_global_supervisor_is_singleton():
    from ytdlp_workstation.engine.process_supervisor import SUPERVISOR as S2
    assert SUPERVISOR is S2
