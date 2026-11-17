"""Selection capture and conservative, verified replacement on supported OSes."""
from __future__ import annotations
import ctypes
import os
import sys
import time
from typing import Callable
from dataclasses import dataclass
from .domain import SelectionContext

# Qt and pynput are imported only when the desktop app starts, not for storage tests.


class ClipboardError(RuntimeError):
    """A transient clipboard or modifier condition prevented safe interaction."""


class ClipboardBridge:
    def __init__(self, app) -> None:
        from pynput import keyboard
        self.app = app
        self.keyboard = keyboard.Controller()
        self.native = NativeTarget()
        self._revision = 0
        self._busy = False
        app.clipboard().dataChanged.connect(self._changed)

    def _changed(self):
        self._revision += 1

    def _sequence(self):
        return self.native.clipboard_sequence(), self._revision

    @staticmethod
    def _pump():
        from PySide6.QtCore import QCoreApplication, QEventLoop
        # Service clipboard/OLE events without dispatching another approval click.
        QCoreApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _ready(self, timeout=.3):
        deadline = time.monotonic() + timeout
        while not self.native.clipboard_available():
            if time.monotonic() >= deadline:
                return False
            time.sleep(.015)
            self._pump()
        return True

    def _wait_modifiers(self):
        deadline = time.monotonic() + .8
        while self.native.modifiers_down():
            if time.monotonic() >= deadline:
                raise ClipboardError("Release Ctrl, Alt, Shift and Windows keys, then try again.")
            time.sleep(.015)
            self._pump()

    def _snapshot(self):
        """Preserve available MIME formats only after clipboard contention clears."""
        if not self._ready():
            raise ClipboardError("The clipboard is busy. Wait a moment and try again.")
        mime = self.app.clipboard().mimeData()
        data, total = {}, 0
        if mime:
            for fmt in mime.formats():
                raw = mime.data(fmt)
                total += raw.size()
                if total > 16 * 1024 * 1024:
                    raise ClipboardError("The clipboard is too large to preserve safely. Use Copy result.")
                data[fmt] = bytes(raw)
        return data

    def _restore(self, data, expected, sequence):
        from PySide6.QtCore import QMimeData
        if not self._ready(.1) or self._sequence() != sequence:
            return
        clipboard = self.app.clipboard()
        if clipboard.text() != expected:
            return
        if not data:
            clipboard.clear()
            return
        mime = QMimeData()
        for fmt, value in data.items():
            mime.setData(fmt, value)
        clipboard.setMimeData(mime)

    def _tap(self, key):
        from pynput import keyboard
        modifier = keyboard.Key.cmd if sys.platform == "darwin" else keyboard.Key.ctrl
        with self.keyboard.pressed(modifier):
            self.keyboard.tap(key)

    def capture(self, guard=None) -> str:
        if self._busy:
            raise ClipboardError("A clipboard operation is already in progress.")
        self._busy = True
        try:
            self._wait_modifiers()
            backup = self._snapshot()
            if guard and not guard():
                return ""
            marker = "FLOWWRITER-CAPTURE-" + str(time.monotonic_ns())
            clipboard = self.app.clipboard()
            clipboard.setText(marker)
            sequence = self._sequence()
            expected, result = marker, ""
            try:
                if guard and not guard():
                    return ""
                self._tap("c")
                deadline = time.monotonic() + .8
                while time.monotonic() < deadline:
                    time.sleep(.02)
                    self._pump()
                    # Avoid repeatedly asking Qt/OLE to materialize unchanged MIME data.
                    if self._sequence() == sequence or not self._ready(.05):
                        continue
                    value = clipboard.text()
                    if value != marker:
                        expected, result = value, value
                        sequence = self._sequence()
                        break
                return result if not guard or guard() else ""
            finally:
                self._restore(backup, expected, sequence)
        finally:
            self._busy = False

    def _schedule_restore(self, backup, text, sequence):
        from PySide6.QtCore import QTimer
        timer = QTimer(self.app)
        timer.setSingleShot(True)
        def restore():
            self._restore(backup, text, sequence)
            timer.deleteLater()
        timer.timeout.connect(restore)
        timer.start(1200)

    def paste(self, text, guard=None) -> bool:
        self._wait_modifiers()
        backup = self._snapshot()
        if guard and not guard():
            return False
        clipboard = self.app.clipboard()
        clipboard.setText(text)
        self._pump()
        sequence = self._sequence()
        if not self._ready() or clipboard.text() != text or (guard and not guard()):
            self._restore(backup, text, sequence)
            return False
        try:
            self._tap("v")
        except Exception:
            self._restore(backup, text, sequence)
            raise
        # Foreign editors may read asynchronously. Never restore after a later copy,
        # even if its text happens to equal our result.
        self._schedule_restore(backup, text, sequence)
        return True


