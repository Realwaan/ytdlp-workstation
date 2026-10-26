"""Tests for batch URL file import."""

from pathlib import Path
from unittest.mock import MagicMock
from ytdlp_workstation.core.state import AppState
from ytdlp_workstation.cli.commands import cmd_batch


def test_cmd_batch_no_arg(capsys):
    qm = MagicMock()
    cmd_batch("batch", qm)
    captured = capsys.readouterr()
    assert "Usage: batch" in captured.out


def test_cmd_batch_file_not_found(capsys, tmp_path: Path):
    qm = MagicMock()
    cmd_batch(f"batch {tmp_path / 'nonexistent.txt'}", qm)
    captured = capsys.readouterr()
    assert "File not found" in captured.out


def test_cmd_batch_enqueues_valid_urls_skips_comments(capsys, tmp_path: Path):
    batch_file = tmp_path / "urls.txt"
    batch_file.write_text("""
# My Download List
https://www.youtube.com/watch?v=video1&si=track123

# Vimeo video
https://vimeo.com/123456789

# Invalid line
not_a_valid_url_here

https://youtu.be/shortlink123
""", encoding="utf-8")

    qm = MagicMock()
    state = AppState()
    cmd_batch(f'batch "{batch_file}"', qm, state=state)

    # 3 valid URLs enqueued
    assert qm.enqueue.call_count == 3
    urls_enqueued = [call[0][0].url for call in qm.enqueue.call_args_list]
    assert "https://www.youtube.com/watch?v=video1" in urls_enqueued
    assert "https://vimeo.com/123456789" in urls_enqueued
    assert "https://youtu.be/shortlink123" in urls_enqueued

    captured = capsys.readouterr()
    assert "Successfully enqueued 3 task(s)" in captured.out
