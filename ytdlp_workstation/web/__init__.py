"""
Local Web Dashboard and REST API package for yt-dlp workstation.
"""

from .server import start_dashboard_server, get_dashboard_server, WorkstationWebServer

__all__ = ["start_dashboard_server", "get_dashboard_server", "WorkstationWebServer"]
