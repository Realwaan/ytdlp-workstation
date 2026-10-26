"""
Unit tests for the Local Web Dashboard and REST API telemetry server.
"""

import json
import time
import urllib.request
import urllib.error
from unittest.mock import MagicMock, patch

from ytdlp_workstation.core.state import DownloadJob, AppState
from ytdlp_workstation.queue.manager import QueueManager
from ytdlp_workstation.web.server import WorkstationWebServer, start_dashboard_server, get_dashboard_server
from ytdlp_workstation.cli.commands import cmd_dashboard


def test_web_server_lifecycle_and_endpoints():
    state = AppState()
    queue_mgr = QueueManager(state=state, max_workers=1)

    # Use a non-standard port for testing
    server = WorkstationWebServer(queue_mgr, state=state, port=18484)
    started = server.start(open_browser=False)
    assert started is True
    assert server.is_running() is True
    port = server.port

    try:
        # 1. Test GET / serves HTML dashboard
        req_root = urllib.request.Request(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(req_root, timeout=3.0) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "YT-DLP WORKSTATION PRO" in html
            assert "Instant Media Extraction" in html

        # 2. Test GET /api/status returns JSON telemetry
        req_status = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
        with urllib.request.urlopen(req_status, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "active" in data
            assert "queued" in data
            assert "history" in data
            assert "system" in data
            assert "free_disk_gb" in data["system"]

        # 3. Test POST /api/download enqueues job
        dl_payload = json.dumps({"url": "https://www.youtube.com/watch?v=dlweb123", "preset": 3}).encode("utf-8")
        req_dl = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/download",
            data=dl_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_dl, timeout=3.0) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode("utf-8"))
            assert res_data.get("success") is True
            job_id = res_data.get("job_id")
            assert job_id is not None

        # Verify queued item is visible via /api/status
        with urllib.request.urlopen(req_status, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            total_jobs = len(data["active"]) + len(data["queued"])
            assert total_jobs >= 1

        # 4. Test POST /api/cancel cancels job
        cancel_payload = json.dumps({"job_id": job_id}).encode("utf-8")
        req_cancel = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/cancel",
            data=cancel_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_cancel, timeout=3.0) as resp:
            assert resp.status == 200
            cancel_res = json.loads(resp.read().decode("utf-8"))
            assert cancel_res.get("success") is True

    finally:
        server.stop()
        queue_mgr.stop_requested = True
        assert server.is_running() is False


def test_cmd_dashboard_launches_server(capsys):
    state = AppState()
    queue_mgr = QueueManager(state=state, max_workers=1)

    with patch("webbrowser.open") as mock_open:
        cmd_dashboard("dashboard 18485", queue_mgr, state=state)
        out = capsys.readouterr().out
        assert "Web Dashboard live at" in out
        assert "http://127.0.0.1:18485" in out
        assert mock_open.called

    # Clean up singleton
    srv = get_dashboard_server()
    if srv:
        srv.stop()
    queue_mgr.stop_requested = True
