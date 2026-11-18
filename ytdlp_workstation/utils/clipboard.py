"""
Universal cross-platform clipboard reader and writer.
Tries pyperclip, then Windows native ctypes user32 API, then PowerShell subprocess fallback.
"""

import os
import ctypes
import subprocess

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_HAS_WIN32_CTYPES = False
_user32 = None
_kernel32 = None

if os.name == "nt":
    try:
        _user32 = ctypes.windll.user32
        _kernel32 = ctypes.windll.kernel32
        _user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
        _user32.IsClipboardFormatAvailable.restype = ctypes.c_bool
        _user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        _user32.OpenClipboard.restype = ctypes.c_bool
        _user32.CloseClipboard.argtypes = []
        _user32.CloseClipboard.restype = ctypes.c_bool
        _user32.EmptyClipboard.argtypes = []
        _user32.EmptyClipboard.restype = ctypes.c_bool
        _user32.GetClipboardData.argtypes = [ctypes.c_uint]
        _user32.GetClipboardData.restype = ctypes.c_void_p
        _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        _user32.SetClipboardData.restype = ctypes.c_void_p
        _kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        _kernel32.GlobalAlloc.restype = ctypes.c_void_p
        _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        _kernel32.GlobalLock.restype = ctypes.c_void_p
        _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        _kernel32.GlobalUnlock.restype = ctypes.c_bool
        _HAS_WIN32_CTYPES = True
    except Exception:
        _HAS_WIN32_CTYPES = False


def get_clipboard_text() -> str:
    """Universal clipboard reader: checks CF_UNICODETEXT first on Windows so
    non-text clipboard contents (images/files) never spawn PowerShell."""
    ctypes_failed = not _HAS_WIN32_CTYPES
    if os.name == "nt" and _HAS_WIN32_CTYPES:
        try:
            if not _user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
                return ""
        except Exception:
            ctypes_failed = True

    if HAS_PYPERCLIP:
        try:
            val = pyperclip.paste()
            if val and isinstance(val, str):
                return val
        except Exception:
            pass

    if os.name == "nt":
        if _HAS_WIN32_CTYPES and not ctypes_failed:
            try:
                if _user32.OpenClipboard(None):
                    try:
                        handle = _user32.GetClipboardData(_CF_UNICODETEXT)
                        if handle:
                            ptr = _kernel32.GlobalLock(handle)
                            if ptr:
                                try:
                                    return ctypes.c_wchar_p(ptr).value or ""
                                finally:
                                    _kernel32.GlobalUnlock(handle)
                    finally:
                        _user32.CloseClipboard()
                return ""
            except Exception:
                ctypes_failed = True

        if ctypes_failed:
            try:
                res = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                    text=True, stderr=subprocess.DEVNULL, timeout=1
                )
                return res.strip()
            except Exception:
                pass

    return ""


def set_clipboard_text(text: str) -> bool:
    """Universal clipboard writer: uses pyperclip if available, else native Windows ctypes."""
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass

    if os.name == "nt" and _HAS_WIN32_CTYPES:
        try:
            if _user32.OpenClipboard(None):
                try:
                    _user32.EmptyClipboard()
                    data = text.encode("utf-16-le") + b"\x00\x00"
                    h_mem = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
                    if h_mem:
                        ptr = _kernel32.GlobalLock(h_mem)
                        if ptr:
                            try:
                                ctypes.memmove(ptr, data, len(data))
                            finally:
                                _kernel32.GlobalUnlock(h_mem)
                            _user32.SetClipboardData(_CF_UNICODETEXT, h_mem)
                            return True
                finally:
                    _user32.CloseClipboard()
        except Exception:
            pass

    return False
