import pytest
from unittest.mock import patch, MagicMock
from ytdlp_workstation.cli.ui import (
    print_banner,
    print_help,
    parse_speed_to_bytes,
    format_speed_bytes,
    format_aggregate_status,
)
from ytdlp_workstation.core.state import AppState, DownloadJob


def test_compact_banner_line_count(capsys):
    state = AppState()
    with patch("ytdlp_workstation.cli.ui.clear_screen"):
        print_banner(active_workers=2, state=state)
    captured = capsys.readouterr()
    lines = [l for l in captured.out.split("\n") if l.strip()]
    # Banner must be under 12 lines tall to prevent scrolling standard 24-row terminals
    assert len(lines) <= 12
    assert "YT-DLP" in captured.out
    assert "Engine" in captured.out
    assert "Workers" in captured.out
    assert "Quality" in captured.out


def test_print_help_topics(capsys):
    # Overview
    print_help()
    captured = capsys.readouterr()
    assert "HELP & COMMAND REFERENCE" in captured.out

    # Downloads
    print_help("downloads")
    captured = capsys.readouterr()
    assert "DOWNLOAD COMMANDS" in captured.out
    assert "1080p" in captured.out

    # Audio
    print_help("audio")
    captured = capsys.readouterr()
    assert "AUDIO & MUSIC COMMANDS" in captured.out
    assert "spotify" in captured.out

    # Streaming
    print_help("streaming")
    captured = capsys.readouterr()
    assert "CLOUD STREAMING" in captured.out
    assert "merge" in captured.out

    # Queue
    print_help("queue")
    captured = capsys.readouterr()
    assert "QUEUE & WORKER" in captured.out
    assert "cancel" in captured.out

    # Media
    print_help("media")
    captured = capsys.readouterr()
    assert "MEDIA ACTIONS" in captured.out
    assert "reveal" in captured.out

    # Settings
    print_help("settings")
    captured = capsys.readouterr()
    assert "SETTINGS & PREFERENCES" in captured.out


def test_parse_speed_to_bytes():
    assert parse_speed_to_bytes("100KiB/s") == 100 * 1024
    assert parse_speed_to_bytes("12.5MiB/s") == 12.5 * (1024 ** 2)
    assert parse_speed_to_bytes("1.5GiB/s") == 1.5 * (1024 ** 3)
    assert parse_speed_to_bytes("--") == 0.0
    assert parse_speed_to_bytes("invalid") == 0.0


def test_format_speed_bytes():
    assert "KiB/s" in format_speed_bytes(500 * 1024)
    assert "MiB/s" in format_speed_bytes(25 * (1024 ** 2))
    assert "GiB/s" in format_speed_bytes(2 * (1024 ** 3))


def test_format_aggregate_status():
    j1 = DownloadJob(url="https://test.com/1")
    j1.speed_str = "10.0MiB/s"
    j2 = DownloadJob(url="https://test.com/2")
    j2.speed_str = "15.0MiB/s"

    agg = format_aggregate_status([j1, j2], pending_count=3, is_paused=False)
    assert "MULTI-WORKER" in agg
    assert "2 Active" in agg
    assert "25.0 MiB/s" in agg
    assert "Pending:" in agg
    assert "3" in agg
    assert "RUNNING" in agg
