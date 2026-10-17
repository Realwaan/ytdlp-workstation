"""Tests for Cloud Streaming Referer Engine."""

from ytdlp_workstation.extractors.referer import auto_detect_referer, is_valid_streaming_referer


def test_mainstream_platforms_require_no_referer():
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.twitch.tv/videos/123456",
        "https://vimeo.com/12345678",
        "https://www.tiktok.com/@user/video/12345",
        "https://twitter.com/user/status/123",
        "https://open.spotify.com/track/123"
    ]
    for u in urls:
        assert auto_detect_referer(u) is None


def test_videasy_and_peakpine_auto_attach_referer():
    url = "https://zenoak.top/hls/master.m3u8"
    ref = auto_detect_referer(url, default_referer="https://movy.sx/")
    assert ref == "https://movy.sx/"

    url_custom = "https://videasy.net/stream/video.mp4"
    ref_custom = auto_detect_referer(url_custom, last_seen_website="https://cinejoy.pk/")
    assert ref_custom == "https://cinejoy.pk/"


def test_poisoned_youtube_referer_falls_back_to_movy():
    url = "https://moon.zenoak.top/vd/abc/index-s1080p-v1-a1.m3u8"
    ref = auto_detect_referer(
        url,
        last_seen_website="https://www.youtube.com/",
        default_referer="https://www.youtube.com/",
    )
    assert ref == "https://movy.sx/"
    assert is_valid_streaming_referer("https://www.youtube.com/") is False
    assert is_valid_streaming_referer("https://movy.sx/") is True


def test_megacloud_and_rabbitstream_referers():
    url = "https://megacloud.tv/embed-2/e-1/abc?z="
    assert auto_detect_referer(url) == "https://megacloud.tv/"

    url_rabbit = "https://rabbitstream.net/embed/1234"
    assert auto_detect_referer(url_rabbit) == "https://rabbitstream.net/"


def test_generic_m3u8_stream_attaches_active_streaming_site():
    url = "https://unknown-cdn-server.xyz/video/master.m3u8"
    ref = auto_detect_referer(url, last_seen_website="https://bingebox.ac/")
    assert ref == "https://bingebox.ac/"
