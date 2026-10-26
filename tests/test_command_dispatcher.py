"""Tests for Command Dispatcher."""

from unittest.mock import MagicMock, patch

from ytdlp_workstation.cli.command_dispatcher import (
    handle_user_command,
    select_preset_menu,
    toggle_settings_menu,
)
from ytdlp_workstation.core.state import DownloadJob


def test_quit_command_sets_stop_requested():
    queue_mgr = MagicMock()
    handle_user_command("q", queue_mgr)
    # stop_requested set on STATE
    from ytdlp_workstation.core.state import STATE
    assert STATE.stop_requested is True
    STATE.stop_requested = False  # reset for other tests


def test_help_command_prints_banner(capsys):
    queue_mgr = MagicMock()
    handle_user_command("help", queue_mgr)
    captured = capsys.readouterr()
    assert "YT-DLP" in captured.out or "workstation" in captured.out.lower()


def test_queue_status_command(capsys):
    queue_mgr = MagicMock()
    queue_mgr.list_jobs.return_value = {
        "active": [],
        "pending": [],
        "completed": [],
    }
    handle_user_command("queue", queue_mgr)
    captured = capsys.readouterr()
    assert "queue" in captured.out.lower() or "status" in captured.out.lower()


def test_pause_resume_commands():
    queue_mgr = MagicMock()
    handle_user_command("pause", queue_mgr)
    queue_mgr.pause_queue.assert_called_once()

    queue_mgr.reset_mock()
    handle_user_command("resume", queue_mgr)
    queue_mgr.resume_queue.assert_called_once()


def test_cancel_pending_job():
    queue_mgr = MagicMock()
    queue_mgr.cancel_job.return_value = True
    handle_user_command("cancel abc123", queue_mgr)
    queue_mgr.cancel_job.assert_called_once_with("abc123")


def test_cancel_job_not_found():
    queue_mgr = MagicMock()
    queue_mgr.cancel_job.return_value = False
    handle_user_command("cancel nope", queue_mgr)
    queue_mgr.cancel_job.assert_called_once_with("nope")


def test_workers_command():
    queue_mgr = MagicMock()
    handle_user_command("workers 3", queue_mgr)
    queue_mgr.set_max_workers.assert_called_once_with(3)


def test_clearqueue_command():
    queue_mgr = MagicMock()
    queue_mgr.clear_pending.return_value = 5
    handle_user_command("clearqueue", queue_mgr)
    queue_mgr.clear_pending.assert_called_once()


def test_spotify_command_enqueues():
    queue_mgr = MagicMock()
    with patch(
        "ytdlp_workstation.cli.command_dispatcher.enqueue_spotify_download"
    ) as mock_enqueue:
        handle_user_command("spotify https://open.spotify.com/track/123", queue_mgr)
        mock_enqueue.assert_called_once()


def test_preset_shortcut_1080p():
    queue_mgr = MagicMock()
    handle_user_command("1080p https://www.youtube.com/watch?v=123", queue_mgr)
    # Should have enqueued a job
    assert queue_mgr.enqueue.called


def test_sb_toggle():
    queue_mgr = MagicMock()
    handle_user_command("sb", queue_mgr)
    from ytdlp_workstation.core.state import STATE
    # Just verify it doesn't crash and toggles config
    assert "sponsorblock" in STATE.config


def test_history_clear():
    queue_mgr = MagicMock()
    with patch.object(
        STATE := __import__("ytdlp_workstation.core.state", fromlist=["STATE"]).STATE,
        "history_manager",
        new=MagicMock(),
    ) as mock_hist:
        handle_user_command("h clear", queue_mgr)
        mock_hist.clear_history.assert_called_once()


def test_open_command():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.os.startfile", create=True) as mock_start:
        handle_user_command("o", queue_mgr)
        mock_start.assert_called_once()


def test_unrecognized_command(capsys):
    queue_mgr = MagicMock()
    handle_user_command("blahblah xyz", queue_mgr)
    captured = capsys.readouterr()
    assert "Unrecognized" in captured.out


def test_empty_input_noop():
    queue_mgr = MagicMock()
    handle_user_command("", queue_mgr)
    handle_user_command("   ", queue_mgr)
    # Should not crash


def test_nowm_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_nowm") as mock_nowm:
        handle_user_command("nowm https://www.tiktok.com/@user/video/123", queue_mgr)
        mock_nowm.assert_called_once()


def test_sniff_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_sniff") as mock_sniff:
        handle_user_command("sniff https://example.com/movie", queue_mgr)
        mock_sniff.assert_called_once()


def test_clean_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_clean") as mock_clean:
        handle_user_command("clean 1 delogo", queue_mgr)
        mock_clean.assert_called_once()


def test_cmd_nowm_direct_resolve_enqueues(capsys):
    from ytdlp_workstation.cli.commands import cmd_nowm
    from ytdlp_workstation.extractors.no_watermark import NoWatermarkMedia
    queue_mgr = MagicMock()

    mock_media = NoWatermarkMedia(
        direct_url="https://v16-webapp.tiktok.com/play/video.mp4",
        title="Funny Cat Video",
        platform="tiktok",
        referer="https://www.tiktok.com/",
    )

    with patch("ytdlp_workstation.cli.commands.resolve_no_watermark_media", return_value=mock_media):
        cmd_nowm("nowm https://www.tiktok.com/@cat/video/123", queue_mgr)
        queue_mgr.enqueue.assert_called_once()
        job = queue_mgr.enqueue.call_args[0][0]
        assert job.url == "https://v16-webapp.tiktok.com/play/video.mp4"
        assert job.display_title == "Funny Cat Video"
        captured = capsys.readouterr()
        assert "unwatermarked stream" in captured.out.lower()


def test_sub_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_sub") as mock_sub:
        handle_user_command("sub list", queue_mgr)
        mock_sub.assert_called_once()


def test_webhook_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_webhook") as mock_hook:
        handle_user_command("webhook list", queue_mgr)
        mock_hook.assert_called_once()


def test_batch_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_batch") as mock_batch:
        handle_user_command("batch urls.txt", queue_mgr)
        mock_batch.assert_called_once()


def test_norm_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_norm") as mock_norm:
        handle_user_command("norm on", queue_mgr)
        mock_norm.assert_called_once()


def test_lyrics_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_lyrics") as mock_lyrics:
        handle_user_command("lyrics Queen - Bohemian Rhapsody", queue_mgr)
        mock_lyrics.assert_called_once()


def test_dashboard_command_dispatches():
    queue_mgr = MagicMock()
    with patch("ytdlp_workstation.cli.command_dispatcher.cmd_dashboard") as mock_dashboard:
        handle_user_command("dashboard", queue_mgr)
        mock_dashboard.assert_called_once()



