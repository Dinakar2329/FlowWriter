"""History pages and search, speed, shared wording, providers form, shortcuts page, streaming card."""
import pytest

# Reuse the disposable-window fixtures from the main UI test module.
from test_ui_offscreen import add_history, dashboard, flush_ui, qt_app, wait_until  # noqa: F401


def fill_history(window, count):
    for i in range(count):
        window.store.log_action(
            "Polish" if i % 2 else "Summarize", source_app=f"App {i}", input_text=f"input {i}",
            output_text="rare-needle here" if i == 7 else f"output {i}", instruction="Do it.",
            status="replaced" if i % 4 == 0 else "generated",
        )


def history_cards_text(window):
    from flowwriter.dashboard_widgets import ReadableText
    return [item.text() for item in window.history.widget().findChildren(ReadableText)]


def test_history_pages_cover_every_entry_without_gaps(dashboard, qt_app):
    fill_history(dashboard, 25)
    dashboard.navigate(1)
    flush_ui(qt_app)
    assert dashboard.history_count.text() == "25 saved entries"
    assert dashboard.history_pager.isVisible() and dashboard.history_pager.summary.text() == "1–10 of 25"
    seen = []
    for page in range(3):
        dashboard.go_to_history_page(page)
        flush_ui(qt_app)
        seen += history_cards_text(dashboard)
    assert len(seen) == 25 and len(set(seen)) == 25          # the old screen drew 120 of "800"
    assert dashboard.history_pager.summary.text() == "21–25 of 25"


def test_history_search_covers_old_entries_and_pages_the_matches(dashboard, qt_app):
    fill_history(dashboard, 25)
    dashboard.navigate(1)
    dashboard.history_search.setText("rare-needle")
    wait_until(lambda: dashboard.history_count.text() == "1 matching entries")
    assert history_cards_text(dashboard) == ["rare-needle here"]
    assert not dashboard.history_pager.isVisible()
    dashboard.history_search.setText("output")
    wait_until(lambda: dashboard.history_count.text() == "24 matching entries")
    dashboard.go_to_history_page(2)
    flush_ui(qt_app)
    assert dashboard.history_pager.summary.text() == "21–24 of 24"
    dashboard.history_filter.setCurrentIndex(dashboard.history_filter.findData("replaced"))
    wait_until(lambda: dashboard.history_count.text() == "7 matching entries")   # entries 0, 4, 8 ... 24
    assert dashboard._history_page == 0                       # a new filter starts again from page 1


def test_page_is_clamped_after_deleting_the_last_entry_on_it(dashboard, qt_app, monkeypatch):
    from flowwriter.dialogs import MessageBox
    fill_history(dashboard, 21)
    dashboard.navigate(1)
    dashboard.go_to_history_page(2)
    flush_ui(qt_app)
    assert len(history_cards_text(dashboard)) == 1
    monkeypatch.setattr(MessageBox, "question", classmethod(lambda cls, *a, **k: MessageBox.Yes))
    dashboard.delete_history_row(dashboard.store.history_page(limit=1, offset=20)[0])
    flush_ui(qt_app)
    assert dashboard._history_page == 1 and len(history_cards_text(dashboard)) == 10   # clamped, not blank


def test_status_names_are_the_same_everywhere(dashboard, qt_app):
    from PySide6.QtWidgets import QLabel
    from flowwriter.labels import STATUS_LABELS
    labels = [dashboard.history_filter.itemText(i) for i in range(dashboard.history_filter.count())]
    assert labels == ["All statuses"] + list(STATUS_LABELS.values())
    texts = [item.text() for item in dashboard.home_rail.findChildren(QLabel)]
    assert "replaced in source" in texts and "discarded" in texts and "applied to source" not in texts
    dashboard.store.log_action("Polish", input_text="a", output_text="b", status="rejected")
    dashboard.navigate(1)
    flush_ui(qt_app)
    chips = [item.text() for item in dashboard.history.widget().findChildren(QLabel) if item.objectName() == "chip"]
    assert chips == ["Discarded"]


def test_navigation_names_match_page_headings(dashboard, qt_app):
    from PySide6.QtWidgets import QLabel
    for index, name in enumerate(dashboard.page_names):
        if name in ("Overview", "Scratchpad", "Insights"):
            continue                                            # Overview greets; the others already match
        dashboard.navigate(index)
        headings = [item.text() for item in dashboard.pages.currentWidget().widget().findChildren(QLabel)
                    if item.objectName() == "h1"]
        assert headings[0] == name, (name, headings)


