"""Coordinates the radial menu, model workers, dashboard, and history."""
from __future__ import annotations
import os
import sys
import threading
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal, QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PySide6.QtGui import QAction
from . import shortcuts
from .domain import SelectionContext, Provider, DEFAULT_EXCLUDED_TITLES, normalized_base_url
from .provider import ChatClient, ProviderError, RequestCancelled, MAX_INPUT_CHARS
from .selection import SelectionBridge
from .radial import RadialMenuWindow
from .overlay import PreviewPopupCard
from .dashboard import MainWindow
from .icons import app_icon

_AUTO = object()


class WorkerEvents(QObject):
    progress = Signal(int, str)
    thinking = Signal(int)
    succeeded = Signal(int, str, int)
    failed = Signal(int, str, str)
    tested = Signal(str, bool)


def api_key_for(profile: Provider, vault, environ=os.environ) -> str:
    """The key saved for this provider, or the environment fallback where that is safe.

    FLOWWRITER_API_KEY is meant for one endpoint. It is sent only to a local server,
    or to the exact URL named in FLOWWRITER_API_KEY_URL, never to any other
    provider the user happens to add.
    """
    saved = vault.get("provider-" + profile.id)
    if saved:
        return saved
    fallback = environ.get("FLOWWRITER_API_KEY", "")
    if not fallback:
        return ""
    try:
        base = normalized_base_url(profile.base_url)
        pinned = environ.get("FLOWWRITER_API_KEY_URL", "").strip()
        if pinned:
            return fallback if normalized_base_url(pinned) == base else ""
        host = (urlsplit(base).hostname or "").lower()
        return fallback if host in ("localhost", "127.0.0.1", "::1") else ""
    except ValueError:
        return ""


class PynputHotkey:
    """Global key through pynput, for macOS and Linux. start() returns '' or an error message."""

    def __init__(self, text: str, callback):
        self.text, self.callback, self._listener = text, callback, None

    def start(self) -> str:
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys({shortcuts.hotkey_to_pynput(self.text): self.callback})
            self._listener.start()
            return ""
        except Exception as exc:
            self._listener = None
            return f"The shortcut {self.text} could not be registered ({type(exc).__name__})."

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass


