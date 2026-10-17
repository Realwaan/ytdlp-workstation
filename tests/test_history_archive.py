"""Tests for History and Download Archive Manager."""

from pathlib import Path
from ytdlp_workstation.core.history import HistoryManager


def test_history_logging_and_clear(tmp_path):
    hist_file = tmp_path / "history.json"
    arch_file = tmp_path / "archive.txt"
    mgr = HistoryManager(history_file=hist_file, archive_file=arch_file)

    mgr.add_entry({
        "url": "https://www.youtube.com/watch?v=123",
        "title": "Test Video",
        "status": "Success"
    })

    entries = mgr.get_entries()
    assert len(entries) == 1
    assert entries[0]["title"] == "Test Video"

    mgr.clear_history()
    assert len(mgr.get_entries()) == 0


def test_download_archive_tracking(tmp_path):
    hist_file = tmp_path / "history.json"
    arch_file = tmp_path / "archive.txt"
    mgr = HistoryManager(history_file=hist_file, archive_file=arch_file)

    assert mgr.is_archived("dQw4w9WgXcQ") is False

    mgr.add_archive_entry("youtube", "dQw4w9WgXcQ")
    assert mgr.is_archived("dQw4w9WgXcQ") is True

    # Reload from disk to verify persistence
    new_mgr = HistoryManager(history_file=hist_file, archive_file=arch_file)
    assert new_mgr.is_archived("dQw4w9WgXcQ") is True
