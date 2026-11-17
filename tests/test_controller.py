"""Request lifecycle: stream, cancel, stale results, replace, retry, shortcuts, shutdown."""
from __future__ import annotations
import os
import threading
import time

import pytest

from flowwriter.provider import ProviderError, RequestCancelled


class FakeKeychain:
    def get_password(self, *a):
        return ""

    def set_password(self, *a):
        return None


class FakeClient:
    """Stands in for the model. `script` runs on the worker thread like the real client."""

    def __init__(self):
        self.script = lambda on_delta, on_thinking, cancel: "Result text"
        self.calls = []

    def generate(self, profile, key, instruction, text, on_delta=None, cancel=None, on_thinking=None):
        self.calls.append({"instruction": instruction, "text": text, "key": key, "profile": profile})
        return self.script(on_delta, on_thinking, cancel)

    def test_connection(self, profile, key):
        return "Connected."


class FakeNative:
    def __init__(self):
        self.special = False
        self.title = "Notepad"

    def is_special_window(self):
        return self.special

    def source_name(self):
        return self.title


class FakeSelection:
    def __init__(self):
        self.native = FakeNative()
        self.replaced = []
        self.ok = True
        self.last_failure = "Original editor could not be focused."
        self.can_retry = True

    def capture(self):
        return None

    def replace(self, ctx, text):
        self.replaced.append((ctx.text, text))
        return self.ok


class FakeHotkey:
    """Stands in for the Windows shortcut registry so tests never grab a real key."""
    error = ""            # set to a message to imitate "another app already uses it"
    registered: list = []

    def __init__(self, text, callback):
        self.text, self.callback = text, callback

    def start(self):
        if FakeHotkey.error:
            return FakeHotkey.error
        FakeHotkey.registered.append(self.text)
        return ""

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def fake_hotkeys(monkeypatch):
    from flowwriter.controller import Controller
    FakeHotkey.error, FakeHotkey.registered = "", []
    monkeypatch.setattr(Controller, "_make_hotkey", staticmethod(FakeHotkey))   # same on every OS
    return FakeHotkey


@pytest.fixture
def parts(tmp_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from cryptography.fernet import Fernet
    from PySide6.QtWidgets import QApplication
    from flowwriter.controller import Controller
    from flowwriter.domain import SelectionContext
    from flowwriter.storage import Store
    from flowwriter.vault import SecretVault

    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "c.db", Fernet(Fernet.generate_key()))
    client, selection = FakeClient(), FakeSelection()
    controller = Controller(app, store, SecretVault(FakeKeychain()), client=client, selection=selection, start_hooks=False)
    controller.context = SelectionContext("original words", "1", "Notepad", time.monotonic())
    yield controller, client, selection, store
    controller.shutdown()
    controller.dashboard.deleteLater()


def wait_until(condition, timeout=3.0):
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert condition(), "condition not met in time"


def statuses(store):
    return [r["status"] for r in store.recent()]


def test_selection_request_streams_then_shows_a_result_to_review(parts):
    controller, client, _selection, store = parts

    def script(on_delta, on_thinking, cancel):
        on_thinking()
        time.sleep(0.05)
        on_delta("Result")
        time.sleep(0.06)
        on_delta("Result text")
        time.sleep(0.05)
        return "Result text"

    client.script = script
    controller._run_from_selection("Polish", "Make it better.")
    wait_until(lambda: controller.card._state == "streaming")
    assert controller.card.preview_box.toPlainText().startswith("Result")
    assert controller.card.preview_box.isReadOnly()              # cannot be edited while it is written
    assert not controller.card.primary_btn.isVisible()           # and cannot be replaced yet
    wait_until(lambda: controller.card._state == "result")
    assert controller.card.preview_box.toPlainText() == "Result text"
    assert not controller.card.preview_box.isReadOnly()
    assert controller.card.primary_btn.isEnabled()
    assert statuses(store) == ["generated"]
    assert client.calls[0]["text"] == "original words"


def test_card_says_thinking_before_the_first_word(parts):
    controller, client, *_ = parts
    release = threading.Event()

    def script(on_delta, on_thinking, cancel):
        on_thinking()
        release.wait(3)
        return "Done"

    client.script = script
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card.status_label.text().startswith("Thinking"))
    release.set()
    wait_until(lambda: controller.card._state == "result")


def test_scratchpad_request_streams_into_the_result_box_and_refreshes_once(parts, monkeypatch):
    controller, client, _selection, store = parts
    refreshes = []
    real = controller.dashboard.refresh
    monkeypatch.setattr(controller.dashboard, "refresh", lambda: refreshes.append(1) or real())

    def script(on_delta, on_thinking, cancel):
        on_delta("Half")
        time.sleep(0.08)
        return "Half done"

    client.script = script
    controller._run_from_scratchpad("some text", "Polish", "Polish it.")
    wait_until(lambda: controller.dashboard.scratch_result.toPlainText() == "Half")
    assert controller.dashboard.scratch_state.text() == "Writing…"
    wait_until(lambda: controller.dashboard.scratch_state.text() == "Done")
    assert controller.dashboard.scratch_result.toPlainText() == "Half done"
    assert len(refreshes) == 1                                   # was twice before: a 0.4 s freeze each
    assert statuses(store) == ["generated"]


