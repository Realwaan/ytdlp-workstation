import pytest
from ytdlp_workstation.cli.completion import (
    get_completion_candidates,
    CompletionEngine,
    _common_prefix,
    TOP_LEVEL_COMMANDS,
)
from ytdlp_workstation.core.state import AppState, DownloadJob


def test_common_prefix():
    assert _common_prefix(["merge", "merger"]) == "merge"
    assert _common_prefix(["cancel", "clear", "clip"]) == "c"
    assert _common_prefix(["play"]) == "play"
    assert _common_prefix([]) == ""


def test_top_level_command_completion_unique():
    start, end, prefix, candidates = get_completion_candidates("mer", 3)
    assert prefix == "mer"
    assert candidates == ["merge"]
    assert start == 0
    assert end == 3


def test_top_level_command_completion_spotify():
    start, end, prefix, candidates = get_completion_candidates("spo", 3)
    assert prefix == "spo"
    assert candidates == ["spotify"]


def test_quality_shortcuts_completion():
    start, end, prefix, candidates = get_completion_candidates("108", 3)
    assert prefix == "108"
    assert candidates == ["1080p"]

    start, end, prefix, candidates = get_completion_candidates("4", 1)
    assert "4k" in candidates


def test_subcommand_completion_help():
    start, end, prefix, candidates = get_completion_candidates("help st", 7)
    assert prefix == "st"
    assert candidates == ["streaming"]

    start, end, prefix, candidates = get_completion_candidates("help ", 5)
    assert "downloads" in candidates
    assert "audio" in candidates
    assert "settings" in candidates


def test_subcommand_completion_cancel_all():
    start, end, prefix, candidates = get_completion_candidates("cancel a", 8)
    assert prefix == "a"
    assert "all" in candidates


def test_completion_engine_single_tab_expands_with_space():
    engine = CompletionEngine()
    buf = list("mer")
    new_buf, new_cursor, changed = engine.handle_tab(buf, 3)
    assert changed is True
    assert "".join(new_buf) == "merge "
    assert new_cursor == 6


def test_completion_engine_cycles_multiple_candidates():
    engine = CompletionEngine()
    # "cla" -> "clear", "clearqueue"
    buf = list("clear")
    # LCP of clear and clearqueue is "clear"
    new_buf, new_cursor, changed = engine.handle_tab(buf, 5)
    assert changed is True
    # First cycle pick
    first_pick = "".join(new_buf)
    assert first_pick in ("clear", "clearqueue")

    # Second tab cycles to next candidate
    new_buf2, new_cursor2, changed2 = engine.handle_tab(new_buf, new_cursor)
    assert changed2 is True
    second_pick = "".join(new_buf2)
    assert second_pick != first_pick
    assert second_pick in ("clear", "clearqueue")


def test_completion_with_queue_jobs():
    from ytdlp_workstation.queue.manager import QueueManager
    qm = QueueManager(max_workers=1)
    job1 = DownloadJob(url="https://test.com/video1")
    qm.active_jobs[job1.id] = job1

    start, end, prefix, candidates = get_completion_candidates("cancel ", 7, queue_mgr=qm)
    assert "all" in candidates
    assert "1" in candidates
    assert job1.id[:8] in candidates
    qm.stop_requested = True
