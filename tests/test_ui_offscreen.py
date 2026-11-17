"""UI behavior and layout checks; all stores and keychains are disposable."""
import os
from pathlib import Path
import sys

import pytest


class FakeKeychain:
    def get_password(self, *args):
        return ""

    def set_password(self, *args):
        return None


@pytest.fixture(scope="module")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    # Windows offscreen Qt does not enumerate fonts, unlike the native platform.
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf", "georgia.ttf", "cambria.ttc"):
            QFontDatabase.addApplicationFont(str(fonts / filename))
    yield app


def wait_until(condition, timeout_ms=3000):
    from PySide6.QtTest import QTest

    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(25)
        waited += 25
    assert condition(), "condition not met in time"


def flush_ui(app):
    from PySide6.QtCore import QEvent

    app.processEvents()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@pytest.fixture
def dashboard(qt_app, tmp_path):
    from cryptography.fernet import Fernet
    from flowwriter.dashboard import MainWindow
    from flowwriter.storage import Store
    from flowwriter.vault import SecretVault

    store = Store(tmp_path / "ui.db", Fernet(Fernet.generate_key()))
    window = MainWindow(store, SecretVault(FakeKeychain()))
    window.show()
    flush_ui(qt_app)
    yield window
    window.hide()
    window.deleteLater()
    flush_ui(qt_app)
    store.close()


def add_history(window):
    return window.store.log_action(
        "Polish", input_text="A draft to revisit.", output_text="<b>Keep this literal.</b> Your revised draft.",
        instruction="Polish this text.", source_app="A very long document window title " * 4,
        status="copied",
    )


