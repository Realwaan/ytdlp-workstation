import pytest
from unittest.mock import patch, MagicMock
from ytdlp_workstation.extractors.web_sniffer import (
    extract_media_from_html,
    sniff_webpage_media,
    _resolve_relative_url,
    SniffedMediaResult,
)


def test_resolve_relative_url():
    base = "https://example.com/articles/news.html"
    assert _resolve_relative_url(base, "/media/video.mp4") == "https://example.com/media/video.mp4"
    assert _resolve_relative_url(base, "//cdn.example.com/video.mp4") == "https://cdn.example.com/video.mp4"
    assert _resolve_relative_url(base, "https://cdn.other.com/v.mp4") == "https://cdn.other.com/v.mp4"


def test_extract_media_og_video():
    html = """
    <html>
      <head>
        <title>Exclusive Interview - Tech News</title>
        <meta property="og:video" content="https://cdn.example.com/videos/interview.mp4" />
      </head>
      <body><h1>News</h1></body>
    </html>
    """
    res = extract_media_from_html(html, "https://technews.com/post/1")
    assert res is not None
    assert res.media_url == "https://cdn.example.com/videos/interview.mp4"
    assert res.title == "Exclusive Interview"
    assert res.source_type == "og:video"
    assert res.referer == "https://technews.com/post/1"


def test_extract_media_json_ld():
    html = """
    <html>
      <head>
        <title>Cooking Masterclass</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "VideoObject",
          "name": "How to make sourdough",
          "contentUrl": "https://media.food.com/sourdough.m3u8"
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    res = extract_media_from_html(html, "https://food.com/recipes/bread")
    assert res is not None
    assert res.media_url == "https://media.food.com/sourdough.m3u8"
    assert res.title == "How to make sourdough"
    assert res.is_m3u8 is True
    assert res.source_type == "json-ld"


def test_extract_media_html5_video():
    html = """
    <html>
      <head><title>Space Launch Video</title></head>
      <body>
        <div class="player">
          <video controls>
            <source src="/assets/launch-recap.mp4" type="video/mp4" />
          </video>
        </div>
      </body>
    </html>
    """
    res = extract_media_from_html(html, "https://space.org/news/launch")
    assert res is not None
    assert res.media_url == "https://space.org/assets/launch-recap.mp4"
    assert res.title == "Space Launch Video"
    assert res.source_type == "html5"


def test_extract_media_player_config():
    html = """
    <html>
      <head><title>Live Game Stream</title></head>
      <body>
        <script>
          jwplayer("myPlayer").setup({
            file: "https://streams.sports.com/game1/index.m3u8",
            width: "100%"
          });
        </script>
      </body>
    </html>
    """
    res = extract_media_from_html(html, "https://sports.com/watch/game1")
    assert res is not None
    assert res.media_url == "https://streams.sports.com/game1/index.m3u8"
    assert res.is_m3u8 is True
    assert res.source_type == "player-config"


def test_sniff_webpage_media_mocked():
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.read.return_value = b'<html><head><title>Web Video</title><meta property="og:video" content="https://v.com/a.mp4" /></head></html>'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = sniff_webpage_media("https://example.com/video")
        assert res is not None
        assert res.media_url == "https://v.com/a.mp4"