def test_cancel_marks_history_and_ignores_the_late_result(parts):
    controller, client, _selection, store = parts
    release = threading.Event()
    seen = {}

    def script(on_delta, on_thinking, cancel):
        release.wait(3)
        seen["cancelled"] = cancel.is_set()
        return "Too late"

    client.script = script
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.inflight)
    controller.card.cancelled.emit()                              # Esc / Cancel on the card
    release.set()
    wait_until(lambda: "cancelled" in seen)
    from PySide6.QtWidgets import QApplication
    for _ in range(10):
        QApplication.processEvents()
        time.sleep(0.01)
    assert seen["cancelled"] is True                              # the worker was told to stop
    assert statuses(store) == ["cancelled"]                       # and no "generated" row appeared
    assert controller.card._state != "result"


def test_a_newer_request_wins_over_a_stale_one(parts):
    controller, client, *_ = parts
    gates = [threading.Event(), threading.Event()]
    order = iter(range(2))

    def script(on_delta, on_thinking, cancel):
        mine = next(order)
        gates[mine].wait(3)
        return f"answer {mine}"

    client.script = script
    controller._run_from_selection("A", "first")
    wait_until(lambda: len(client.calls) == 1)
    controller._run_from_selection("B", "second")
    wait_until(lambda: len(client.calls) == 2)
    gates[1].set()
    wait_until(lambda: controller.card.preview_box.toPlainText() == "answer 1")
    gates[0].set()                                                # the first one finishes last
    time.sleep(0.1)
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert controller.card.preview_box.toPlainText() == "answer 1"


def test_failure_shows_the_message_logs_it_and_retry_runs_again(parts):
    controller, client, _selection, store = parts
    attempts = []

    def script(on_delta, on_thinking, cancel):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError("Could not connect to the configured API endpoint.", "connection")
        return "Second try works"

    client.script = script
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card._state == "error")
    assert "Could not connect" in controller.card.error_label.text()
    assert statuses(store) == ["failed"] and store.recent()[0]["error_type"] == "connection"
    controller.card.retry_requested.emit()
    wait_until(lambda: controller.card._state == "result")
    assert controller.card.preview_box.toPlainText() == "Second try works"
    assert len(attempts) == 2


def test_unexpected_errors_do_not_leak_details(parts):
    controller, client, *_ = parts

    def script(on_delta, on_thinking, cancel):
        raise RuntimeError("SECRET-DETAIL")

    client.script = script
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card._state == "error")
    assert "SECRET-DETAIL" not in controller.card.error_label.text()


def test_replace_success_and_failure_paths(parts):
    controller, client, selection, store = parts
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card._state == "result")
    selection.ok = False
    controller.card.approved.emit("Edited by me")
    assert selection.replaced == [("original words", "Edited by me")]
    assert controller.card.error_label.text() == selection.last_failure     # told why, with retry
    assert controller.card.primary_btn.isEnabled() and statuses(store) == ["generated"]
    selection.ok = True
    controller.card.approved.emit("Edited by me")
    assert statuses(store) == ["replaced"]
    assert store.recent()[0]["output_text"] == "Edited by me"


def test_discard_and_copy_update_history(parts):
    controller, *_rest, store = parts
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card._state == "result")
    controller.card.copied.emit("Copied text")
    assert statuses(store) == ["copied"]
    controller._run_from_selection("Polish", "Go.")
    wait_until(lambda: controller.card._state == "result")
    controller.card.cancelled.emit()
    assert statuses(store) == ["rejected", "copied"]


def test_the_env_key_only_goes_to_local_or_pinned_providers():
    from flowwriter.controller import api_key_for
    from flowwriter.domain import Provider
    from flowwriter.vault import SecretVault

    vault = SecretVault(FakeKeychain())
    local = Provider("a", "Ollama", "http://localhost:11434/v1", "m")
    remote = Provider("b", "Other", "https://api.thirdparty.example/v1", "m")
    env = {"FLOWWRITER_API_KEY": "sk-env"}
    assert api_key_for(local, vault, env) == "sk-env"
    assert api_key_for(remote, vault, env) == ""                  # not sent to a provider added later
    pinned = {**env, "FLOWWRITER_API_KEY_URL": "https://api.thirdparty.example/v1/"}
    assert api_key_for(remote, vault, pinned) == "sk-env"
    assert api_key_for(local, vault, pinned) == ""
    vault.put("provider-b", "saved-key")
    assert api_key_for(remote, vault, env) == "saved-key"          # a saved key always wins


