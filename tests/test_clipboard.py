"""Clipboard contention and race checks without touching the system clipboard."""
from types import SimpleNamespace

import pytest
pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import QMimeData

from flowwriter.selection import ClipboardBridge, ClipboardError


class MemoryClipboard:
    def __init__(self):
        self.version = 0
        self.reads = 0
        self.value = QMimeData()
        self.value.setText("Original clipboard")
        self.value.setHtml("<b>Original clipboard</b>")

    def mimeData(self):
        return self.value

    def text(self):
        self.reads += 1
        return self.value.text()

    def setText(self, text):
        mime = QMimeData()
        mime.setText(text)
        self.setMimeData(mime)

    def setMimeData(self, mime):
        self.version += 1
        self.value = mime

    def clear(self):
        self.setMimeData(QMimeData())


@pytest.fixture
def clipboard_bridge(monkeypatch):
    import flowwriter.selection as selection
    clock = [0.0]
    monkeypatch.setattr(selection.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(selection.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    clipboard = MemoryClipboard()
    bridge = ClipboardBridge.__new__(ClipboardBridge)
    bridge.app = SimpleNamespace(clipboard=lambda: clipboard)
    bridge.native = SimpleNamespace(
        clipboard_sequence=lambda: clipboard.version,
        clipboard_available=lambda: True,
        modifiers_down=lambda: False,
    )
    bridge._revision, bridge._busy = 0, False
    bridge._pump = lambda: None
    bridge._tap = lambda key: None
    return bridge, clipboard


def test_capture_waits_for_copy_and_restores_rich_clipboard(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    bridge._tap = lambda key: clipboard.setText("Selected words")
    assert bridge.capture(guard=lambda: True) == "Selected words"
    assert clipboard.text() == "Original clipboard"
    assert clipboard.mimeData().html() == "<b>Original clipboard</b>"


def test_no_copy_response_does_not_repeatedly_materialize_clipboard(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    assert bridge.capture() == ""
    assert clipboard.text() == "Original clipboard"
    assert clipboard.reads <= 3


def test_busy_clipboard_and_held_modifiers_do_not_send_keys(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    keys = []
    bridge._tap = keys.append
    bridge.native.clipboard_available = lambda: False
    with pytest.raises(ClipboardError, match="busy"):
        bridge.capture()
    assert keys == []
    assert clipboard.version == 0
    bridge.native.clipboard_available = lambda: True
    bridge.native.modifiers_down = lambda: True
    with pytest.raises(ClipboardError, match="Release"):
        bridge.paste("Replacement")
    assert keys == []
    assert clipboard.version == 0


def test_waits_for_transient_contention_and_modifier_release(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    modifiers, availability = iter((True, True, False)), iter((False, False, True, True))
    bridge.native.modifiers_down = lambda: next(modifiers, False)
    bridge.native.clipboard_available = lambda: next(availability, True)
    bridge._tap = lambda key: clipboard.setText("Verified selection")
    assert bridge.capture() == "Verified selection"


def test_delayed_paste_restore_does_not_overwrite_a_later_identical_copy(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    restoration = []
    keys = []
    bridge._tap = keys.append
    bridge._schedule_restore = lambda *args: restoration.append(args)
    assert bridge.paste("Replacement", guard=lambda: True)
    assert keys == ["v"]
    assert clipboard.text() == "Replacement"
    clipboard.setText("Replacement")  # Same text, but the user's newer clipboard operation.
    bridge._restore(*restoration[0])
    assert clipboard.text() == "Replacement"


def test_paste_revalidates_target_after_publishing_clipboard(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    keys = []
    bridge._tap = keys.append
    active = [True]
    bridge._pump = lambda: active.__setitem__(0, False)
    assert not bridge.paste("Replacement", guard=lambda: active[0])
    assert keys == []
    assert clipboard.text() == "Original clipboard"


def test_capture_reentrancy_does_not_overwrite_the_active_transaction(clipboard_bridge):
    bridge, clipboard = clipboard_bridge
    bridge._busy = True
    with pytest.raises(ClipboardError, match="already in progress"):
        bridge.capture()
    assert clipboard.version == 0
