"""
User alert notifications and audio feedback.
Provides native Windows 10/11 desktop toast notifications and chimes with cross-platform fallbacks.
"""

import os
import sys
import shutil
import base64
import threading
import subprocess

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


def play_sound(sound_type: str = "notice", enabled: bool = True) -> None:
    """Play audio feedback chime."""
    if not enabled:
        return
    if HAS_WINSOUND:
        try:
            if sound_type == "notice":
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            elif sound_type == "success":
                winsound.MessageBeep(winsound.MB_OK)
            elif sound_type == "error":
                winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass
    else:
        # Cross-platform terminal bell fallback
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass


def send_desktop_notification(title: str, message: str, enabled: bool = True) -> None:
    """Send native desktop notification across Windows, macOS, and Linux."""
    if not enabled:
        return

    def _toast():
        try:
            if os.name == "nt":
                safe_title = (title.replace("&", "&amp;")
                                   .replace("<", "&lt;")
                                   .replace(">", "&gt;")
                                   .replace('"', "&quot;")
                                   .replace("'", "&apos;"))
                safe_msg = (message.replace("&", "&amp;")
                                   .replace("<", "&lt;")
                                   .replace(">", "&gt;")
                                   .replace('"', "&quot;")
                                   .replace("'", "&apos;"))

                script = f"""
$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::new()
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{safe_title}</text><text>{safe_msg}</text></binding></visual></toast>')
$toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)
"""
                encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
                subprocess.run(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                )
            elif sys.platform == "darwin":
                # macOS AppleScript notification
                escaped_title = title.replace('"', '\\"')
                escaped_msg = message.replace('"', '\\"')
                subprocess.run(
                    ["osascript", "-e", f'display notification "{escaped_msg}" with title "{escaped_title}"'],
                    capture_output=True,
                    check=False
                )
            elif shutil.which("notify-send"):
                # Linux libnotify
                subprocess.run(
                    ["notify-send", title, message],
                    capture_output=True,
                    check=False
                )
        except Exception:
            pass

    threading.Thread(target=_toast, daemon=True).start()


# Backward-compatible alias
send_windows_toast = send_desktop_notification