def test_overview_refresh_does_not_decrypt_the_whole_history(dashboard, qt_app, monkeypatch):
    fill_history(dashboard, 80)
    decrypted = []
    real = dashboard.store._decrypt
    monkeypatch.setattr(dashboard.store, "_decrypt", lambda data: decrypted.append(1) or real(data))
    dashboard.refresh()
    flush_ui(qt_app)
    assert len(decrypted) <= 40                                # one page of 10; was ~1,300 on every refresh
    assert sum(dashboard.activity_chart.series) == 80


def test_scratchpad_run_refreshes_the_dashboard_once(dashboard, monkeypatch):
    calls = []
    real = dashboard.store.stats
    monkeypatch.setattr(dashboard.store, "stats", lambda: calls.append(1) or real())
    dashboard.scratch_complete("done")
    assert len(calls) == 1


def test_date_label_follows_the_calendar(dashboard):
    from datetime import datetime
    dashboard.home_date.setText("An old date")
    dashboard._tick()
    assert dashboard.home_date.text() == datetime.now().strftime("%B %d, %Y")


def test_recent_rows_say_which_day(dashboard, qt_app):
    from PySide6.QtWidgets import QLabel
    from flowwriter.dashboard_widgets import RecentEntry
    add_history(dashboard)
    dashboard.refresh()
    flush_ui(qt_app)
    row = dashboard.findChildren(RecentEntry)[0]
    stamp = next(item.text() for item in row.findChildren(QLabel) if item.objectName() == "muted")
    assert stamp.startswith("Today\n") and ("AM" in stamp or "PM" in stamp)


def test_date_format_is_shared():
    from datetime import datetime, timedelta, timezone
    from flowwriter.labels import when
    now = datetime(2026, 11, 14, 15, 0).astimezone()

    def at(days, hour, minute):
        return (now - timedelta(days=days)).replace(hour=hour, minute=minute).astimezone(timezone.utc).isoformat()

    assert when(at(0, 12, 54), now) == "Today 12:54 PM"
    assert when(at(1, 9, 5), now) == "Yesterday 9:05 AM"
    assert when(at(5, 18, 30), now) == "Nov 9 · 6:30 PM"
    assert "2025" in when(at(400, 8, 0), now)
    assert when("not a date", now) == "not a date"


def test_providers_page_keeps_unsaved_edits_and_asks_before_dropping_them(dashboard, qt_app, monkeypatch):
    from flowwriter.dialogs import MessageBox
    dashboard.navigate(4)
    dashboard.provider_model.setText("typed-model")
    dashboard.provider_model.textEdited.emit("typed-model")
    dashboard.navigate(0)
    dashboard.navigate(4)
    assert dashboard.provider_model.text() == "typed-model"       # coming back no longer wipes the form
    asked = []
    monkeypatch.setattr(MessageBox, "question", classmethod(lambda cls, *a, **k: asked.append(a[1]) or MessageBox.No))
    dashboard.new_profile()
    assert asked == ["Unsaved changes"] and dashboard.provider_model.text() == "typed-model"
    monkeypatch.setattr(MessageBox, "question", classmethod(lambda cls, *a, **k: MessageBox.Yes))
    dashboard.new_profile()
    assert dashboard.provider_model.text() == "" and not dashboard._provider_dirty


def test_saved_api_key_is_not_loaded_into_the_form_until_asked(dashboard, qt_app, monkeypatch):
    from flowwriter.dialogs import MessageBox
    profile = dashboard.store.profiles()[0]
    dashboard.vault.put("provider-" + profile.id, "sk-secret")
    dashboard.navigate(4)
    flush_ui(qt_app)
    assert dashboard.provider_key.text() == ""                    # nothing readable sits in the widget
    assert "saved" in dashboard.provider_key.placeholderText().lower()
    assert not dashboard.remove_key_button.isHidden()
    dashboard.provider_show_key.setChecked(True)
    assert dashboard.provider_key.text() == "sk-secret"
    dashboard.provider_show_key.setChecked(False)
    assert dashboard.provider_key.text() == ""
    dashboard.save_profile()                                      # an empty box keeps the saved key
    assert dashboard.vault.get("provider-" + profile.id) == "sk-secret"
    monkeypatch.setattr(MessageBox, "question", classmethod(lambda cls, *a, **k: MessageBox.Yes))
    dashboard.remove_saved_key()
    assert dashboard.vault.get("provider-" + profile.id) == ""


def test_closing_the_window_hides_it_but_never_blocks_a_system_shutdown(dashboard, qt_app, monkeypatch):
    from PySide6.QtGui import QCloseEvent, QGuiApplication
    dashboard.close()
    assert not dashboard.isVisible()                              # tray behaviour is unchanged
    dashboard.show()
    monkeypatch.setattr(QGuiApplication, "isSavingSession", lambda self: True)
    event = QCloseEvent()
    event.ignore()
    dashboard.closeEvent(event)
    assert event.isAccepted()                                     # Windows can finish shutting down


