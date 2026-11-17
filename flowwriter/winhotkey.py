"""Windows global shortcut using the operating system's own registration (RegisterHotKey).

Why not only pynput: its hook watches keys but cannot tell that another app already owns the
same combination, and it does not stop the key reaching that app. Registering with Windows
fixes both: if another app has the shortcut we are told ("already used"), and while we hold
it, no other app sees it.
"""
from __future__ import annotations
import sys
import threading

from .shortcuts import parse_hotkey, validate_hotkey

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
_VK_NAMED = {
    "space": 0x20, "tab": 0x09, "return": 0x0D, "enter": 0x0D, "backspace": 0x08,
    "del": 0x2E, "delete": 0x2E, "ins": 0x2D, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


def to_windows(text: str, vk_scan=None) -> tuple[int, int]:
    """'Ctrl+Alt+Space' -> (modifier flags, virtual-key code). Raises ValueError."""
    mods, key = parse_hotkey(validate_hotkey(text))
    flags = 0
    for name, bit in (("ctrl", MOD_CONTROL), ("alt", MOD_ALT), ("shift", MOD_SHIFT), ("meta", MOD_WIN)):
        if name in mods:
            flags |= bit
    low = key.lower()
    if low in _VK_NAMED:
        vk = _VK_NAMED[low]
    elif low.startswith("f") and low[1:].isdigit():
        vk = 0x70 + int(low[1:]) - 1
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif len(key) == 1 and vk_scan is not None:
        vk = vk_scan(key) & 0xFF          # punctuation depends on the keyboard layout
    else:
        raise ValueError(f"'{key}' cannot be used as a shortcut key.")
    return flags, vk


class WindowsHotkey:
    """Owns one registered shortcut on its own thread. start() returns '' or a plain-English error."""

    def __init__(self, text: str, callback):
        self.text, self.callback = text, callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error = ""

    def start(self) -> str:
        if sys.platform != "win32":
            return "Windows shortcut registration is only available on Windows."
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            flags, vk = to_windows(self.text, lambda ch: user32.VkKeyScanW(ord(ch)))
        except ValueError as exc:
            return str(exc)
        self._thread = threading.Thread(target=self._run, args=(flags, vk), name="flowwriter-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            return f"The shortcut {self.text} did not register in time."
        if self._error:
            self.stop()
        return self._error

    def _run(self, flags: int, vk: int) -> None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.argtypes = user32.GetMessageW.argtypes + [wintypes.UINT]
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)        # creates this thread's message queue
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, flags | MOD_NOREPEAT, vk):
            code = ctypes.get_last_error()
            self._error = (
                f"{self.text} is already used by another app. Choose a different shortcut."
                if code == ERROR_HOTKEY_ALREADY_REGISTERED else
                f"The shortcut {self.text} could not be registered (Windows error {code})."
            )
            self._ready.set()
            return
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        if self._thread_id and sys.platform == "win32":
            import ctypes
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(2)
