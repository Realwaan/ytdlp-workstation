"""
User alert notifications and audio feedback.
Provides native Windows 10/11 desktop toast notifications and chimes with cross-platform fallbacks.
"""

import os
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
    if not enabled or not HAS_WINSOUND:
        return
    try:
        if sound_type == "notice":
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif sound_type == "success":
            winsound.MessageBeep(winsound.MB_OK)
        elif sound_type == "error":
            winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass


def send_windows_toast(title: str, message: str, enabled: bool = True) -> None:
    """Send native Windows 10/11 Desktop Notification banner in background."""
    if not enabled or os.name != "nt":
        return

    def _toast():
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
        try:
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
        except Exception:
            pass

    threading.Thread(target=_toast, daemon=True).start()