def test_private_mode_button_looks_like_a_switch(dashboard, qt_app):
    assert not dashboard.private_button.isChecked() and dashboard.private_button.objectName() == ""
    dashboard.toggle_private()
    assert dashboard.private_button.isChecked() and dashboard.private_button.objectName() == "privateOn"
    assert dashboard.private_button.text() == "Private mode: On"
    dashboard.toggle_private()
    assert not dashboard.private_button.isChecked() and dashboard.private_button.text() == "Private mode: Off"


def test_shortcuts_page_saves_validates_and_resets(dashboard, qt_app, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QSignalSpy
    from flowwriter import shortcuts
    from flowwriter.dialogs import MessageBox
    warned = []
    monkeypatch.setattr(MessageBox, "warning", classmethod(lambda cls, *a, **k: warned.append(a[2])))
    dashboard.navigate(7)
    flush_ui(qt_app)
    assert dashboard.drag_choice.currentData() == "ctrl"
    assert dashboard.hotkey_edit.keySequence().toString(QKeySequence.PortableText) == "Ctrl+Alt+Space"
    changed = QSignalSpy(dashboard.shortcuts_changed)
    dashboard.hotkey_edit.setKeySequence(QKeySequence("Ctrl+C"))
    dashboard.save_shortcuts()
    assert changed.count() == 0 and warned and "two modifier" in warned[0]      # refused, nothing saved
    assert shortcuts.load(dashboard.store).hotkey == "Ctrl+Alt+Space"
    dashboard.drag_choice.setCurrentIndex(dashboard.drag_choice.findData("alt"))
    dashboard.hotkey_edit.clear()
    dashboard.save_shortcuts()
    saved = shortcuts.load(dashboard.store)
    assert changed.count() >= 1 and saved.drag == frozenset({"alt"}) and saved.hotkey == ""   # the drag change also saved by itself
    assert "Alt" in dashboard.shortcut_hint.text()
    dashboard.reset_shortcuts()
    assert shortcuts.load(dashboard.store) == shortcuts.Shortcuts()
    assert dashboard.hotkey_edit.keySequence().toString(QKeySequence.PortableText) == "Ctrl+Alt+Space"


def test_excluded_titles_default_lists_password_managers(dashboard, qt_app):
    dashboard.navigate(5)
    assert "KeePass" in dashboard.excluded_titles.text() and "1Password" in dashboard.excluded_titles.text()
    dashboard.store.set_pref("excluded_titles", "")
    dashboard.load_privacy()
    assert dashboard.excluded_titles.text() == ""                 # clearing the list is respected


def test_card_streams_text_and_only_allows_replace_when_finished(qt_app):
    from PySide6.QtCore import QPoint
    from flowwriter.overlay import PreviewPopupCard
    card = PreviewPopupCard()
    card.show_loading(QPoint(400, 200), "Polish")
    assert card.progress.isVisible() and not card.preview_box.isVisible()
    card.show_thinking()
    assert card.status_label.text().startswith("Thinking")
    card.show_stream("First words")
    assert card.status_label.text().startswith("Writing") and card.preview_box.toPlainText() == "First words"
    assert card.preview_box.isVisible() and card.progress.isVisible()
    assert not card.primary_btn.isVisible() and not card.copy_btn.isVisible() and card.cancel_btn.isVisible()
    card.show_stream("word " * 400)
    assert card.preview_box.height() <= card.PREVIEW_MAX_H
    card.show_result("Final")
    assert card.primary_btn.isVisible() and card.primary_btn.isEnabled() and not card.progress.isVisible()
    assert not card.preview_box.isReadOnly()
    card.show_stream("late chunk")                                # a stray late chunk must not undo the result
    assert card.preview_box.toPlainText() == "Final"
    card.hide()
    card.deleteLater()
    flush_ui(qt_app)


def test_recent_list_keeps_its_height_when_a_refresh_arrives_while_the_window_is_open(dashboard, qt_app):
    """A transformation finishing while the Overview is visible used to leave the list 1 px tall (blank)."""
    from PySide6.QtTest import QTest
    from flowwriter.dashboard_widgets import RecentEntry
    dashboard.resize(1900, 1000)
    for i in range(34):  # long, multi-line rows like real output
        dashboard.store.log_action("Rephrase", input_text="in", output_text=f"Entry {i} " + "word " * 30)
    dashboard.refresh()
    wait_until(lambda: dashboard.recent_scroll.height() == dashboard.RECENT_MAX_HEIGHT)
    dashboard.recent_scroll.verticalScrollBar().setValue(300)
    QTest.qWait(50)                                       # let the window settle, as it does in real use
    dashboard.store.log_action("Polish", input_text="in", output_text="finished while the window was open " + "word " * 30)
    dashboard.refresh()                                   # what the controller does after a transformation
    wait_until(lambda: dashboard.recent_scroll.height() == dashboard.RECENT_MAX_HEIGHT)
    flush_ui(qt_app)
    visible = [e for e in dashboard.findChildren(RecentEntry) if e.isVisible()]
    assert len(visible) == 10
    assert dashboard.recent_scroll.viewport().height() > 100


def test_recent_list_recovers_from_a_short_page_to_a_full_one(dashboard, qt_app):
    dashboard.refresh()
    add_history(dashboard)
    dashboard.refresh()
    wait_until(lambda: 1 < dashboard.recent_scroll.height() < dashboard.RECENT_MAX_HEIGHT)
    fill_history(dashboard, 12)
    dashboard.refresh()
    wait_until(lambda: dashboard.recent_scroll.height() == dashboard.RECENT_MAX_HEIGHT)


def test_checkbox_rules_draw_a_visible_tick_instead_of_the_system_accent_fill():
    from flowwriter.styles import APP_STYLESHEET, checkbox_rules
    rules = checkbox_rules()
    assert "QCheckBox::indicator:checked" in rules and "QCheckBox::indicator:unchecked" in rules
    assert rules in APP_STYLESHEET
    import re
    from PySide6.QtGui import QImage, QColor
    for match in re.finditer(r'url\("([^"]+)"\)', rules):
        image = QImage(match.group(1))
        assert not image.isNull() and image.width() == 17
    checked = QImage(re.search(r'checked \{ image: url\("([^"]+box-on\.png)', rules).group(1))
    # a white tick must be present inside the dark box
    assert QColor(checked.pixel(8, 10)).lightness() > 200 or QColor(checked.pixel(7, 11)).lightness() > 200


def test_writing_sources_lists_apps_and_opens_details_in_place(qt_app):
    from datetime import date
    from flowwriter.insights import InsightRecord, UsageSummary
    from flowwriter.sources_ui import SourcesCard, AppRow
    from PySide6.QtWidgets import QPushButton
    summary = UsageSummary(date.today())
    stamp = __import__("datetime").datetime.now().astimezone().isoformat()
    for i, title in enumerate(["Q3.xlsx - Excel", "Budget.xlsx - Excel", "Inbox - Alex - Outlook"]):
        summary.add(InsightRecord(i, stamp, "Polish", "copied", title, 6))
    card = SourcesCard()
    card.set_summary(summary)
    rows = card.list_page.findChildren(AppRow)
    assert [r.accessibleName().split(":")[0] for r in rows] == ["Excel", "Outlook"]
    rows[0].click()
    assert card.currentWidget() is card.detail_page
    texts = [w.text() for w in card.detail_page.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    assert "Excel" in texts and "2" in texts and "Q3.xlsx" in texts and "Budget.xlsx" in texts
    back = next(b for b in card.detail_page.findChildren(QPushButton) if b.text() == "All apps")
    back.click()
    assert card.currentWidget() is card.list_page
    card.open_app(summary.apps["excel"])
    card.set_summary(summary)                       # a refresh keeps the open app open
    assert card.currentWidget() is card.detail_page


def test_icon_buttons_keep_an_even_gap_and_normal_size(qt_app):
    from flowwriter.dashboard_widgets import AppButton, button
    plain = button("Save", True)
    with_icon = button("Save", True, icon_name="check")
    from flowwriter.styles import APP_STYLESHEET
    for item in (plain, with_icon):
        item.setStyleSheet(APP_STYLESHEET)          # sizes are measured as in the app
    assert isinstance(with_icon, AppButton)
    assert with_icon.sizeHint().width() > plain.sizeHint().width() + with_icon.iconSize().width()   # room for the 8 px gap
    with_icon.resize(with_icon.sizeHint())
    assert not with_icon.grab().isNull()            # paints without error


def test_every_icon_draws_visible_pixels_and_actions_have_icons(qt_app):
    """QtSvg silently skips markup it does not understand, so check real pixels, not just names."""
    from PySide6.QtCore import QSize
    from flowwriter import icons
    from flowwriter.domain import PRESETS, PROMPT_ACTION
    assert "stroke" not in "".join(icons.LUCIDE.values()) and "<g" not in "".join(icons.LUCIDE.values())
    for name in icons.PATHS:
        image = icons.icon(name).pixmap(QSize(24, 24)).toImage()
        painted = sum(1 for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 40)
        assert painted > 20, f"icon '{name}' draws almost nothing"
    for action_name, _prompt in [*PRESETS, PROMPT_ACTION]:
        assert icons.action_icon_name(action_name) in icons.PATHS and icons.action_icon_name(action_name) != "actions"
    assert icons.action_icon_name("My own action") == "actions"       # user-made actions fall back to the bolt
