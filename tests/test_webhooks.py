"""Tests for WebhookDispatcher."""

import json
from unittest.mock import patch, MagicMock
from ytdlp_workstation.core.events import EventType, AppEvent
from ytdlp_workstation.core.webhooks import WebhookDispatcher


def test_format_payload_discord():
    dispatcher = WebhookDispatcher()
    event_success = AppEvent(
        event_type=EventType.JOB_FINISHED,
        data={
            "title": "Cool Video",
            "preset": "1080p",
            "size": "10 MB",
            "duration": "15s",
        },
    )
    payload = dispatcher.format_payload("https://discord.com/api/webhooks/123/abc", event_success)
    assert "embeds" in payload
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert "Download Complete" in embed["title"]
    assert embed["color"] == 0x2ECC71
    assert "Cool Video" in embed["description"]

    # Failed job
    event_fail = AppEvent(
        event_type=EventType.JOB_FAILED,
        data={"title": "Bad Video", "error": "HTTP 404"},
    )
    fail_payload = dispatcher.format_payload("https://discord.com/api/webhooks/123/abc", event_fail)
    assert fail_payload["embeds"][0]["color"] == 0xE74C3C

    # Subscription found new
    event_sub = AppEvent(
        event_type=EventType.SUBSCRIPTION_FOUND_NEW,
        data={"title": "New Upload", "video_id": "vid999"},
    )
    sub_payload = dispatcher.format_payload("https://discordapp.com/api/webhooks/123/abc", event_sub)
    assert sub_payload["embeds"][0]["color"] == 0x3498DB


def test_format_payload_generic():
    dispatcher = WebhookDispatcher()
    event = AppEvent(
        event_type=EventType.JOB_FINISHED,
        data={"title": "Generic Test"},
    )
    payload = dispatcher.format_payload("https://api.mycustomserver.com/webhook", event)
    assert payload["event"] == "job_finished"
    assert payload["data"]["title"] == "Generic Test"


def test_dispatch_payload_success():
    dispatcher = WebhookDispatcher()
    event = AppEvent(
        event_type=EventType.JOB_FINISHED,
        data={"title": "Success Test"},
    )

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = dispatcher.dispatch_payload("https://example.com/webhook", event)
        assert res is True


def test_dispatch_payload_failure():
    dispatcher = WebhookDispatcher()
    event = AppEvent(
        event_type=EventType.JOB_FINISHED,
        data={"title": "Fail Test"},
    )

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res = dispatcher.dispatch_payload("https://example.com/webhook", event)
        assert res is False


def test_dispatcher_lifecycle_and_test_ping():
    dispatcher = WebhookDispatcher()
    dispatcher.install()
    assert dispatcher._installed is True
    dispatcher.uninstall()
    assert dispatcher._installed is False

    with patch.object(dispatcher, "dispatch_payload", return_value=True) as mock_dispatch:
        assert dispatcher.test_webhook("https://discord.com/api/webhooks/123") is True
        mock_dispatch.assert_called_once()
