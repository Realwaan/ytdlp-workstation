"""Tests for Spotify Metadata Engine."""

from ytdlp_workstation.extractors.spotify import (
    is_spotify_url,
    build_music_search_query
)


def test_is_spotify_url():
    assert is_spotify_url("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT") is True
    assert is_spotify_url("https://open.spotify.com/album/4eLPsYPBmXABThSJ821sqY") is True
    assert is_spotify_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M") is True
    assert is_spotify_url("https://spotify.link/AbCdEf123") is True
    assert is_spotify_url("https://youtube.com/watch?v=123") is False


def test_build_music_search_query():
    q_ytm = build_music_search_query("Queen", "Bohemian Rhapsody", provider="ytm")
    assert q_ytm.startswith("ytsearch1:")
    assert "Queen - Bohemian Rhapsody Audio" in q_ytm

    q_yt = build_music_search_query("Daft Punk", "Get Lucky", provider="yt")
    assert q_yt.startswith("ytsearch1:")
    assert "Daft Punk - Get Lucky Audio" in q_yt
