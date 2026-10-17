"""Tests for Presets and Quality Shortcuts."""

from ytdlp_workstation.core.presets import (
    PRESETS,
    QUALITY_SHORTCUT_MAP,
    get_preset,
    resolve_format_sort
)


def test_presets_coverage():
    assert len(PRESETS) >= 12
    for pid in range(1, 13):
        p = get_preset(pid)
        assert "name" in p
        assert "format" in p
        assert "extract_audio" in p


def test_quality_shortcuts():
    assert "1080p" in QUALITY_SHORTCUT_MAP
    assert "720p" in QUALITY_SHORTCUT_MAP
    assert "4k" in QUALITY_SHORTCUT_MAP
    assert "mp3" in QUALITY_SHORTCUT_MAP
    assert "flac" in QUALITY_SHORTCUT_MAP

    pid_1080, is_audio_1080, _ = QUALITY_SHORTCUT_MAP["1080p"]
    assert pid_1080 == 3
    assert is_audio_1080 is False

    pid_mp3, is_audio_mp3, _ = QUALITY_SHORTCUT_MAP["mp3"]
    assert pid_mp3 == 7
    assert is_audio_mp3 is True


def test_resolve_format_sort():
    compat = resolve_format_sort("compatibility")
    assert "vcodec:h264" in compat
    assert "acodec:aac" in compat

    quality = resolve_format_sort("quality")
    assert "vcodec:av01" in quality

    auto = resolve_format_sort("auto")
    assert auto is None