class NativeTarget:
    """Only Windows has a validated focus-restore adapter in this release.

    macOS and Linux have working selection/copy but intentionally do not use
    unsafe blind paste after a popup steals focus.
    """
    def current_id(self) -> str | None:
        if sys.platform != "win32":
            return None
        from .windows import user32
        hwnd = user32().GetForegroundWindow()
        return str(hwnd) if hwnd else None

    def restore(self, target_id: str | None) -> bool:
        if not target_id or sys.platform != "win32":
            return False
        try:
            from .windows import user32
            api, hwnd = user32(), int(target_id)
            if not api.IsWindow(hwnd):
                return False
            if api.IsIconic(hwnd):
                api.ShowWindow(hwnd, 9)  # SW_RESTORE
            api.SetForegroundWindow(hwnd)
            deadline = time.monotonic() + .45
            while time.monotonic() < deadline:
                if self.current_id() == target_id:
                    return True
                time.sleep(.015)
            return False
        except (ValueError, OSError):
            return False

    def source_name(self) -> str:
        if sys.platform != "win32":
            return "Desktop application"
        try:
            from .windows import user32
            api = user32()
            hwnd = api.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            api.GetWindowTextW(hwnd, buf, len(buf))
            return buf.value[:150] or "Desktop application"
        except OSError:
            return "Desktop application"

    # Windows where a synthetic Ctrl+C is unsafe or meaningless: in a console it is an
    # interrupt, in a file manager it copies files, on the desktop it copies icons.
    SPECIAL_CLASSES = frozenset({
        "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "PuTTY", "VirtualConsoleClass",
        "org.wezfurlong.wezterm", "Alacritty", "CabinetWClass", "Progman", "WorkerW", "Shell_TrayWnd",
    })

    def window_class(self) -> str:
        if sys.platform != "win32":
            return ""
        try:
            from .windows import user32
            api = user32()
            buf = ctypes.create_unicode_buffer(256)
            api.GetClassNameW(api.GetForegroundWindow(), buf, len(buf))
            return buf.value
        except OSError:
            return ""

    def is_special_window(self) -> bool:
        return self.window_class() in self.SPECIAL_CLASSES

    def modifiers_down(self):
        if sys.platform != "win32":
            return False
        from .windows import user32
        return any(user32().GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C))

    def clipboard_available(self):
        if sys.platform != "win32":
            return True
        from .windows import user32
        api = user32()
        if not api.OpenClipboard(None):
            return False
        api.CloseClipboard()
        return True

    def clipboard_sequence(self):
        if sys.platform != "win32":
            return 0
        from .windows import user32
        return user32().GetClipboardSequenceNumber()


class SelectionBridge:
    SETTLE_SECONDS = 0.15

    def __init__(self, qt_app):
        self.native = NativeTarget()
        self.clipboard = ClipboardBridge(qt_app)

    def capture(self) -> SelectionContext | None:
        current = self.native.current_id()
        name = self.native.source_name()
        guard = (lambda: self.native.current_id() == current) if current else None
        text = self.clipboard.capture(guard=guard)
        if not text or not text.strip() or (guard and not guard()):
            return None
        return SelectionContext(text=text, target_id=current, app_name=name, captured_at=time.monotonic())

    def replace(self, ctx: SelectionContext, replacement: str) -> bool:
        """Restore and recapture exact original selection; never paste blindly.

        A true atomic operation is impossible with most foreign editors. Failure
        returns False so the UI can offer Copy. Never paste to an unknown target.
        """
        self.last_failure = ""
        self.can_retry = False
        if not replacement or not replacement.strip():
            self.last_failure = "The replacement text is empty."
            return False
        if time.monotonic() - ctx.captured_at > 600:
            self.last_failure = "This selection has expired. Select the original text again."
            return False
        if not self.native.restore(ctx.target_id):
            self.last_failure = "The original editor could not be focused. Open it and try again."
            self.can_retry = True
            return False
        guard = lambda: self.native.current_id() == ctx.target_id
        if not guard():
            self.last_failure = "The active window changed. Try again in the original editor."
            self.can_retry = True
            return False
        try:
            # Editors such as Excel's cell editor (F2) need a moment after they regain focus
            # before they accept keys, and an early Ctrl+C is silently ignored.
            time.sleep(self.SETTLE_SECONDS)
            reselected = self.clipboard.capture(guard=guard)
            if not reselected and guard():
                time.sleep(self.SETTLE_SECONDS * 2)
                reselected = self.clipboard.capture(guard=guard)
            if not reselected:
                self.last_failure = ("Nothing is selected in the original app any more. Select the same text again "
                                     "there, then press Try replace again, or use Copy result.")
                self.can_retry = True
                return False
            if reselected != ctx.text:
                self.last_failure = "The original selection could not be verified. Select the text again or use Copy result."
                return False
            if not guard():
                self.last_failure = "The active window changed before replacement."
                self.can_retry = True
                return False
            if not self.clipboard.paste(replacement, guard=guard):
                self.last_failure = "The clipboard or target changed before paste. Try again."
                self.can_retry = True
                return False
            return True
        except ClipboardError as exc:
            self.last_failure = str(exc)
            self.can_retry = True
            return False
