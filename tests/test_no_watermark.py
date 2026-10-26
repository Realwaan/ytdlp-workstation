import json
import pytest
from unittest.mock import patch, MagicMock
from ytdlp_workstation.extractors.no_watermark import (
    is_no_watermark_candidate,
    clean_douyin_watermark_url,
    resolve_tiktok_clean,
    resolve_douyin_clean,
    resolve_capcut_clean,
    resolve_no_watermark_media,
    CleanMediaResult,
)


def test_is_no_watermark_candidate():
    assert is_no_watermark_candidate("https://www.tiktok.com/@user/video/1234") is True
    assert is_no_watermark_candidate("https://vt.tiktok.com/ZSjR1234/") is True
    assert is_no_watermark_candidate("https://v.douyin.com/iR1234/") is True
    assert is_no_watermark_candidate("https://www.capcut.com/template-detail/123") is True
    assert is_no_watermark_candidate("https://www.youtube.com/watch?v=123") is False


def test_clean_douyin_watermark_url():
    raw_wm_url = "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0200fg10000abc&watermark=1"
    clean_url = clean_douyin_watermark_url(raw_wm_url)
    assert "/play/" in clean_url
    assert "/playwm/" not in clean_url
    assert "watermark" not in clean_url


def test_resolve_tiktok_clean_mocked():
    mock_payload = {
        "code": 0,
        "msg": "success",
        "data": {
            "id": "7429182391283",
            "title": "Clean Sunset Video",
            "play": "https://v16-webapp-prime.tiktokcdn.com/clean_video.mp4",
            "wmplay": "https://v16-webapp-prime.tiktokcdn.com/watermarked_video.mp4",
            "duration": 15,
            "author": {
                "nickname": "Traveler"
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("ytdlp_workstation.extractors.no_watermark.follow_redirects", side_effect=lambda u, **kwargs: u):
        result = resolve_tiktok_clean("https://www.tiktok.com/@traveler/video/7429182391283")
        assert result is not None
        assert "clean_video.mp4" in result.direct_url
        assert "watermarked" not in result.direct_url
        assert "Sunset Video" in result.title
        assert result.platform == "TikTok (No-Watermark)"


def test_resolve_douyin_clean_mocked():
    mock_payload = {
        "aweme_detail": {
            "desc": "Amazing Drone Shot",
            "author": {
                "nickname": "Pilot"
            },
            "video": {
                "play_addr": {
                    "url_list": [
                        "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=123"
                    ]
                }
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("ytdlp_workstation.extractors.no_watermark.follow_redirects", return_value="https://www.douyin.com/video/7123456789012345678"):
        result = resolve_douyin_clean("https://v.douyin.com/iR1234/")
        assert result is not None
        # Must have rewritten playwm to play
        assert "/play/" in result.direct_url
        assert "/playwm/" not in result.direct_url
        assert "Drone Shot" in result.title


def test_resolve_capcut_clean_mocked():
    mock_html = """
    <html>
      <head>
        <title>Cinematic Intro - CapCut</title>
        <meta property="og:video" content="https://sf16-ies-music.capcut.com/raw_template_stream.mp4" />
      </head>
      <body></body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_html.encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("ytdlp_workstation.extractors.no_watermark.follow_redirects", side_effect=lambda u, **kwargs: u):
        result = resolve_capcut_clean("https://www.capcut.com/template-detail/12345")
        assert result is not None
        assert result.direct_url == "https://sf16-ies-music.capcut.com/raw_template_stream.mp4"
        assert "Cinematic Intro" in result.title


def test_resolve_no_watermark_dispatcher():
    with patch("ytdlp_workstation.extractors.no_watermark.resolve_tiktok_clean") as mock_tt:
        mock_tt.return_value = CleanMediaResult(
            direct_url="https://test.com/clean.mp4",
            title="Clean"
        )
        res = resolve_no_watermark_media("https://www.tiktok.com/@user/video/123")
        assert res is not None
        assert res.direct_url == "https://test.com/clean.mp4"
