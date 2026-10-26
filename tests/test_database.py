"""Tests for SQLite DatabaseEngine."""

import pytest
from pathlib import Path
from ytdlp_workstation.core.database import DatabaseEngine


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_workstation.db"
    return DatabaseEngine(db_path=db_file)


def test_archive_operations(test_db):
    assert test_db.is_archived("video123") is False
    assert test_db.get_archive_count() == 0

    test_db.add_archive_entry("youtube", "video123", "Test Title")
    assert test_db.is_archived("video123") is True
    assert test_db.get_archive_count() == 1

    # Adding duplicate should ignore
    test_db.add_archive_entry("youtube", "video123", "Test Title Again")
    assert test_db.get_archive_count() == 1

    test_db.clear_archive()
    assert test_db.is_archived("video123") is False
    assert test_db.get_archive_count() == 0


def test_job_history_operations(test_db):
    job1 = {
        "id": "job_001",
        "url": "https://youtube.com/watch?v=abc",
        "title": "Song ABC",
        "preset": "Audio MP3",
        "status": "Success",
        "progress": 100.0,
        "size": "5.2 MB",
        "duration": "12s",
        "target_dir": "/downloads"
    }
    test_db.log_job(job1)

    history = test_db.get_history(limit=10)
    assert len(history) == 1
    assert history[0]["id"] == "job_001"
    assert history[0]["title"] == "Song ABC"

    # Search functionality
    search_res = test_db.get_history(search="ABC")
    assert len(search_res) == 1
    no_res = test_db.get_history(search="NonExistent")
    assert len(no_res) == 0

    test_db.clear_history()
    assert len(test_db.get_history()) == 0


def test_subscription_operations(test_db):
    sub_id = test_db.add_subscription(
        url="https://youtube.com/@Channel",
        title="My Channel",
        interval_mins=30,
        preset_id=1,
        folder="ChannelFolder"
    )
    assert sub_id is not None

    subs = test_db.list_subscriptions()
    assert len(subs) == 1
    assert subs[0]["title"] == "My Channel"

    sub = test_db.get_subscription(sub_id)
    assert sub["url"] == "https://youtube.com/@Channel"

    # Update check time
    test_db.update_subscription_check_time(sub_id, new_title="Updated Channel Title")
    updated = test_db.get_subscription(sub_id)
    assert updated["title"] == "Updated Channel Title"
    assert updated["last_checked_at"] is not None

    # Toggle enabled
    test_db.toggle_subscription(sub_id)
    disabled_sub = test_db.get_subscription(sub_id)
    assert disabled_sub["enabled"] == 0
    assert len(test_db.list_subscriptions(enabled_only=True)) == 0

    # Remove subscription
    assert test_db.remove_subscription(sub_id) is True
    assert len(test_db.list_subscriptions()) == 0


def test_webhook_operations(test_db):
    hook_id = test_db.add_webhook("https://discord.com/api/webhooks/test", "all")
    assert hook_id is not None

    hooks = test_db.list_webhooks()
    assert len(hooks) == 1
    assert hooks[0]["url"] == "https://discord.com/api/webhooks/test"

    assert test_db.delete_webhook(hook_id) is True
    assert len(test_db.list_webhooks()) == 0


def test_database_stats_and_vacuum(test_db):
    test_db.add_archive_entry("youtube", "vid1")
    stats = test_db.get_database_stats()
    assert stats["archived_media_count"] == 1
    assert stats["file_size_bytes"] > 0

    # Vacuum executes without error
    test_db.vacuum()
