"""
Local Web Dashboard & REST API server.
Provides a modern glassmorphic web interface to monitor downloads, manage queues,
and trigger new media jobs from any web browser on the local machine.
"""

__all__ = ["start_dashboard_server", "get_dashboard_server", "WorkstationWebServer"]

import os
import sys
import json
import socket
import logging
import threading
import urllib.parse
from pathlib import Path
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List

from ..core.state import DownloadJob, AppState, resolve_state
from ..core.presets import PRESETS
from ..core.database import DB
from ..utils.system import get_free_disk_space_gb, open_file_or_folder, reveal_in_file_manager
from ..extractors.url_detector import clean_url, is_valid_media_url

logger = logging.getLogger("ytdlp_workstation.web")

# Cache the singleton web server instance
GLOBAL_WEB_SERVER: Optional["WorkstationWebServer"] = None

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YT-DLP Workstation Pro | Dashboard</title>
  <meta name="description" content="High-performance media workstation download manager, queue controller, and real-time telemetry dashboard.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #070913;
      --bg-surface: rgba(18, 23, 38, 0.72);
      --bg-card: rgba(26, 33, 56, 0.65);
      --bg-input: rgba(13, 17, 28, 0.85);
      --border-glass: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(16, 185, 129, 0.45);
      --accent-emerald: #10b981;
      --accent-cyan: #06b6d4;
      --accent-violet: #8b5cf6;
      --accent-rose: #f43f5e;
      --accent-amber: #f59e0b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-subtle: #64748b;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --shadow-glow: 0 0 25px rgba(16, 185, 129, 0.18);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    body {
      background-color: var(--bg-dark);
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(16, 185, 129, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 85% 80%, rgba(6, 182, 212, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 50% 50%, rgba(139, 92, 246, 0.04) 0%, transparent 60%);
      background-attachment: fixed;
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* Layout Header */
    header {
      background: rgba(11, 15, 26, 0.8);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border-glass);
      position: sticky;
      top: 0;
      z-index: 100;
      padding: 0.85rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }

    .brand-logo {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 1.25rem;
      color: #041019;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.35);
    }

    .brand-title h1 {
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(to right, #ffffff, #94a3b8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .brand-title p {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
    }

    .telemetry-badges {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .badge-pill {
      background: var(--bg-surface);
      border: 1px solid var(--border-glass);
      border-radius: 30px;
      padding: 0.35rem 0.85rem;
      font-size: 0.8rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      backdrop-filter: blur(10px);
    }

    .live-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: var(--accent-emerald);
      box-shadow: 0 0 10px var(--accent-emerald);
      animation: pulse 2s infinite ease-in-out;
    }

    @keyframes pulse {
      0% { opacity: 0.5; transform: scale(0.9); }
      50% { opacity: 1; transform: scale(1.15); }
      100% { opacity: 0.5; transform: scale(0.9); }
    }

    /* Main Container */
    main {
      flex: 1;
      max-width: 1200px;
      width: 100%;
      margin: 0 auto;
      padding: 2rem;
      display: flex;
      flex-direction: column;
      gap: 2rem;
    }

    /* Action Card - New Download */
    .hero-card {
      background: var(--bg-surface);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-glass);
      border-radius: var(--radius-lg);
      padding: 1.75rem 2rem;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
      position: relative;
      overflow: hidden;
    }

    .hero-card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: linear-gradient(90deg, #10b981, #06b6d4, #8b5cf6);
    }

    .card-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 1.25rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .input-row {
      display: flex;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }

    .input-row input {
      flex: 1;
      background: var(--bg-input);
      border: 1px solid var(--border-glass);
      border-radius: var(--radius-md);
      padding: 0.85rem 1.25rem;
      font-size: 0.95rem;
      color: var(--text-main);
      outline: none;
      transition: all 0.2s ease;
    }

    .input-row input:focus {
      border-color: var(--accent-emerald);
      box-shadow: 0 0 15px rgba(16, 185, 129, 0.2);
    }

    .btn-submit {
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: #ffffff;
      border: none;
      border-radius: var(--radius-md);
      padding: 0 1.75rem;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      transition: all 0.2s ease;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
    }

    .btn-submit:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4);
    }

    .btn-submit:active {
      transform: translateY(0);
    }

    .presets-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
    }

    .preset-label {
      font-size: 0.85rem;
      color: var(--text-muted);
      font-weight: 500;
      margin-right: 0.5rem;
    }

    .preset-chip {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border-glass);
      border-radius: 20px;
      padding: 0.4rem 0.9rem;
      font-size: 0.8rem;
      font-weight: 500;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .preset-chip:hover {
      background: rgba(255, 255, 255, 0.09);
      color: var(--text-main);
    }

    .preset-chip.active {
      background: rgba(16, 185, 129, 0.15);
      border-color: var(--accent-emerald);
      color: var(--accent-emerald);
      font-weight: 600;
    }

    /* Section Panels */
    .panel {
      background: var(--bg-surface);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-glass);
      border-radius: var(--radius-lg);
      padding: 1.5rem;
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
    }

    .panel-header h2 {
      font-size: 1.1rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }

    .count-tag {
      background: rgba(255, 255, 255, 0.06);
      border-radius: 12px;
      padding: 0.15rem 0.6rem;
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--accent-cyan);
    }

    /* Active Downloads Cards */
    .downloads-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 1rem;
    }

    .download-card {
      background: var(--bg-card);
      border: 1px solid var(--border-glass);
      border-radius: var(--radius-md);
      padding: 1.25rem 1.5rem;
      transition: border-color 0.2s ease;
      position: relative;
    }

    .download-card:hover {
      border-color: rgba(6, 182, 212, 0.3);
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.75rem;
    }

    .media-info {
      flex: 1;
      padding-right: 1.5rem;
    }

    .media-title {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 0.25rem;
      word-break: break-all;
    }

    .media-meta {
      font-size: 0.8rem;
      color: var(--text-muted);
      display: flex;
      gap: 1rem;
    }

    .btn-cancel {
      background: rgba(244, 63, 94, 0.12);
      border: 1px solid rgba(244, 63, 94, 0.25);
      color: var(--accent-rose);
      border-radius: var(--radius-sm);
      padding: 0.35rem 0.75rem;
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .btn-cancel:hover {
      background: var(--accent-rose);
      color: #ffffff;
    }

    /* Progress Bar */
    .progress-track {
      background: rgba(0, 0, 0, 0.4);
      height: 8px;
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 0.6rem;
      position: relative;
    }

    .progress-fill {
      background: linear-gradient(90deg, #10b981, #06b6d4);
      height: 100%;
      border-radius: 4px;
      width: 0%;
      transition: width 0.3s ease;
      box-shadow: 0 0 10px rgba(6, 182, 212, 0.5);
    }

    .card-bottom-stats {
      display: flex;
      justify-content: space-between;
      font-size: 0.82rem;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-muted);
    }

    .speed-tag {
      color: var(--accent-emerald);
      font-weight: 600;
    }

    /* History Table */
    .table-container {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }

    th {
      padding: 0.75rem 1rem;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-subtle);
      border-bottom: 1px solid var(--border-glass);
      font-weight: 600;
    }

    td {
      padding: 0.9rem 1rem;
      font-size: 0.85rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-muted);
    }

    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
      color: var(--text-main);
    }

    .status-badge {
      display: inline-block;
      padding: 0.2rem 0.55rem;
      border-radius: 12px;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
    }

    .status-completed {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
    }

    .status-failed {
      background: rgba(244, 63, 94, 0.15);
      color: var(--accent-rose);
    }

    .empty-state {
      padding: 2.5rem;
      text-align: center;
      color: var(--text-subtle);
      font-size: 0.9rem;
    }

    footer {
      text-align: center;
      padding: 1.5rem;
      color: var(--text-subtle);
      font-size: 0.8rem;
      border-top: 1px solid var(--border-glass);
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div class="brand-title">
        <h1>YT-DLP WORKSTATION PRO</h1>
        <p>Studio Engine Telemetry v2.0</p>
      </div>
    </div>
    <div class="telemetry-badges">
      <div class="badge-pill" id="badge-disk">
        <span>💾 Free Disk:</span>
        <strong id="disk-space">-- GB</strong>
      </div>
      <div class="badge-pill" id="badge-workers">
        <span>⚙️ Concurrency:</span>
        <strong id="worker-count">--</strong>
      </div>
      <div class="badge-pill" id="badge-status">
        <div class="live-dot"></div>
        <span>Online</span>
      </div>
    </div>
  </header>

  <main>
    <!-- Hero / Enqueue Form -->
    <section class="hero-card">
      <div class="card-title">🚀 Instant Media Extraction</div>
      <div class="input-row">
        <input type="text" id="input-url" placeholder="Paste YouTube, TikTok, Spotify, Instagram, or m3u8 stream URL..." autocomplete="off">
        <button class="btn-submit" id="btn-download" onclick="submitDownload()">
          <span>Download</span>
        </button>
      </div>
      <div class="presets-row">
        <span class="preset-label">Format Preset:</span>
        <div class="preset-chip active" data-id="1" onclick="selectPreset(1, this)">Best 4K/8K (MP4)</div>
        <div class="preset-chip" data-id="3" onclick="selectPreset(3, this)">1080p Full HD</div>
        <div class="preset-chip" data-id="4" onclick="selectPreset(4, this)">720p HD</div>
        <div class="preset-chip" data-id="7" onclick="selectPreset(7, this)">320k MP3 Audio</div>
        <div class="preset-chip" data-id="9" onclick="selectPreset(9, this)">Lossless FLAC</div>
        <div class="preset-chip" data-id="12" onclick="selectPreset(12, this)">MKV (All Subs)</div>
      </div>
    </section>

    <!-- Active Downloads -->
    <section class="panel">
      <div class="panel-header">
        <h2>⚡ Active Downloads <span class="count-tag" id="active-count">0</span></h2>
      </div>
      <div class="downloads-grid" id="active-downloads-container">
        <div class="empty-state">No downloads currently active. Queue is idle.</div>
      </div>
    </section>

    <!-- Queued Downloads -->
    <section class="panel">
      <div class="panel-header">
        <h2>⏳ Waiting in Queue <span class="count-tag" id="queue-count">0</span></h2>
      </div>
      <div class="downloads-grid" id="queued-downloads-container">
        <div class="empty-state">Queue is currently empty.</div>
      </div>
    </section>

    <!-- Completed History -->
    <section class="panel">
      <div class="panel-header">
        <h2>📜 Recent Completed History <span class="count-tag" id="history-count">0</span></h2>
      </div>
      <div class="table-container">
        <table id="history-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Title / File</th>
              <th>Preset</th>
              <th>Size</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody id="history-body">
            <tr>
              <td colspan="5" class="empty-state">Loading history...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>

  <footer>
    YT-DLP Workstation Pro &bull; Local Autonomous Telemetry Server &bull; Port 8484
  </footer>

  <script>
    let selectedPresetId = 1;

    function selectPreset(id, el) {
      selectedPresetId = id;
      document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
    }

    async function submitDownload() {
      const urlInput = document.getElementById('input-url');
      const url = urlInput.value.trim();
      if (!url) return;

      const btn = document.getElementById('btn-download');
      btn.innerText = 'Queuing...';
      btn.disabled = true;

      try {
        const resp = await fetch('/api/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url, preset: selectedPresetId })
        });
        const data = await resp.json();
        if (data.success) {
          urlInput.value = '';
          pollStatus();
        } else {
          alert('Error queuing download: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Network error communicating with workstation server.');
      } finally {
        btn.innerText = 'Download';
        btn.disabled = false;
      }
    }

    async function cancelJob(jobId) {
      try {
        await fetch('/api/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: jobId })
        });
        pollStatus();
      } catch (err) {
        console.error('Failed to cancel job:', err);
      }
    }

    async function pollStatus() {
      try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        renderDashboard(data);
      } catch (e) {
        console.error('Polling error:', e);
      }
    }

    function renderDashboard(data) {
      // Update system telemetry
      if (data.system) {
        document.getElementById('disk-space').innerText = data.system.free_disk_gb + ' GB';
        document.getElementById('worker-count').innerText = data.system.max_workers;
      }

      // Update Active Downloads
      const activeEl = document.getElementById('active-downloads-container');
      const activeJobs = data.active || [];
      document.getElementById('active-count').innerText = activeJobs.length;

      if (activeJobs.length === 0) {
        activeEl.innerHTML = '<div class="empty-state">No downloads currently active. Queue is idle.</div>';
      } else {
        activeEl.innerHTML = activeJobs.map(job => `
          <div class="download-card" id="card-${job.id}">
            <div class="card-top">
              <div class="media-info">
                <div class="media-title">${escapeHtml(job.title || job.url)}</div>
                <div class="media-meta">
                  <span>Preset: ${escapeHtml(job.preset_name || 'Standard')}</span>
                  <span>ID: ${job.id}</span>
                </div>
              </div>
              <button class="btn-cancel" onclick="cancelJob('${job.id}')">Cancel</button>
            </div>
            <div class="progress-track">
              <div class="progress-fill" style="width: ${Math.min(100, Math.max(0, job.progress))}%"></div>
            </div>
            <div class="card-bottom-stats">
              <span>${job.progress.toFixed(1)}% &bull; ${escapeHtml(job.downloaded_str || '0 MB')} / ${escapeHtml(job.total_str || 'Unknown')}</span>
              <span class="speed-tag">⚡ ${escapeHtml(job.speed_str || '0 KB/s')} ${job.eta_str ? '&bull; ETA: ' + escapeHtml(job.eta_str) : ''}</span>
            </div>
          </div>
        `).join('');
      }

      // Update Queued Downloads
      const queueEl = document.getElementById('queued-downloads-container');
      const queuedJobs = data.queued || [];
      document.getElementById('queue-count').innerText = queuedJobs.length;

      if (queuedJobs.length === 0) {
        queueEl.innerHTML = '<div class="empty-state">Queue is currently empty.</div>';
      } else {
        queueEl.innerHTML = queuedJobs.map((job, idx) => `
          <div class="download-card">
            <div class="card-top">
              <div class="media-info">
                <div class="media-title">#${idx + 1} - ${escapeHtml(job.title || job.url)}</div>
                <div class="media-meta">
                  <span>Preset: ${escapeHtml(job.preset_name || 'Standard')}</span>
                </div>
              </div>
              <button class="btn-cancel" onclick="cancelJob('${job.id}')">Remove</button>
            </div>
          </div>
        `).join('');
      }

      // Update History Table
      const historyBody = document.getElementById('history-body');
      const historyItems = data.history || [];
      document.getElementById('history-count').innerText = historyItems.length;

      if (historyItems.length === 0) {
        historyBody.innerHTML = '<tr><td colspan="5" class="empty-state">No downloads recorded yet.</td></tr>';
      } else {
        historyBody.innerHTML = historyItems.map(item => `
          <tr>
            <td>
              <span class="status-badge ${item.status === 'completed' ? 'status-completed' : 'status-failed'}">
                ${item.status}
              </span>
            </td>
            <td><strong>${escapeHtml(item.title || item.url)}</strong></td>
            <td>${escapeHtml(item.preset_name || 'Standard')}</td>
            <td>${escapeHtml(item.file_size || '--')}</td>
            <td>${item.duration_sec ? item.duration_sec + 's' : '--'}</td>
          </tr>
        `).join('');
      }
    }

    function escapeHtml(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    // Auto-poll telemetry every 1000ms
    setInterval(pollStatus, 1000);
    pollStatus();
  </script>
</body>
</html>
"""


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Handles REST API requests and serves the workstation dashboard."""

    def log_message(self, format, *args):
        # Silence default stderr logging to keep terminal output clean
        pass

    @property
    def server_instance(self) -> "WorkstationWebServer":
        return getattr(self.server, "workstation_instance")

    def _send_json_response(self, data: Any, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/status":
            ws = self.server_instance
            state = ws.state
            queue_mgr = ws.queue_mgr

            active_list: List[Dict[str, Any]] = []
            for j in queue_mgr.get_active_jobs():
                p_name = PRESETS.get(j.preset_override or 1, {}).get("name", "Default")
                active_list.append({
                    "id": j.id,
                    "url": j.url,
                    "title": j.display_title or j.saved_filename or j.url,
                    "progress": j.progress_pct,
                    "speed_str": j.speed_str,
                    "eta_str": j.eta_str,
                    "downloaded_str": j.downloaded_str,
                    "total_str": j.total_str,
                    "preset_name": p_name,
                })

            queued_list: List[Dict[str, Any]] = []
            for j in queue_mgr.get_queued_jobs():
                p_name = PRESETS.get(j.preset_override or 1, {}).get("name", "Default")
                queued_list.append({
                    "id": j.id,
                    "url": j.url,
                    "title": j.display_title or j.url,
                    "preset_name": p_name,
                })

            history_items = DB.get_history(limit=15)

            system_info = {
                "free_disk_gb": get_free_disk_space_gb(Path(state.config.get("download_dir", "."))),
                "max_workers": state.config.get("max_concurrent_downloads", 2),
                "loudness_norm": state.config.get("audio_loudness_norm", False),
                "lyrics": state.config.get("download_lyrics", False),
            }

            self._send_json_response({
                "active": active_list,
                "queued": queued_list,
                "history": history_items,
                "system": system_info,
            })
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8", errors="replace") if content_length > 0 else "{}"

        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}

        ws = self.server_instance

        if path == "/api/download":
            url = clean_url(payload.get("url", "").strip())
            preset_id = int(payload.get("preset", 1))

            if not url or not is_valid_media_url(url):
                self._send_json_response({"success": False, "error": "Invalid media URL"}, status=400)
                return

            force_audio = preset_id in (7, 8, 9, 10, 11)
            job = DownloadJob(
                url=url,
                preset_override=preset_id,
                force_audio=force_audio,
            )
            ws.queue_mgr.enqueue(job)
            self._send_json_response({"success": True, "job_id": job.id})
            return

        if path == "/api/cancel":
            job_id = payload.get("job_id")
            if not job_id:
                self._send_json_response({"success": False, "error": "Missing job_id"}, status=400)
                return

            res = ws.queue_mgr.cancel(job_id)
            self._send_json_response({"success": res})
            return

        if path == "/api/retry":
            job_id = payload.get("job_id")
            if not job_id:
                self._send_json_response({"success": False, "error": "Missing job_id"}, status=400)
                return

            # Find matching item in DB
            items = DB.get_history(limit=50)
            target = next((item for item in items if str(item.get("id")) == str(job_id) or str(item.get("url")) == str(job_id)), None)
            if target and target.get("url"):
                new_job = DownloadJob(url=target["url"], preset_override=target.get("preset_id", 1))
                ws.queue_mgr.enqueue(new_job)
                self._send_json_response({"success": True, "job_id": new_job.id})
                return

            self._send_json_response({"success": False, "error": "Job not found in history"}, status=404)
            return

        self.send_error(404, "Not Found")


class WorkstationWebServer:
    """Threaded HTTP Server for the local workstation dashboard."""

    def __init__(self, queue_mgr, state: Optional[AppState] = None, port: int = 8484):
        self.queue_mgr = queue_mgr
        self.state = resolve_state(state)
        self.port = port
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False

    def is_running(self) -> bool:
        return self._running and self.server is not None

    def start(self, open_browser: bool = False) -> bool:
        if self.is_running():
            if open_browser:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{self.port}")
            return True

        # Check if port is available or find adjacent free port
        for candidate_port in [self.port, self.port + 1, self.port + 2]:
            try:
                server = ThreadingHTTPServer(("127.0.0.1", candidate_port), DashboardRequestHandler)
                setattr(server, "workstation_instance", self)
                self.server = server
                self.port = candidate_port
                break
            except OSError:
                continue

        if not self.server:
            logger.error("Could not bind workstation web server to local port.")
            return False

        self._running = True
        self.thread = threading.Thread(target=self._run_server, daemon=True, name="WebDashboardServer")
        self.thread.start()

        if open_browser:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.port}")

        return True

    def _run_server(self):
        try:
            self.server.serve_forever()
        except Exception:
            pass
        finally:
            self._running = False

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        self._running = False


def start_dashboard_server(queue_mgr, state: Optional[AppState] = None, port: int = 8484, open_browser: bool = True) -> WorkstationWebServer:
    """Start or retrieve the singleton workstation dashboard web server."""
    global GLOBAL_WEB_SERVER
    if GLOBAL_WEB_SERVER is None or not GLOBAL_WEB_SERVER.is_running():
        GLOBAL_WEB_SERVER = WorkstationWebServer(queue_mgr, state=state, port=port)
        GLOBAL_WEB_SERVER.start(open_browser=open_browser)
    elif open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{GLOBAL_WEB_SERVER.port}")
    return GLOBAL_WEB_SERVER


def get_dashboard_server() -> Optional[WorkstationWebServer]:
    """Retrieve active web server instance if running."""
    return GLOBAL_WEB_SERVER