def test_special_windows_and_excluded_titles_skip_capture(parts):
    controller, _client, selection, store = parts
    captured = []
    selection.capture = lambda: captured.append(1)
    controller.dashboard.hide()
    selection.native.special = True
    controller._on_selection_trigger()
    assert not captured                                           # terminals are left alone by default
    selection.native.special = False
    selection.native.title = "KeePass - Vault"
    controller._on_selection_trigger()
    assert not captured                                           # password managers excluded by default
    selection.native.title = "Notes"
    controller._on_selection_trigger()
    assert captured
    captured.clear()
    selection.native.special = True
    store.set_pref("skip_special_windows", "false")
    controller.apply_shortcuts()
    controller._on_selection_trigger()
    assert captured                                               # the user can allow terminals


def test_changing_shortcuts_applies_without_restart(parts):
    controller, *_rest, store = parts
    from flowwriter import shortcuts
    assert controller.shortcuts == shortcuts.Shortcuts()
    controller.dashboard.navigate(7)
    controller.dashboard.drag_choice.setCurrentIndex(controller.dashboard.drag_choice.findData("alt"))
    from PySide6.QtGui import QKeySequence
    controller.dashboard.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+K"))
    controller.dashboard.save_shortcuts()
    assert controller.shortcuts.drag == frozenset({"alt"})
    assert controller.shortcuts.hotkey == "Ctrl+Shift+K"
    assert "Alt" in controller.dashboard.shortcut_hint.text()
    assert shortcuts.load(store) == controller.shortcuts


def test_shutdown_is_safe_to_repeat(parts):
    controller, *_ = parts
    controller.shutdown()
    controller.shutdown()
    assert controller._closed


def test_end_to_end_stream_is_visible_on_the_card_while_the_server_is_still_writing(tmp_path):
    """Real client + real HTTP + real card: the text grows on screen before the reply is finished."""
    from test_streaming import Handler, Script, event
    from http.server import ThreadingHTTPServer
    from cryptography.fernet import Fernet
    from PySide6.QtWidgets import QApplication
    from flowwriter.controller import Controller
    from flowwriter.domain import Provider, SelectionContext
    from flowwriter.storage import Store
    from flowwriter.vault import SecretVault

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    words = [f"word{i} " for i in range(12)]
    Script.steps = [(0.12, event({"content": "", "reasoning": "thinking"}))] + \
                   [(0.1, event({"content": w})) for w in words] + [(0, "data: [DONE]\n\n")]
    Script.content_type, Script.seen_bodies = "text/event-stream", []
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "e.db", Fernet(Fernet.generate_key()))
    store.save_profile(Provider("local-default", "Local", f"http://127.0.0.1:{srv.server_address[1]}/v1", "any", True))
    controller = Controller(app, store, SecretVault(FakeKeychain()), selection=FakeSelection(), start_hooks=False)
    controller.context = SelectionContext("hello", "1", "Notepad", time.monotonic())
    try:
        controller._run_from_selection("Polish", "Go.")
        lengths, states = [], set()
        end = time.monotonic() + 8
        while controller.card._state != "result" and time.monotonic() < end:
            app.processEvents()
            states.add(controller.card._state)
            if controller.card._state == "streaming":
                lengths.append(len(controller.card.preview_box.toPlainText()))
            time.sleep(0.02)
        assert controller.card._state == "result"
        assert "streaming" in states
        assert len(set(lengths)) >= 4 and lengths == sorted(lengths)      # it grew, word by word
        assert lengths[0] < len("".join(words)) / 2                         # and was far from complete at first sight
        assert controller.card.preview_box.toPlainText() == "".join(words).strip()
    finally:
        controller.shutdown()
        controller.dashboard.deleteLater()
        srv.shutdown()
        srv.server_close()


def test_a_shortcut_another_app_already_owns_is_explained_and_not_advertised(parts, fake_hotkeys):
    controller, *_rest, store = parts
    clash = "Ctrl+Alt+Space is already used by another app. Choose a different shortcut."
    fake_hotkeys.error = clash
    controller.apply_shortcuts()
    dash = controller.dashboard
    assert dash.shortcut_status.text() == clash
    assert "not active" in dash.shortcut_hint.text()
    dash.navigate(7)                                   # opening the page must not wipe the explanation
    assert dash.shortcut_status.text() == clash
    assert "not active" in dash.shortcut_hint.text()
    # choosing a free key clears the warning and registers the new key
    fake_hotkeys.error = ""
    from PySide6.QtGui import QKeySequence
    dash.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+K"))
    dash.save_shortcuts()
    assert fake_hotkeys.registered[-1] == "Ctrl+Shift+K"
    assert "already used" not in dash.shortcut_status.text()
    assert "Ctrl+Shift+K" in dash.shortcut_hint.text()


def test_shortcut_edits_are_saved_without_pressing_save(parts):
    controller, *_rest, store = parts
    from flowwriter import shortcuts
    dash = controller.dashboard
    dash.navigate(7)
    dash.drag_choice.setCurrentIndex(dash.drag_choice.findData("alt"))      # a user change: saved at once
    assert shortcuts.load(store).drag == frozenset({"alt"})
    dash.skip_special.setChecked(False)
    assert shortcuts.load(store).skip_special_windows is False
    dash.navigate(7)                                                        # filling the form saves nothing new
    assert shortcuts.load(store).drag == frozenset({"alt"})
