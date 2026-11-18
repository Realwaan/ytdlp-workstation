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


def test_archive_lookup_is_exact_match_not_substring(tmp_path):
    """O(1) index must match exact video IDs only — no false substring positives."""
    hist_file = tmp_path / "history.json"
    arch_file = tmp_path / "archive.txt"
    arch_file.write_text("youtube abc123\ntiktok xyz999\n", encoding="utf-8")
    mgr = HistoryManager(history_file=hist_file, archive_file=arch_file)

    assert mgr.is_archived("abc123") is True
    assert mgr.is_archived("xyz999") is True
    # Substring overlaps must NOT match: "bc123" is inside "abc123" but is a different ID
    assert mgr.is_archived("bc123") is False
    assert mgr.is_archived("yz999") is False
    assert mgr.is_archived("") is False


def test_archive_index_built_for_entries_without_extractor_prefix(tmp_path):
    """Legacy single-token archive lines index the whole line as the ID."""
    hist_file = tmp_path / "history.json"
    arch_file = tmp_path / "archive.txt"
    arch_file.write_text("legacy_id_only\n", encoding="utf-8")
    mgr = HistoryManager(history_file=hist_file, archive_file=arch_file)

    assert mgr.is_archived("legacy_id_only") is True
    assert mgr.is_archived("other") is False
