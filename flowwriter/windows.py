"""Small, optional Windows integrations; other platforms use native defaults."""
from __future__ import annotations

import ctypes
from functools import lru_cache
import sys

APP_ID = "FlowWriter.Studio"


@lru_cache(maxsize=1)
def user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    for name, args, result in (
        ("GetForegroundWindow", [], ctypes.c_void_p),
        ("IsWindow", [ctypes.c_void_p], ctypes.c_int),
        ("IsIconic", [ctypes.c_void_p], ctypes.c_int),
        ("ShowWindow", [ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
        ("SetForegroundWindow", [ctypes.c_void_p], ctypes.c_int),
        ("GetWindowTextW", [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
        ("GetClassNameW", [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
        ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
        ("OpenClipboard", [ctypes.c_void_p], ctypes.c_int),
        ("CloseClipboard", [], ctypes.c_int),
        ("GetClipboardSequenceNumber", [], ctypes.c_uint32),
    ):
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def configure_process():
    if sys.platform != "win32":
        return
    shell = ctypes.WinDLL("shell32")
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def apply_titlebar(window_id: int) -> bool:
    """Use a light native caption; explicit colors are supported on Windows 11."""
    if sys.platform != "win32":
        return False
    try:
        api = ctypes.WinDLL("dwmapi")
        function = api.DwmSetWindowAttribute
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        function.restype = ctypes.c_long
        success = False
        # COLORREF uses 0x00BBGGRR. Neutral RGB values are identical in either order.
        for attribute, value in ((20, 0), (35, 0xF5F5F5), (36, 0x262626), (34, 0xE5E5E5)):
            data = ctypes.c_uint32(value)
            success |= function(window_id, attribute, ctypes.byref(data), ctypes.sizeof(data)) == 0
        return success
    except (OSError, AttributeError):
        return False
