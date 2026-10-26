"""Tests for URL detection and sanitation."""

from ytdlp_workstation.extractors.url_detector import (
    is_valid_media_url,
    extract_media_url,
    clean_url
)


def test_clean_url_strips_tracking_params():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=12345&utm_source=twitter"
    cleaned = clean_url(url)
    assert "utm_source" not in cleaned
    assert "si=12345" not in cleaned
    assert "watch?v=dQw4w9WgXcQ" in cleaned

    # Test leading tracking parameter preserves the '?' delimiter
    leading_track = "https://www.youtube.com/watch?si=12345&v=dQw4w9WgXcQ"
    cleaned_lead = clean_url(leading_track)
    assert cleaned_lead == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Test shortlink with only tracking parameter
    short_track = "https://youtu.be/dQw4w9WgXcQ?si=abcdef123"
    cleaned_short = clean_url(short_track)
    assert cleaned_short == "https://youtu.be/dQw4w9WgXcQ"



def test_is_valid_media_url_supported_domains():
    valid_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "https://spotify.link/AbCdEf123",
        "https://www.tiktok.com/@user/video/1234567890",
        "https://vt.tiktok.com/ZSjR1234/",
        "https://v.douyin.com/iR1234/",
        "https://www.capcut.com/template-detail/12345",
        "https://www.xiaohongshu.com/explore/12345",
        "https://xhslink.com/a/12345",
        "https://www.kuaishou.com/short-video/12345",
        "https://www.threads.net/@user/post/12345",
        "https://b23.tv/av12345",
        "https://www.instagram.com/reel/C12345/",
        "https://x.com/user/status/123456789",
        "https://twitter.com/user/status/123456789",
        "https://kick.com/streamer",
        "https://rumble.com/v12345-video.html",
        "https://cdn.example.com/videos/stream.m3u8",
        "https://storage.googleapis.com/test.mp4"
    ]
    for u in valid_urls:
        assert is_valid_media_url(u, media_filter_only=True) is True, f"Failed for {u}"


def test_is_valid_media_url_invalid_text():
    invalid_texts = [
        "hello world",
        "not a url",
        "https://example.com/article/read-me",
        "ftp://invalid/file.iso",
        ""
    ]
    for text in invalid_texts:
        assert is_valid_media_url(text, media_filter_only=True) is False


def test_extract_media_url():
    text = "Hey check out this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ it is great!"
    extracted = extract_media_url(text)
    assert extracted == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
