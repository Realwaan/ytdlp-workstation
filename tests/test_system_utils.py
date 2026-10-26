"""Tests for system and notification utilities."""

from pathlib import Path
from unittest.mock import patch, MagicMock
from ytdlp_workstation.utils.system import (
    sanitize_filename,
    get_free_disk_space_gb,
    cleanup_orphaned_fragments,
    open_file_or_folder,
    reveal_in_file_manager,
    set_console_title,
    reset_console_title,
)
from ytdlp_workstation.utils.notifications import (
    play_sound,
    send_desktop_notification,
    send_windows_toast,
)


def test_sanitize_filename():
    assert sanitize_filename('My "Favorite" Movie: 2024? <Director*s Cut>|Part/1') == "My Favorite Movie 2024 Directors CutPart1"
    assert sanitize_filename("") == "Untitled"
    assert sanitize_filename("   ") == "Untitled"


def test_get_free_disk_space_gb(tmp_path: Path):
    space = get_free_disk_space_gb(tmp_path)
    assert isinstance(space, float)
    assert space >= 0.0


def test_cleanup_orphaned_fragments(tmp_path: Path):
    frag1 = tmp_path / "stream-Frag1"
    frag2 = tmp_path / "stream-Frag2"
    normal = tmp_path / "normal_video.mp4"
    frag1.write_text("frag")
    frag2.write_text("frag")
    normal.write_text("video")

    cleanup_orphaned_fragments(tmp_path)
    assert not frag1.exists()
    assert not frag2.exists()
    assert normal.exists()


def test_open_file_or_folder_nonexistent(tmp_path: Path):
    assert open_file_or_folder(tmp_path / "does_not_exist.mp4") is False


def test_reveal_in_file_manager_nonexistent(tmp_path: Path):
    assert reveal_in_file_manager(tmp_path / "does_not_exist.mp4") is False


def test_open_file_or_folder_existing(tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    with patch("os.startfile", create=True) as mock_start:
        assert open_file_or_folder(f) is True
        mock_start.assert_called_once()


def test_reveal_in_file_manager_existing(tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    with patch("subprocess.run") as mock_run:
        assert reveal_in_file_manager(f) is True
        mock_run.assert_called_once()


def test_console_title_calls():
    # Should execute without throwing errors
    set_console_title("Test Title")
    reset_console_title()


def test_notifications_execute_cleanly():
    # Calling play_sound with all sound types should not crash
    play_sound("notice", enabled=False)
    play_sound("success", enabled=False)
    play_sound("error", enabled=False)

    # Calling send_desktop_notification disabled
    send_desktop_notification("Test", "Msg", enabled=False)
    send_windows_toast("Test", "Msg", enabled=False)
