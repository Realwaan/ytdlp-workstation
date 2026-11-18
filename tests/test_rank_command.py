"""Tests for YouTube Automation Ranking command and workflows."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdlp_workstation.cli.command_dispatcher import handle_user_command
from ytdlp_workstation.cli.commands import get_next_rank_number, cmd_rank
from ytdlp_workstation.cli.completion import TOP_LEVEL_COMMANDS, SUBCOMMAND_MAP
from ytdlp_workstation.core.state import AppState, DownloadJob


@pytest.fixture(autouse=True)
def _no_network_resolver():
    """cmd_rank resolves TikTok links over the network; keep unit tests offline (~3s each otherwise)."""
    with patch("ytdlp_workstation.cli.commands.resolve_no_watermark_media", return_value=None), \
         patch("ytdlp_workstation.cli.commands.play_sound"):
        yield


def test_get_next_rank_number_empty_dir(tmp_path: Path):
    assert get_next_rank_number(tmp_path) == 1


def test_get_next_rank_number_sequential_files(tmp_path: Path):
    for i in range(1, 6):
        (tmp_path / f"{i}.mp4").write_text("dummy")
    assert get_next_rank_number(tmp_path) == 6


def test_get_next_rank_number_with_non_integer_files(tmp_path: Path):
    (tmp_path / "intro.mp4").write_text("dummy")
    (tmp_path / "1.mp4").write_text("dummy")
    (tmp_path / "2.mp4").write_text("dummy")
    assert get_next_rank_number(tmp_path) == 3


def test_cmd_rank_with_explicit_number_and_url(tmp_path: Path):
    queue_mgr = MagicMock()
    state = AppState()
    state.set_config("rank_download_dir", str(tmp_path))

    cmd_rank("rank 6 https://www.tiktok.com/@test/video/1234567890", queue_mgr, state=state)

    queue_mgr.enqueue.assert_called_once()
    job: DownloadJob = queue_mgr.enqueue.call_args[0][0]
    assert "Rank #6" in job.display_title
    assert job.target_dir == str(tmp_path)
    assert f"6.%(ext)s" in job.custom_output_template
    assert job.preset_override == 1
    assert job.needs_quality_prompt is False


def test_cmd_rank_dir_subcommand(tmp_path: Path):
    queue_mgr = MagicMock()
    state = AppState()
    new_dir = tmp_path / "custom_src"

    cmd_rank(f"rank dir {new_dir}", queue_mgr, state=state)

    assert state.config.get("rank_download_dir") == str(new_dir.resolve())
    assert new_dir.exists()


def test_cmd_rank_list_subcommand(tmp_path: Path, capsys):
    queue_mgr = MagicMock()
    state = AppState()
    state.set_config("rank_download_dir", str(tmp_path))
    (tmp_path / "1.mp4").write_bytes(b"0" * 1024 * 1024)

    cmd_rank("rank list", queue_mgr, state=state)

    captured = capsys.readouterr()
    assert "1.mp4" in captured.out
    assert "Next incremental slot" in captured.out


def test_command_dispatcher_routes_pure_digit(tmp_path: Path):
    queue_mgr = MagicMock()
    state = AppState()
    state.set_config("rank_download_dir", str(tmp_path))

    handle_user_command("7 https://www.tiktok.com/@test/video/9876543210", queue_mgr, state=state)

    queue_mgr.enqueue.assert_called_once()
    job: DownloadJob = queue_mgr.enqueue.call_args[0][0]
    assert "Rank #7" in job.display_title
    assert f"7.%(ext)s" in job.custom_output_template


def test_command_dispatcher_routes_hashtag_digit(tmp_path: Path):
    queue_mgr = MagicMock()
    state = AppState()
    state.set_config("rank_download_dir", str(tmp_path))

    handle_user_command("#8 https://www.tiktok.com/@test/video/1122334455", queue_mgr, state=state)

    queue_mgr.enqueue.assert_called_once()
    job: DownloadJob = queue_mgr.enqueue.call_args[0][0]
    assert "Rank #8" in job.display_title
    assert f"8.%(ext)s" in job.custom_output_template


def test_cmd_rank_uses_clipboard_when_url_omitted(tmp_path: Path):
    queue_mgr = MagicMock()
    state = AppState()
    state.set_config("rank_download_dir", str(tmp_path))

    with patch("ytdlp_workstation.cli.commands.get_clipboard_text", return_value="https://www.tiktok.com/@test/video/7788990011"):
        cmd_rank("rank 9", queue_mgr, state=state)

    queue_mgr.enqueue.assert_called_once()
    job: DownloadJob = queue_mgr.enqueue.call_args[0][0]
    assert "Rank #9" in job.display_title
    assert "7788990011" in job.url
    assert f"9.%(ext)s" in job.custom_output_template


def test_rank_in_autocomplete():
    assert "rank" in TOP_LEVEL_COMMANDS
    assert "rank" in SUBCOMMAND_MAP
    assert "dir" in SUBCOMMAND_MAP["rank"]
    assert "list" in SUBCOMMAND_MAP["rank"]


def test_get_next_rank_number_accounts_for_inflight_jobs(tmp_path: Path):
    (tmp_path / "1.mp4").write_text("dummy")

    active_job = DownloadJob(
        url="https://www.tiktok.com/@test/video/111",
        target_dir=str(tmp_path),
        custom_output_template=str(tmp_path / "2.%(ext)s"),
    )
    queued_job = DownloadJob(
        url="https://www.tiktok.com/@test/video/222",
        target_dir=str(tmp_path),
        custom_output_template=str(tmp_path / "3.%(ext)s"),
    )
    other_dir_job = DownloadJob(
        url="https://www.tiktok.com/@test/video/333",
        target_dir=str(tmp_path / "other"),
        custom_output_template=str(tmp_path / "other" / "99.%(ext)s"),
    )

    queue_mgr = MagicMock()
    queue_mgr.get_active_jobs.return_value = [active_job]
    queue_mgr.get_queued_jobs.return_value = [queued_job, other_dir_job]

    assert get_next_rank_number(tmp_path, queue_mgr=queue_mgr) == 4
