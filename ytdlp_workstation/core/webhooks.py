"""
Webhook notification dispatcher.

Listens to EventBus for job completion and failure events and broadcasts
JSON payloads or Discord embeds to registered webhook URLs asynchronously.
"""

from __future__ import annotations

import json
import time
import threading
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
from .events import BUS, EventType, AppEvent
from .database import DB


class WebhookDispatcher:
    """Dispatches event notifications to HTTP webhooks."""

    def __init__(self, db=None, timeout: float = 6.0):
        self.db = db or DB
        self.timeout = timeout
        self._installed = False

    def install(self) -> None:
        """Subscribe to Job lifecycle events on EventBus."""
        if not self._installed:
            BUS.subscribe(EventType.JOB_FINISHED, self._on_event)
            BUS.subscribe(EventType.JOB_FAILED, self._on_event)
            BUS.subscribe(EventType.JOB_CANCELLED, self._on_event)
            BUS.subscribe(EventType.SUBSCRIPTION_FOUND_NEW, self._on_event)
            self._installed = True

    def uninstall(self) -> None:
        """Unsubscribe from EventBus."""
        if self._installed:
            BUS.unsubscribe(EventType.JOB_FINISHED, self._on_event)
            BUS.unsubscribe(EventType.JOB_FAILED, self._on_event)
            BUS.unsubscribe(EventType.JOB_CANCELLED, self._on_event)
            BUS.unsubscribe(EventType.SUBSCRIPTION_FOUND_NEW, self._on_event)
            self._installed = False

    def _on_event(self, event: AppEvent) -> None:
        """Worker callback invoked when a subscribed event fires."""
        try:
            hooks = self.db.list_webhooks()
            if not hooks:
                return

            for h in hooks:
                h_url = h.get("url", "")
                h_types = h.get("event_types", "all")
                if not h_url:
                    continue
                if h_types != "all" and event.event_type.value not in h_types:
                    continue

                t = threading.Thread(
                    target=self.dispatch_payload,
                    args=(h_url, event),
                    name=f"WebhookPost-{event.event_type.value}",
                    daemon=True,
                )
                t.start()
        except Exception:
            pass

    def dispatch_payload(self, webhook_url: str, event: AppEvent) -> bool:
        """Send formatted event payload to a webhook URL."""
        try:
            payload = self.format_payload(webhook_url, event)
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "YTDLP-Workstation/2.0 (WebhookDispatcher)",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = getattr(resp, "status", getattr(resp, "code", 200))
                return 200 <= int(status_code) < 300
        except Exception:
            return False

    def format_payload(self, webhook_url: str, event: AppEvent) -> Dict[str, Any]:
        """Format event payload based on destination (Discord embed vs generic JSON)."""
        is_discord = "discord.com" in webhook_url or "discordapp.com" in webhook_url
        d = event.data

        if is_discord:
            status = d.get("status", "Completed")
            is_success = event.event_type == EventType.JOB_FINISHED
            color = 0x2ECC71 if is_success else 0xE74C3C  # Green or Red

            if event.event_type == EventType.SUBSCRIPTION_FOUND_NEW:
                title = "📺 Channel Subscription: New Video Queued"
                color = 0x3498DB  # Blue
                desc = f"**Title:** {d.get('title', 'Unknown')}\n**Video ID:** `{d.get('video_id', '')}`"
            elif is_success:
                title = "⚡ Download Complete"
                desc = (
                    f"**Title:** {d.get('title', 'Media')}\n"
                    f"**Preset:** {d.get('preset', 'Default')}\n"
                    f"**Size:** {d.get('size', 'N/A')}\n"
                    f"**Duration:** {d.get('duration', 'N/A')}"
                )
            else:
                title = f"⚠️ Download {status}"
                desc = (
                    f"**Title:** {d.get('title') or d.get('url', 'Media')}\n"
                    f"**Error:** `{d.get('error') or 'Process interrupted'}`"
                )

            return {
                "username": "YT-DLP Workstation",
                "embeds": [
                    {
                        "title": title,
                        "description": desc,
                        "color": color,
                        "footer": {"text": "YT-DLP Supercharged Workstation v2.0"},
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(event.timestamp)),
                    }
                ],
            }

        # Generic webhook JSON schema
        return {
            "event": event.event_type.value,
            "timestamp": event.timestamp,
            "data": event.data,
        }

    def test_webhook(self, webhook_url: str) -> bool:
        """Send a test ping notification to verify webhook configuration."""
        test_event = AppEvent(
            event_type=EventType.JOB_FINISHED,
            data={
                "id": "test_ping",
                "title": "YT-DLP Workstation Webhook Test",
                "preset": "1080p Full HD",
                "size": "42.0 MB",
                "duration": "4.2s",
                "status": "Success",
                "url": "https://github.com/Realwaan/ytdlp-workstation",
            },
        )
        return self.dispatch_payload(webhook_url, test_event)


# Global singleton dispatcher
WEBHOOK_DISPATCHER = WebhookDispatcher()
