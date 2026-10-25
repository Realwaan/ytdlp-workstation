import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from ytdlp_workstation.cli.commands import (
    resolve_media_file_by_target,
    cmd_play,
    cmd_reveal,
    cmd_retry,
)
from ytdlp_workstation.cli.command_dispatcher import handle_user_command
from ytdlp_workstation.core.state import AppState, DownloadJob
from ytdlp_workstation.core.history import HistoryManager


def test_resolve_media_file_from_history(tmp_path):
    state = AppState()
    test_video = tmp_path / "test_movie.mp4"
    test_video.write_text("dummy")

    state.config_manager.set("download_dir", str(tmp_path))
    state.history_manager = HistoryManager(history_file=tmp_path / "h.json", archive_file=tmp_path / "a.txt")
    state.history_manager.add_entry({
        "url": "https://test.com/stream.m3u8",
        "status": "Success",
        "preset": "Default",
        "title": "test_movie.mp4",
        "saved_filename": "test_movie.mp4",
        "duration": "120",
    })

    resolved = resolve_media_file_by_target("1", state)
    assert resolved is not None
    assert resolved.name == "test_movie.mp4"


def test_cmd_play_opens_file(tmp_path):
    state = AppState()
    test_video = tmp_path / "test_movie.mp4"
    test_video.write_text("dummy")
    state.config_manager.set("download_dir", str(tmp_path))
    state.history_manager = HistoryManager(history_file=tmp_path / "h.json", archive_file=tmp_path / "a.txt")

    state.history_manager.add_entry({
        "url": "https://test.com/stream.m3u8",
        "status": "Success",
        "preset": "Default",
        "title": "test_movie.mp4",
        "saved_filename": "test_movie.mp4",
        "duration": "120",
    })

    qm = MagicMock()
    with patch("os.startfile") as mock_startfile:
        cmd_play("play 1", qm, state=state)
        mock_startfile.assert_called_once_with(str(test_video))


def test_cmd_reveal_invokes_explorer(tmp_path):
    state = AppState()
    test_video = tmp_path / "test_movie.mp4"
    test_video.write_text("dummy")
    state.config_manager.set("download_dir", str(tmp_path))
    state.history_manager = HistoryManager(history_file=tmp_path / "h.json", archive_file=tmp_path / "a.txt")

    state.history_manager.add_entry({
        "url": "https://test.com/stream.m3u8",
        "status": "Success",
        "preset": "Default",
        "title": "test_movie.mp4",
        "saved_filename": "test_movie.mp4",
        "duration": "120",
    })

    with patch("subprocess.run") as mock_run:
        cmd_reveal("reveal 1", state=state)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "explorer.exe" in args[0]
        assert "test_movie.mp4" in args[1]


def test_cmd_retry_reenqueues_failed_job(capsys, tmp_path):
    state = AppState()
    state.history_manager = HistoryManager(history_file=tmp_path / "h.json", archive_file=tmp_path / "a.txt")
    state.history_manager.add_entry({
        "url": "https://moon.zenoak.top/vd/index-s1080p-v1-a1.m3u8",
        "status": "Failed",
        "preset": "Default",
        "title": "My Failed Movie",
        "error_message": "HTTP Error 403: Forbidden",
    })

    qm = MagicMock()
    cmd_retry("retry 1", qm, state=state)
    qm.enqueue.assert_called_once()
    enqueued_job = qm.enqueue.call_args[0][0]
    assert "moon.zenoak.top" in enqueued_job.url
    # Cloud stream automatically attached streaming referer
    assert "http" in enqueued_job.referer

    captured = capsys.readouterr()
    assert "Re-enqueued failed task" in captured.out


def test_command_dispatcher_routes_reveal_and_retry(capsys, tmp_path):
    state = AppState()
    state.history_manager = HistoryManager(history_file=tmp_path / "h.json", archive_file=tmp_path / "a.txt")
    empty_dir = tmp_path / "empty_dl"
    empty_dir.mkdir()
    state.config_manager.set("download_dir", str(empty_dir))
    qm = MagicMock()

    # reveal without matching files falls back to opening downloads folder
    with patch("os.startfile") as mock_startfile:
        handle_user_command("reveal", qm, state=state)
        mock_startfile.assert_called_once()

    # retry with empty history prints warning
    state.history_manager.clear_history()
    handle_user_command("retry", qm, state=state)
    captured = capsys.readouterr()
    assert "No failed downloads" in captured.out or "history" in captured.out