class Controller(QObject):
    show_wheel = Signal()
    escape_pressed = Signal()

    def __init__(self, app: QApplication, store, vault, *, client=None, selection=_AUTO, start_hooks=True):
        super().__init__()
        self.app, self.store, self.vault = app, store, vault
        self.client = client or ChatClient()
        self.dashboard = MainWindow(store, vault)
        self.radial = RadialMenuWindow()
        self.radial.set_actions(store.actions())
        self.card = PreviewPopupCard()
        self.context: SelectionContext | None = None
        self.last_anchor = QPoint(400, 300)
        self.pending_action: tuple[str, str] | None = None
        self.pending_mode = "selection"
        self.pending_text = ""
        self.pending_start = 0.0
        self.pending_profile: Provider | None = None
        self.pending_source_name = ""
        self.inflight = False
        self.pending_history_id: int | None = None
        self.pending_output = ""
        self.request_id = 0
        self.cancel_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self._closed = False
        self.selection_error = ""
        self.shortcuts = shortcuts.load(store)
        self._held: set[str] = set()
        self._drag_start = None
        self._listen_keys = None
        self._listen_mouse = None
        self._hotkeys = None
        self.hotkey_error = ""
        if selection is _AUTO:
            try:
                self.selection = SelectionBridge(app)
            except Exception as exc:
                self.selection = None
                self.selection_error = f"Global selection integration unavailable: {type(exc).__name__}"
        else:
            self.selection = selection
        self.worker_events = WorkerEvents()
        self.worker_events.progress.connect(self._on_progress)
        self.worker_events.thinking.connect(self._on_thinking)
        self.worker_events.succeeded.connect(self._on_success)
        self.worker_events.failed.connect(self._on_failure)
        self.worker_events.tested.connect(self.dashboard.test_finished)
        self.show_wheel.connect(self._on_selection_trigger)
        self.escape_pressed.connect(self.radial.hide)
        self.radial.action_selected.connect(self._run_from_selection)
        self.radial.custom_prompt_requested.connect(self._open_custom)
        self.card.custom_submitted.connect(lambda prompt: self._run_from_selection("Custom", prompt))
        self.card.approved.connect(self._attempt_replace)
        self.card.copied.connect(self._copy_result)
        self.card.cancelled.connect(self._reject)
        self.card.retry_requested.connect(self._retry)
        self.dashboard.scratchpad_requested.connect(self._run_from_scratchpad)
        self.dashboard.action_changed.connect(lambda: self.radial.set_actions(self.store.actions()))
        self.dashboard.scratch_copied.connect(self._scratch_copied)
        self.dashboard.provider_test_requested.connect(self._test_provider)
        self.dashboard.shortcuts_changed.connect(self.apply_shortcuts)
        self.tray = self._make_tray()
        if start_hooks:
            self._start_hooks()
        # Also runs when Windows is shutting down or signing out.
        app.aboutToQuit.connect(self.shutdown)
        self.dashboard.show()
        if self.selection_error:
            self.dashboard.statusBar().showMessage(self.selection_error)
        if self.hotkey_error:   # e.g. another app already uses the saved shortcut
            self.dashboard.show_shortcut_status(self.hotkey_error, False)
            self.dashboard.navigate(7)

    def _make_tray(self):
        tray = QSystemTrayIcon(app_icon(), self.app)
        menu = QMenu()
        show = QAction("Open FlowWriter Studio", menu)
        show.triggered.connect(self.open_dashboard)
        menu.addAction(show)
        new = QAction("Open Scratchpad", menu)
        new.triggered.connect(lambda: self.open_dashboard(2))
        menu.addAction(new)
        private = QAction("Toggle private mode", menu)
        private.triggered.connect(self.dashboard.toggle_private)
        menu.addAction(private)
        menu.addSeparator()
        quit_action = QAction("Quit FlowWriter Studio", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.open_dashboard() if reason == QSystemTrayIcon.DoubleClick else None)
        tray.setToolTip("FlowWriter Studio")
        tray.show()
        self._tray_menu = menu
        return tray

    def open_dashboard(self, page: int = 0):
        self.dashboard.navigate(page)
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    # -- global input ------------------------------------------------------------------
    def _start_hooks(self):
        if self.selection is None:
            return
        try:
            from pynput import keyboard, mouse

            def on_press(key):
                name = shortcuts.modifier_name(getattr(key, "name", ""))
                if name:
                    self._held.add(name)
                if key == keyboard.Key.esc:
                    self.escape_pressed.emit()

            def on_release(key):
                name = shortcuts.modifier_name(getattr(key, "name", ""))
                if name:
                    self._held.discard(name)

            def on_click(x, y, btn, pressed):
                if btn != mouse.Button.left:
                    return
                if pressed:
                    self._drag_start = (x, y)
                elif self._drag_start:
                    start = self._drag_start
                    self._drag_start = None
                    moved = (start[0]-x)**2 + (start[1]-y)**2 >= 20**2
                    if moved and shortcuts.drag_matches(self.shortcuts.drag, self._held):
                        self.show_wheel.emit()

            self._listen_keys = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listen_mouse = mouse.Listener(on_click=on_click)
            self._listen_keys.start()
            self._listen_mouse.start()
            self.hotkey_error = self._start_hotkey()
        except Exception as exc:
            self.selection_error = f"Global input hooks could not start: {type(exc).__name__}"

    def _start_hotkey(self) -> str:
        """(Re)register the global key. Returns an error message, or '' when fine."""
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None
        if not self.shortcuts.hotkey or self.selection is None:
            return ""
        hook = self._make_hotkey(self.shortcuts.hotkey, lambda: self.show_wheel.emit())
        error = hook.start()
        if error:
            return error
        self._hotkeys = hook
        return ""

    @staticmethod
    def _make_hotkey(text: str, callback):
        """The global-key listener for this system. Tests replace this one method."""
        if sys.platform == "win32":
            # Register with Windows: it tells us when another app already owns the combination,
            # and while we hold it no other app is triggered by it.
            from .winhotkey import WindowsHotkey
            return WindowsHotkey(text, callback)
        return PynputHotkey(text, callback)

    def apply_shortcuts(self):
        """Take new shortcut settings from the saved preferences and use them at once."""
        self.shortcuts = shortcuts.load(self.store)
        self._held.clear()
        error = self._start_hotkey()
        self.dashboard.show_shortcut_status(error or self.shortcuts.describe(), not error)

    def _on_selection_trigger(self):
        if self._closed or self.selection is None:
            return
        # Do not launch the wheel while editing inside the dashboard or preview.
        if self.dashboard.isActiveWindow() or self.card.isActiveWindow():
            return
        if self.shortcuts.skip_special_windows and self.selection.native.is_special_window():
            return
        raw = self.store.get_pref("excluded_titles", DEFAULT_EXCLUDED_TITLES)
        excluded = [phrase.strip().casefold() for phrase in raw.split(",") if phrase.strip()]
        source_title = self.selection.native.source_name().casefold()
        if any(phrase in source_title for phrase in excluded):
            return
        try:
            ctx = self.selection.capture()
        except Exception:
            return
        if ctx is None:
            return
        self.cancel_current()
        self.card.hide()
        self.context = ctx
        self.last_anchor = QCursor.pos()
        self.radial.set_actions(self.store.actions())
        self.radial.pop_at_cursor()

    def _open_custom(self):
        if self.context:
            self.card.show_custom_prompt_mode(self.last_anchor)

    def _run_from_selection(self, label: str, instruction: str):
        if self.context is None:
            return
        self._start_request(label, instruction, self.context.text, "selection")

    def _run_from_scratchpad(self, text: str, label: str, instruction: str):
        self.context = None
        self.last_anchor = QCursor.pos()
        self._start_request(label, instruction, text, "scratchpad")

    # -- requests ----------------------------------------------------------------------
    def _start_request(self, label: str, instruction: str, text: str, mode: str):
        self.cancel_current()
        self.pending_mode = mode
        self.pending_action = (label, instruction)
        self.pending_text = text
        self.pending_output = ""
        self.pending_history_id = None
        self.pending_start = time.monotonic()
        self.pending_source_name = self.context.app_name if mode == "selection" and self.context else "Scratchpad"
        self.inflight = True
        self.request_id += 1
        rid = self.request_id
        cancel = self.cancel_event
        profile = self.store.active_profile()
        self.pending_profile = profile
        started = self.pending_start
        key = api_key_for(profile, self.vault)
        if mode == "selection":
            self.card.show_loading(self.last_anchor, label)
        else:
            self.dashboard.scratch_state.setText("Connecting...")
            self.dashboard.scratch_result.clear()

        events = self.worker_events
        gate = {"text": 0.0, "think": 0.0}

        def on_delta(chunk):
            # Keep the screen smooth: at most about 25 updates a second. The final
            # text always arrives through `succeeded`.
            now = time.monotonic()
            if now - gate["text"] >= 0.04:
                gate["text"] = now
                events.progress.emit(rid, chunk)

        def on_thinking():
            now = time.monotonic()
            if now - gate["think"] >= 0.3:
                gate["think"] = now
                events.thinking.emit(rid)

        def work():
            try:
                output = self.client.generate(
                    profile, key, instruction, text,
                    on_delta=on_delta, cancel=cancel, on_thinking=on_thinking,
                )
                events.succeeded.emit(rid, output, int((time.monotonic()-started)*1000))
            except RequestCancelled:
                pass
            except ProviderError as exc:
                events.failed.emit(rid, str(exc), exc.code)
            except Exception:
                events.failed.emit(rid, "An unexpected model request error occurred.", "unexpected")

        t = threading.Thread(target=work, name=f"flowwriter-request-{rid}", daemon=True)
        self.threads = [w for w in self.threads if w.is_alive()] + [t]
        t.start()

    def _live(self, rid) -> bool:
        return rid == self.request_id and not self.cancel_event.is_set() and self.inflight

    def _on_thinking(self, rid):
        if not self._live(rid):
            return
        if self.pending_mode == "selection":
            self.card.show_thinking()
        else:
            self.dashboard.scratch_thinking()

    def _on_progress(self, rid, chunk):
        if not self._live(rid):
            return
        self.pending_output = chunk
        if self.pending_mode == "selection":
            self.card.show_stream(chunk)
        else:
            self.dashboard.scratch_progress(chunk)

    def _on_success(self, rid: int, output: str, latency_ms: int):
        if rid != self.request_id or self.cancel_event.is_set():
            return
        self.pending_output = output
        self.inflight = False
        profile = self.pending_profile or self.store.active_profile()
        action, instruction = self.pending_action or ("Custom", "")
        self.pending_history_id = self.store.log_action(
            action, source_app=(self.context.app_name if self.pending_mode == "selection" and self.context else "Scratchpad"),
            provider_name=profile.name, model=profile.model, instruction=instruction,
            input_text=self.pending_text, output_text=output, status="generated",
            latency_ms=latency_ms,
        )
        if self.pending_mode == "selection":
            self.card.show_result(output)
            self.dashboard.refresh()
        else:
            self.dashboard.scratch_complete(output)  # refreshes the dashboard itself

    def _on_failure(self, rid: int, message: str, error_code: str):
        if rid != self.request_id or self.cancel_event.is_set():
            return
        self.inflight = False
        action, instruction = self.pending_action or ("Custom", "")
        profile = self.pending_profile or self.store.active_profile()
        self.store.log_action(
            action, source_app=self.context.app_name if self.context else "Scratchpad",
            provider_name=profile.name, model=profile.model, instruction=instruction,
            input_text=self.pending_text[:MAX_INPUT_CHARS], output_text="", status="failed", error_type=error_code,
        )
        if self.pending_mode == "selection":
            self.card.show_error(message)
        else:
            self.dashboard.scratch_error(message)
        self.dashboard.refresh()

    def _reject(self):
        self.store.update_history(self.pending_history_id, "rejected", self.card.preview_box.toPlainText() if self.pending_output else None)
        self.cancel_current()
        self.dashboard.refresh()

    def _copy_result(self, text: str):
        QApplication.clipboard().setText(text)
        self.store.update_history(self.pending_history_id, "copied", text)
        self.cancel_current()
        self.dashboard.refresh()

    def _scratch_copied(self, text: str):
        if self.pending_mode == "scratchpad":
            self.store.update_history(self.pending_history_id, "copied", text)
            self.dashboard.refresh()

    def _attempt_replace(self, new_text: str):
        if self.pending_mode != "selection" or self.context is None or self.selection is None:
            self.card.show_replace_failed()
            return
        # The popover may hold focus. Hide before trying to restore target.
        self.card.hide()
        QApplication.processEvents()
        ok = False
        try:
            ok = self.selection.replace(self.context, new_text)
        except Exception:
            ok = False
        if ok:
            self.store.update_history(self.pending_history_id, "replaced", new_text)
            self.cancel_current()
            self.dashboard.refresh()
        else:
            self.card.show_result(new_text)
            self.card.show_replace_failed(
                getattr(self.selection, "last_failure", ""),
                retry=getattr(self.selection, "can_retry", False),
            )

    def _retry(self):
        if self.pending_action:
            self._start_request(*self.pending_action, self.pending_text, self.pending_mode)

    def _test_provider(self, profile: Provider, key: str):
        def work():
            try:
                result = self.client.test_connection(profile, key)
                self.worker_events.tested.emit(result, True)
            except ProviderError as exc:
                self.worker_events.tested.emit(str(exc), False)
            except Exception:
                self.worker_events.tested.emit("Unexpected connection test error.", False)
        t = threading.Thread(target=work, name="flowwriter-test", daemon=True)
        self.threads.append(t)
        t.start()

    def cancel_current(self):
        if self.inflight and self.pending_action and self.pending_profile:
            action, instruction = self.pending_action
            self.store.log_action(
                action, source_app=self.pending_source_name,
                provider_name=self.pending_profile.name, model=self.pending_profile.model,
                instruction=instruction, input_text=self.pending_text,
                output_text="", status="cancelled",
                latency_ms=int((time.monotonic() - self.pending_start) * 1000),
            )
        self.inflight = False
        self.cancel_event.set()
        self.cancel_event = threading.Event()
        self.request_id += 1

    # -- shutdown ----------------------------------------------------------------------
    def shutdown(self):
        """Stop everything once. Safe to call again (quit, then aboutToQuit)."""
        if self._closed:
            return
        self._closed = True
        self.cancel_current()
        for hook in (self._listen_keys, self._listen_mouse, self._hotkeys):
            if hook:
                try:
                    hook.stop()
                except Exception:
                    pass
        self.radial.hide()
        self.card.hide()
        self.tray.hide()
        self.store.close()

    def quit(self):
        self.shutdown()
        self.app.quit()
