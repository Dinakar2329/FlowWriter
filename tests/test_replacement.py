import time
from flowwriter.domain import SelectionContext
from flowwriter.selection import SelectionBridge

class NativeStub:
    def __init__(self, source):
        self.source = source
        self.active = "dashboard"
        self.restore_calls = 0
    def restore(self, handle):
        self.restore_calls += 1
        if handle != self.source:
            return False
        self.active = self.source
        return True
    def current_id(self):
        return self.active

class ClipboardStub:
    def __init__(self, text):
        self.selected = text
        self.pasted = []
    def capture(self, guard=None):
        return self.selected
    def paste(self, text, guard=None):
        if guard and not guard():
            return False
        self.pasted.append(text)
        return True


def bridge(native, clipboard):
    obj = SelectionBridge.__new__(SelectionBridge)
    obj.native = native
    obj.clipboard = clipboard
    return obj


def test_no_paste_if_target_missing_or_changed():
    native = NativeStub("source-window")
    cb = ClipboardStub("original")
    ctx = SelectionContext("original", "source-window", "Editor", time.monotonic())
    assert bridge(native, cb).replace(ctx, "changed")
    assert cb.pasted == ["changed"]
    cb.pasted.clear()
    cb.selected = "new unrelated selection"
    assert not bridge(native, cb).replace(ctx, "changed")
    assert cb.pasted == []
    bad = SelectionContext("original", None, "Editor", time.monotonic())
    assert not bridge(native, cb).replace(bad, "changed")


def test_never_blind_paste_to_different_handle():
    native = NativeStub("other-window")
    cb = ClipboardStub("original")
    ctx = SelectionContext("original", "source-window", "Editor", time.monotonic())
    assert not bridge(native, cb).replace(ctx, "danger")
    assert cb.pasted == []


def test_stale_session_cannot_replace():
    native = NativeStub("source-window")
    cb = ClipboardStub("original")
    ctx = SelectionContext("original", "source-window", "Editor", time.monotonic() - 601)
    assert not bridge(native, cb).replace(ctx, "different")
    assert cb.pasted == []


def test_focus_change_during_recapture_never_pastes():
    native = NativeStub("source-window")
    clipboard = ClipboardStub("original")
    def capture(guard=None):
        native.active = "different-window"
        return "original"
    clipboard.capture = capture
    context = SelectionContext("original", "source-window", "Editor", time.monotonic())
    assert not bridge(native, clipboard).replace(context, "replacement")
    assert clipboard.pasted == []


def test_transient_clipboard_failure_can_retry_but_selection_mismatch_cannot():
    from flowwriter.selection import ClipboardError
    native = NativeStub("source-window")
    clipboard = ClipboardStub("original")
    context = SelectionContext("original", "source-window", "Editor", time.monotonic())
    adapter = bridge(native, clipboard)
    def busy(guard=None):
        raise ClipboardError("Clipboard is busy")
    clipboard.capture = busy
    assert not adapter.replace(context, "replacement")
    assert adapter.can_retry
    assert "busy" in adapter.last_failure
    clipboard.capture = lambda guard=None: "changed selection"
    assert not adapter.replace(context, "replacement")
    assert not adapter.can_retry
    assert clipboard.pasted == []


def test_editor_that_ignores_the_first_copy_is_given_a_second_chance():
    """Excel's cell editor (F2) can ignore a Ctrl+C sent the instant it regains focus."""
    native = NativeStub("source-window")
    clipboard = ClipboardStub("original")
    answers = iter(["", "original"])          # first copy ignored, second works
    clipboard.capture = lambda guard=None: next(answers)
    context = SelectionContext("original", "source-window", "Excel", time.monotonic())
    adapter = bridge(native, clipboard)
    adapter.SETTLE_SECONDS = 0.01
    assert adapter.replace(context, "replacement")
    assert clipboard.pasted == ["replacement"]


def test_lost_selection_explains_itself_and_can_be_retried_but_never_pastes():
    native = NativeStub("source-window")
    clipboard = ClipboardStub("original")
    clipboard.capture = lambda guard=None: ""
    context = SelectionContext("original", "source-window", "Excel", time.monotonic())
    adapter = bridge(native, clipboard)
    adapter.SETTLE_SECONDS = 0.01
    assert not adapter.replace(context, "replacement")
    assert adapter.can_retry and "Nothing is selected" in adapter.last_failure
    assert clipboard.pasted == []
    clipboard.capture = lambda guard=None: "original"          # the user selects it again and retries
    assert adapter.replace(context, "replacement")
    assert clipboard.pasted == ["replacement"]
