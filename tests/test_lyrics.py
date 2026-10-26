"""
Unit and integration tests for Synchronized Lyrics (.lrc) fetching and parsing via LRCLIB.
"""

import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from ytdlp_workstation.core.state import AppState
from ytdlp_workstation.extractors.lyrics import (
    fetch_lyrics,
    search_lyrics,
    save_lrc_file,
    fetch_and_save_lyrics_for_media,
)
from ytdlp_workstation.cli.commands import cmd_lyrics


SAMPLE_LRCLIB_PAYLOAD = {
    "id": 12345,
    "trackName": "Bohemian Rhapsody",
    "artistName": "Queen",
    "albumName": "A Night at the Opera",
    "duration": 354,
    "instrumental": False,
    "plainLyrics": "Is this the real life? Is this just fantasy?",
    "syncedLyrics": "[00:00.00] Is this the real life?\n[00:03.50] Is this just fantasy?\n[00:08.10] Caught in a landslide",
}


def test_fetch_lyrics_exact_match():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_LRCLIB_PAYLOAD).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = fetch_lyrics(track_name="Bohemian Rhapsody", artist_name="Queen")
        assert res is not None
        assert res["track_name"] == "Bohemian Rhapsody"
        assert res["artist_name"] == "Queen"
        assert "[00:00.00]" in res["synced_lyrics"]
        assert "real life" in res["plain_lyrics"]


def test_search_lyrics_fallback():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps([SAMPLE_LRCLIB_PAYLOAD]).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = search_lyrics("Queen Bohemian Rhapsody")
        assert res is not None
        assert res["artist_name"] == "Queen"
        assert "[00:00.00]" in res["synced_lyrics"]


def test_save_lrc_file(tmp_path):
    mp3_file = tmp_path / "Queen - Bohemian Rhapsody.mp3"
    mp3_file.write_bytes(b"dummy mp3 data")

    lrc_content = "[00:01.00] Line 1\n[00:05.00] Line 2\n"
    lrc_path = save_lrc_file(mp3_file, lrc_content)

    assert lrc_path is not None
    assert lrc_path.exists()
    assert lrc_path.suffix == ".lrc"
    assert lrc_path.stem == mp3_file.stem
    assert "Line 1" in lrc_path.read_text(encoding="utf-8")


def test_fetch_and_save_lyrics_for_media(tmp_path):
    audio_file = tmp_path / "song.flac"
    audio_file.write_bytes(b"dummy flac data")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_LRCLIB_PAYLOAD).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        saved = fetch_and_save_lyrics_for_media(audio_file, artist="Queen", track="Bohemian Rhapsody")
        assert saved is not None
        assert saved.exists()
        assert saved.name == "song.lrc"
        assert "Caught in a landslide" in saved.read_text(encoding="utf-8")


def test_cmd_lyrics_toggle_and_search(capsys):
    state = AppState()
    state.config["download_lyrics"] = False

    # Check status
    cmd_lyrics("lyrics", state=state)
    out = capsys.readouterr().out
    assert "DISABLED" in out

    # Toggle on
    cmd_lyrics("lyrics on", state=state)
    assert state.config["download_lyrics"] is True

    # Search lyrics in terminal
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_LRCLIB_PAYLOAD).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        cmd_lyrics("lyrics Queen - Bohemian Rhapsody", state=state)
        out = capsys.readouterr().out
        assert "Queen" in out
        assert "Bohemian Rhapsody" in out
        assert "Synchronized (.lrc)" in out