def test_all_navigation_controls_work(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    expected = ["Overview", "History", "Scratchpad", "Actions", "Providers", "Privacy", "Insights", "Shortcuts"]
    assert dashboard.page_names == expected
    for index, control in enumerate(dashboard.nav_buttons):
        assert control.accessibleName() == expected[index]
        assert not control.icon().isNull()
        QTest.mouseClick(control, Qt.LeftButton)
        flush_ui(qt_app)
        assert dashboard.pages.currentIndex() == index
        assert [item.isChecked() for item in dashboard.nav_buttons] == [i == index for i in range(8)]


@pytest.mark.parametrize("custom", [False, True])
def test_start_writing_and_transform_preserve_user_input(dashboard, qt_app, custom):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    QTest.mouseClick(dashboard.start_writing, Qt.LeftButton)
    assert dashboard.pages.currentIndex() == 2
    text = "A draft with <tags> and a second line.\nKeep my line breaks."
    dashboard.scratch_input.setPlainText(text)
    instruction = "Make this warmer." if custom else ""
    dashboard.scratch_instruction.setText(instruction)
    selected = dashboard.store.actions()[dashboard.scratch_action.currentIndex()]
    requested = QSignalSpy(dashboard.scratchpad_requested)
    dashboard.submit_scratchpad()
    assert requested.count() == 1
    assert requested.at(0) == [text, selected.name, instruction or selected.prompt]

    copied = QSignalSpy(dashboard.scratch_copied)
    dashboard.scratch_complete("Edited output.")
    dashboard.copy_scratchpad_result()
    assert qt_app.clipboard().text() == "Edited output."
    assert copied.at(0) == ["Edited output."]


def test_recent_row_actions_and_literal_text(dashboard, qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QPushButton
    from flowwriter.dashboard import HistoryDialog
    from flowwriter.dashboard_widgets import RecentEntry

    row_id = add_history(dashboard)
    dashboard.refresh()
    flush_ui(qt_app)
    entries = dashboard.findChildren(RecentEntry)
    assert len(entries) == 1
    row = entries[0]
    text = next(item for item in row.findChildren(QLabel) if "<b>" in item.text())
    assert text.textFormat() == Qt.PlainText
    controls = {item.accessibleName(): item for item in row.findChildren(QPushButton)}
    QTest.mouseClick(controls["Copy transformed text"], Qt.LeftButton)
    assert qt_app.clipboard().text() == "<b>Keep this literal.</b> Your revised draft."
    opened = []
    monkeypatch.setattr(HistoryDialog, "exec", lambda self: opened.append(self.record["id"]))
    QTest.mouseClick(controls["Open transformation details"], Qt.LeftButton)
    assert opened == [row_id]
    assert dashboard.metric_labels["total"].text() == "1"
    assert dashboard.metric_labels["copied"].text() == "1"


def test_history_search_filter_favorite_and_reuse(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    row_id = add_history(dashboard)
    dashboard.refresh()
    dashboard.navigate(1)
    flush_ui(qt_app)
    favorite = next(item for item in dashboard.history.widget().findChildren(QPushButton)
                    if item.accessibleName() == "Add to favorites")
    QTest.mouseClick(favorite, Qt.LeftButton)
    flush_ui(qt_app)
    assert dashboard.store.recent()[0]["is_favorite"] == 1
    dashboard.history_search.setText("unmatched query")
    wait_until(lambda: dashboard.history_count.text().startswith("0 matching entries"))
    dashboard.history_search.clear()
    dashboard.history_filter.setCurrentIndex(dashboard.history_filter.findData("replaced"))
    wait_until(lambda: dashboard.history_count.text().startswith("0 saved entries"))
    dashboard.history_filter.setCurrentIndex(dashboard.history_filter.findData("copied"))
    wait_until(lambda: dashboard.history_count.text().startswith("1 saved entries"))
    reuse = next(item for item in dashboard.history.widget().findChildren(QPushButton) if item.text() == "Reuse")
    QTest.mouseClick(reuse, Qt.LeftButton)
    assert dashboard.pages.currentIndex() == 2
    assert dashboard.scratch_input.toPlainText() == "A draft to revisit."
    assert dashboard.scratch_instruction.text() == "Polish this text."


@pytest.mark.parametrize("width,height", [(920, 620), (1360, 880), (1920, 1080)])
def test_pages_fit_supported_window_sizes(dashboard, qt_app, width, height):
    from PySide6.QtWidgets import QPushButton

    add_history(dashboard)
    dashboard.refresh()
    dashboard.resize(width, height)
    for index in range(8):
        dashboard.navigate(index)
        flush_ui(qt_app)
        page = dashboard.pages.currentWidget()
        content = page.widget()
        assert content.width() <= page.viewport().width(), f"Page {index} overflows at {width}px"
        for control in content.findChildren(QPushButton):
            if control.isVisible():
                right_edge = control.mapTo(content, control.rect().topRight()).x()
                assert right_edge < content.width(), f"{control.text() or control.accessibleName()} is clipped"
    # Switching back to a wide layout must restore the rail and full editor.
    dashboard.resize(1360, 880)
    dashboard.navigate(0)
    flush_ui(qt_app)
    assert dashboard.home_rail.width() == 268
    assert dashboard.shortcut_card.isVisible()


@pytest.mark.parametrize("cipher_available,save_history,private,expected", [
    (True, True, False, "Encrypted local history"),
    (True, True, True, "Private mode is on"),
    (True, False, False, "History saving is paused"),
    (False, True, False, "History saving is paused"),
])
def test_privacy_summary_reflects_actual_storage(dashboard, cipher_available, save_history, private, expected):
    if not cipher_available:
        dashboard.store.cipher = None
    dashboard.store.set_pref("save_history", "true" if save_history else "false")
    dashboard.store.set_pref("private_mode", "true" if private else "false")
    dashboard.load_privacy()
    assert dashboard.home_privacy_status.text() == expected
    if private or not save_history or not cipher_available:
        assert "not saved" in dashboard.home_privacy_detail.text()
    dashboard.toggle_private()
    assert dashboard.private_toggle.isChecked() != private


def test_empty_history_provides_a_working_start_action(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    assert dashboard.metric_labels["total"].text() == "0"
    assert sum(dashboard.activity_chart.series) == 0
    start = next(item for item in dashboard.home.widget().findChildren(QPushButton)
                 if item.text() == "Open Scratchpad")
    QTest.mouseClick(start, Qt.LeftButton)
    assert dashboard.pages.currentIndex() == 2


def test_vector_icons_render_at_multiple_resolutions(qt_app):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from flowwriter.icons import PATHS, icon

    for name in PATHS:
        for scale in (1.0, 2.0):
            raster = icon(name).pixmap(QSize(24, 24), scale).toImage()
            assert raster.width() == 24 * scale
            assert any(raster.pixelColor(x, y).alpha() > 0
                       for x in range(raster.width()) for y in range(raster.height())), name
    assert not icon("copy").pixmap(QSize(24, 24), QIcon.Disabled).isNull()


def test_preview_controls_fit_and_emit_edited_text(qt_app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from flowwriter.overlay import PreviewPopupCard

    preview = PreviewPopupCard()
    preview.show_loading(QPoint(400, 200), "Polish")
    preview.show_result("Initial output")
    flush_ui(qt_app)
    for control in (preview.copy_btn, preview.cancel_btn, preview.primary_btn):
        assert preview.card.rect().contains(control.mapTo(preview.card, control.rect().topRight()))
    preview.preview_box.setPlainText("My edited output")
    copied = QSignalSpy(preview.copied)
    QTest.mouseClick(preview.copy_btn, Qt.LeftButton)
    assert copied.at(0) == ["My edited output"]
    preview.show_result("Another output")
    preview.show_replace_failed()
    assert not preview.primary_btn.isEnabled()
    assert preview.copy_btn.isVisible()
    preview.hide()
    preview.deleteLater()
    flush_ui(qt_app)


def test_insights_metrics_tabs_and_calendar_are_operable(dashboard, qt_app, capfd):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    add_history(dashboard)
    dashboard.navigate(6)
    QTest.qWait(60)
    panel = dashboard.insights_panel
    assert panel.summary.completed == 1
    assert panel.metrics["words"].text() == "6"
    assert panel.metrics["used"].text() == "100%"
    assert "1 of 1" in panel.metric_captions["used"].text()
    QTest.mouseClick(panel.tabs, Qt.LeftButton, pos=panel.tabs.tabRect(1).center())
    assert panel.pages.currentIndex() == 1
    assert panel.summary.actions == {"Polish": 1}
    QTest.mouseClick(panel.tabs, Qt.LeftButton, pos=panel.tabs.tabRect(0).center())
    flush_ui(qt_app)
    calendar = panel.calendar
    active = calendar.grid.item(panel.summary.today.weekday(), 25)
    zero = calendar.grid.item(0, 0)
    image = calendar.grid.viewport().grab().toImage()
    active_color = image.pixelColor(calendar.grid.visualItemRect(active).center())
    zero_color = image.pixelColor(calendar.grid.visualItemRect(zero).center())
    assert active_color != zero_color, "Calendar must visibly distinguish active and inactive days"
    assert "1 transformations" in calendar.selected_day.text()
    calendar.grid.setFocus()
    QTest.keyClick(calendar.grid, Qt.Key_Left)
    assert "0 transformations" in calendar.selected_day.text()
    assert "Error calling Python override" not in capfd.readouterr().err


def test_insights_refresh_tracks_deletion_and_private_mode(dashboard, qt_app):
    from PySide6.QtTest import QTest

    add_history(dashboard)
    dashboard.navigate(6)
    QTest.qWait(50)
    dashboard.toggle_private()
    QTest.qWait(50)
    assert "not being saved" in dashboard.insights_panel.note.text()
    assert dashboard.insights_panel.summary.completed == 1  # Saved history remains visible.
    dashboard.store.clear_history()
    dashboard.refresh()
    QTest.qWait(50)
    assert dashboard.insights_panel.summary.completed == 0
    assert dashboard.insights_panel.metrics["words"].text() == "0"


def test_insights_unreadable_history_is_explicit(dashboard, qt_app):
    from PySide6.QtTest import QTest

    add_history(dashboard)
    dashboard.store.cipher = None
    dashboard.navigate(6)
    QTest.qWait(50)
    panel = dashboard.insights_panel
    assert panel.metrics["words"].text() == "—"
    assert panel.metrics["completed"].text() == "1"
    assert "could not be unlocked" in panel.note.text()


def test_insights_read_error_keeps_previous_values_and_can_retry(dashboard, qt_app, monkeypatch):
    import sqlite3
    from PySide6.QtTest import QTest

    add_history(dashboard)
    dashboard.navigate(6)
    QTest.qWait(50)
    panel = dashboard.insights_panel
    with monkeypatch.context() as patch:
        def fail(*args):
            raise sqlite3.OperationalError("Synthetic read error")
        patch.setattr(dashboard.store, "insight_batch", fail)
        panel.refresh()
        QTest.qWait(50)
        assert "Could not load" in panel.status.text()
        assert panel.metrics["completed"].text() == "1"
    panel.refresh()
    QTest.qWait(50)
    assert "all time" in panel.status.text()


def test_feed_text_keeps_literal_content_and_has_room_for_lines(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from flowwriter.dashboard_widgets import ReadableText

    add_history(dashboard)
    dashboard.refresh()
    flush_ui(qt_app)
    text = dashboard.home.widget().findChild(ReadableText)
    assert text.textFormat() == Qt.PlainText
    assert text._document(300).toPlainText() == "<b>Keep this literal.</b> Your revised draft."
    assert text.heightForWidth(100) > text.heightForWidth(500)
    assert text.height() >= text.heightForWidth(text.width())


def recent_entries(dashboard):
    from flowwriter.dashboard_widgets import RecentEntry
    return dashboard.recent_scroll.widget().findChildren(RecentEntry)


def pager_buttons(dashboard):
    from PySide6.QtWidgets import QPushButton
    return {item.accessibleName(): item for item in dashboard.recent_pager.findChildren(QPushButton)
            if not item.isHidden()}


def test_recent_transformations_paginate_without_gaps_or_duplicates(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    for i in range(25):
        dashboard.store.log_action("Polish", input_text=f"Draft {i}", output_text=f"Output {i}")
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard.recent_pager.isVisible()
    assert dashboard.recent_pager.summary.text() == "1–10 of 25"
    seen = [e.findChild(type(dashboard.recent_pager.summary), "body").text() for e in recent_entries(dashboard)]
    assert len(seen) == 10 and seen[0] == "Output 24"
    assert not pager_buttons(dashboard)["Previous page"].isEnabled()

    QTest.mouseClick(pager_buttons(dashboard)["Next page"], Qt.LeftButton)
    flush_ui(qt_app)
    assert dashboard.recent_pager.summary.text() == "11–20 of 25"
    second = [e.findChild(type(dashboard.recent_pager.summary), "body").text() for e in recent_entries(dashboard)]
    assert second[0] == "Output 14" and not set(seen) & set(second)

    QTest.mouseClick(pager_buttons(dashboard)["Page 3 of 3"], Qt.LeftButton)
    flush_ui(qt_app)
    last = recent_entries(dashboard)
    assert len(last) == 5
    assert dashboard.recent_pager.summary.text() == "21–25 of 25"
    assert not pager_buttons(dashboard)["Next page"].isEnabled()
    assert pager_buttons(dashboard)["Page 3 of 3"].accessibleDescription() == "Current page"


def test_recent_pager_is_hidden_when_everything_fits_on_one_page(dashboard, qt_app):
    for i in range(10):
        dashboard.store.log_action("Polish", input_text=f"Draft {i}", output_text=f"Output {i}")
    dashboard.refresh()
    flush_ui(qt_app)
    assert len(recent_entries(dashboard)) == 10
    assert not dashboard.recent_pager.isVisible()
    dashboard.store.log_action("Polish", input_text="One more", output_text="Eleventh")
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard.recent_pager.isVisible()
    assert len(recent_entries(dashboard)) == 10


def test_recent_page_is_kept_on_refresh_and_clamped_after_deletes(dashboard, qt_app):
    for i in range(21):
        dashboard.store.log_action("Polish", input_text=f"Draft {i}", output_text=f"Output {i}")
    dashboard.refresh()
    dashboard.go_to_recent_page(2)
    flush_ui(qt_app)
    assert len(recent_entries(dashboard)) == 1
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard._recent_page == 2  # a background refresh must not bounce the reader to page 1
    dashboard.store.delete_history(dashboard.store.history_page(limit=1, offset=20)[0]["id"])
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard._recent_page == 1
    assert len(recent_entries(dashboard)) == 10
    dashboard.store.clear_history()
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard.home_empty.isVisible()
    assert not dashboard.recent_scroll.isVisible() and not dashboard.recent_pager.isVisible()


def test_recent_list_scrolls_inside_its_card(dashboard, qt_app):
    from PySide6.QtCore import Qt

    for i in range(10):
        dashboard.store.log_action("Polish", input_text="x", output_text="A longer result sentence. " * 12)
    dashboard.refresh()
    flush_ui(qt_app)
    area = dashboard.recent_scroll
    bar = area.verticalScrollBar()
    assert area.height() <= dashboard.RECENT_MAX_HEIGHT
    assert bar.maximum() > 0, "a full page of long entries must scroll inside the card"
    assert area.bottom_fade.isVisible() and not area.top_fade.isVisible()
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    bar.setValue(bar.maximum())
    flush_ui(qt_app)
    assert area.top_fade.isVisible() and not area.bottom_fade.isVisible()
    dashboard.go_to_recent_page(0)
    assert bar.value() == 0  # changing page starts at the top


def test_wheel_scrolls_list_first_then_the_page_behind_it(dashboard, qt_app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    for i in range(10):
        dashboard.store.log_action("Polish", input_text="x", output_text="A longer result sentence. " * 12)
    dashboard.resize(920, 620)
    dashboard.refresh()
    flush_ui(qt_app)
    inner, page = dashboard.recent_scroll.verticalScrollBar(), dashboard.home.verticalScrollBar()
    assert inner.maximum() > 0 and page.maximum() > 0
    page.setValue(page.maximum() // 2)
    viewport = dashboard.recent_scroll.viewport()

    def wheel(delta):
        position = QPointF(viewport.rect().center())
        QApplication.sendEvent(viewport, QWheelEvent(
            position, viewport.mapToGlobal(position), QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
            Qt.NoModifier, Qt.NoScrollPhase, False))

    before = page.value()
    wheel(-120)
    assert inner.value() > 0 and page.value() == before, "the list scrolls first"
    for _ in range(80):
        wheel(-120)
    assert inner.value() == inner.maximum()
    assert page.value() > before, "at the end of the list the page behind must keep scrolling"
    for _ in range(80):
        wheel(120)
    assert inner.value() == 0 and page.value() < before


def test_short_recent_list_does_not_leave_blank_space(dashboard, qt_app):
    add_history(dashboard)
    dashboard.refresh()
    flush_ui(qt_app)
    entry = recent_entries(dashboard)[0]
    assert dashboard.recent_scroll.height() < dashboard.RECENT_MAX_HEIGHT
    assert dashboard.recent_scroll.verticalScrollBar().maximum() == 0
    assert dashboard.recent_scroll.height() >= entry.height()


def test_page_numbers_collapse_long_ranges():
    from flowwriter.dashboard_widgets import page_numbers

    assert page_numbers(0, 0) == []
    assert page_numbers(0, 1) == [0]
    assert page_numbers(0, 3) == [0, 1, 2]
    assert page_numbers(0, 9) == [0, 1, None, 8]
    assert page_numbers(4, 9) == [0, None, 3, 4, 5, None, 8]
    assert page_numbers(8, 9) == [0, None, 7, 8]
    assert page_numbers(2, 5) == [0, 1, 2, 3, 4]


def test_scroll_boundaries_fade_and_do_not_intercept_clicks(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    for _ in range(10):
        add_history(dashboard)
    # The recent list now scrolls inside its card, so only a compact window overflows the page.
    dashboard.resize(920, 620)
    dashboard.refresh()
    flush_ui(qt_app)
    assert dashboard.home.bottom_fade.isVisible()
    assert not dashboard.home.top_fade.isVisible()
    assert dashboard.home.bottom_fade.testAttribute(Qt.WA_TransparentForMouseEvents)
    dashboard.home.verticalScrollBar().setValue(100)
    flush_ui(qt_app)
    assert dashboard.home.top_fade.isVisible()


def test_badge_and_packaged_ico_have_contrast_and_multiple_sizes(qt_app, tmp_path):
    import struct
    from PySide6.QtCore import QSize
    from flowwriter.icons import app_icon, write_app_ico

    for size in (16, 32, 256):
        image = app_icon().pixmap(QSize(size, size)).toImage()
        colors = [image.pixelColor(x, y) for x in range(size) for y in range(size)]
        assert any(c.alpha() > 200 and c.red() > 240 and 120 < c.green() < 210 for c in colors)
        assert any(c.alpha() > 200 and c.red() < 60 for c in colors)
    target = tmp_path / "app.ico"
    write_app_ico(target)
    data = target.read_bytes()
    assert struct.unpack_from("<HHH", data) == (0, 1, 7)
    assert b"\x89PNG\r\n\x1a\n" in data


def test_styles_keep_positive_point_sizes_and_emit_no_font_warning(dashboard, qt_app, capfd):
    from PySide6.QtWidgets import QWidget

    for index in range(7):
        dashboard.navigate(index)
        flush_ui(qt_app)
        dashboard.grab()
    for control in dashboard.findChildren(QWidget):
        assert control.font().pointSizeF() > 0, control.objectName()
    assert "QFont::setPointSize" not in capfd.readouterr().err


def test_disabled_replacement_cannot_be_invoked_through_shortcut(qt_app):
    from PySide6.QtTest import QSignalSpy
    from flowwriter.overlay import PreviewPopupCard

    preview = PreviewPopupCard()
    preview.show_result("Replacement")
    approved = QSignalSpy(preview.approved)
    preview.show_replace_failed()
    preview._on_primary()
    assert approved.count() == 0
    preview.show_replace_failed("Clipboard busy", retry=True)
    preview._on_primary()
    assert approved.at(0) == ["Replacement"]
    preview.hide()
    preview.deleteLater()
    flush_ui(qt_app)


def test_scroll_viewport_does_not_cover_rounded_workspace_corners(dashboard, qt_app):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QFrame

    flush_ui(qt_app)
    frame = dashboard.findChild(QFrame, "workspace")
    image = dashboard.grab().toImage()
    for point in (QPoint(1, 2), QPoint(1, frame.height() - 3)):
        position = frame.mapTo(dashboard, point)
        color = image.pixelColor(position)
        assert color.red() == color.green() == color.blue() == 245


def test_action_selection_has_no_focus_frame_and_keyboard_still_works(dashboard, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    dashboard.navigate(3)
    dashboard.action_list.setFocus()
    flush_ui(qt_app)
    option = QStyleOptionViewItem()
    option.state = QStyle.State_Enabled | QStyle.State_Selected | QStyle.State_HasFocus
    dashboard.action_list.itemDelegate().initStyleOption(option, dashboard.action_list.currentIndex())
    assert not option.state & QStyle.State_HasFocus
    assert option.state & QStyle.State_Selected
    previous = dashboard.action_list.currentRow()
    QTest.keyClick(dashboard.action_list, Qt.Key_Down)
    assert dashboard.action_list.currentRow() == previous + 1
    assert dashboard.action_name.text() == dashboard.action_list.currentItem().text()


def test_sidebar_focus_uses_background_instead_of_dark_border(dashboard, qt_app):
    dashboard.navigate(3)
    flush_ui(qt_app)
    control = dashboard.nav_buttons[3]
    image = control.grab().toImage()
    edge = image.pixelColor(0, image.height() // 2)
    assert edge.red() > 220 and edge.green() > 220 and edge.blue() > 220
    assert control.isChecked()


def test_details_dialog_is_readable_with_dark_system_palette(dashboard, qt_app):
    from PySide6.QtGui import QPalette, QColor
    from PySide6.QtWidgets import QPlainTextEdit
    from flowwriter.dashboard import HistoryDialog

    add_history(dashboard)
    previous = qt_app.palette()
    dark = QPalette(previous)
    dark.setColor(QPalette.Window, QColor("#202020"))
    dark.setColor(QPalette.WindowText, QColor("#EEEEEE"))
    qt_app.setPalette(dark)
    dialog = HistoryDialog(dashboard.store.recent()[0], dashboard)
    try:
        dialog.show()
        flush_ui(qt_app)
        assert dialog.grab().toImage().pixelColor(8, 8).lightness() > 240
        assert dialog.palette().color(QPalette.WindowText).lightness() < 60
        editors = dialog.findChildren(QPlainTextEdit)
        assert len(editors) == 2
        assert all(editor.isReadOnly() for editor in editors)
        assert {editor.toPlainText() for editor in editors} == {
            "A draft to revisit.", "<b>Keep this literal.</b> Your revised draft.",
        }
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_app.setPalette(previous)
        flush_ui(qt_app)


@pytest.mark.parametrize("answer,remaining", [("No", 1), ("Yes", 0)])
def test_themed_confirmation_keeps_yes_no_and_safe_default(dashboard, qt_app, answer, remaining):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPalette
    from flowwriter.dialogs import MessageBox

    add_history(dashboard)
    record = dashboard.store.recent()[0]
    observed = []
    def respond():
        dialog = qt_app.activeModalWidget()
        observed.append((isinstance(dialog, MessageBox), dialog.defaultButton() == dialog.button(MessageBox.No),
                         dialog.testOption(MessageBox.Option.DontUseNativeDialog),
                         dialog.palette().color(QPalette.Window).lightness(),
                         dialog.palette().color(QPalette.WindowText).lightness()))
        dialog.button(getattr(MessageBox, answer)).click()
    QTimer.singleShot(0, respond)
    dashboard.delete_history_row(record)
    assert observed == [(True, True, True, 255, 38)]
    assert len(dashboard.store.recent()) == remaining


def test_confirmation_escape_cancels(dashboard, qt_app):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from flowwriter.dialogs import MessageBox

    QTimer.singleShot(0, lambda: QTest.keyClick(qt_app.activeModalWidget(), Qt.Key_Escape))
    result = MessageBox.question(dashboard, "Delete entry", "Delete this history entry?",
                                 MessageBox.Yes | MessageBox.No, MessageBox.No)
    assert result == MessageBox.No


def test_parentless_information_and_warning_use_the_same_light_dialog(qt_app):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPalette
    from flowwriter.dialogs import MessageBox

    observed = []
    def respond():
        dialog = qt_app.activeModalWidget()
        observed.append((dialog.palette().color(QPalette.Window).lightness(), dialog.text()))
        dialog.button(MessageBox.Ok).click()
    for method in (MessageBox.information, MessageBox.warning):
        QTimer.singleShot(0, respond)
        assert method(None, "Message", "Literal <text> remains readable.") == MessageBox.Ok
    assert observed == [(255, "Literal <text> remains readable.")] * 2
