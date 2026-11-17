"""Native premium desktop dashboard, reusable action library and local history."""
from __future__ import annotations
from datetime import datetime, timedelta
import threading

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QObject
from PySide6.QtGui import QColor, QPainter, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QTextEdit, QLineEdit, QListWidget,
    QCheckBox, QStackedWidget, QSplitter, QKeySequenceEdit,
    QPlainTextEdit, QApplication, QBoxLayout, QSizePolicy,
)
from . import shortcuts
from .domain import Action, Provider, DEFAULT_EXCLUDED_TITLES, MAX_ACTIONS_PER_FACE, make_id, normalized_base_url
from .labels import METRIC_CAPTIONS, STATUS_ORDER, status_label, when, day_text, clock_text
from .styles import APP_STYLESHEET
from .icons import icon, app_icon, action_icon_name
from .dashboard_widgets import (FlowArtwork, RecentEntry, ReadableText, SelectField, SelectionDelegate,
                                label, surface, button, divider, icon_button, SoftScrollArea,
                                FeedScrollArea, Pager)
from .insights_ui import InsightsPanel
from .dialogs import LightDialog, MessageBox


def scroll_page():
    area = SoftScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.viewport().setAutoFillBackground(False)
    content = QWidget()
    content.setObjectName("page")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(36, 18, 36, 36)
    layout.setSpacing(24)
    layout.setAlignment(Qt.AlignTop)
    area.setWidget(content)
    return area, layout


def section_heading(title, sub=None):
    box = QVBoxLayout()
    box.setSpacing(3)
    box.addWidget(label(title, "h1"))
    if sub:
        box.addWidget(label(sub, "muted"))
    return box


def truncated(text, size=185):
    text = " ".join((text or "").split())
    return text[:size] + ("..." if len(text) > size else "")


time_text = when  # one date format everywhere (see labels.py)


class SearchEvents(QObject):
    """Results of the background history search, delivered on the interface thread."""
    progress = Signal(int, int, int)   # token, scanned, total
    found = Signal(int, object)        # token, ids or None when stopped


class ActivityBars(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(155)
        self.series = [0] * 7

    def set_series(self, values):
        self.series = values[:7]
        description = f"Last 7 days: {sum(self.series)} transformations. " + ", ".join(str(v) for v in self.series)
        self.setAccessibleName(description)
        self.setToolTip(description)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        labels = [(datetime.now().astimezone().date() - timedelta(days=d)).strftime("%a") for d in range(6, -1, -1)]
        mx = max(max(self.series, default=0), 1)
        gap = max(12, w / 8)
        bar_w = min(32, (w - gap * 2) / 13)
        for i, value in enumerate(self.series):
            x = gap + i * (w - 2 * gap) / 6
            ht = max(5, (h - 50) * value / mx)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E9E9E9"))
            p.drawRoundedRect(int(x-bar_w/2), 9, int(bar_w), int(h-50), 6, 6)
            if value:
                p.setBrush(QColor("#327A74"))
                p.drawRoundedRect(int(x-bar_w/2), int(h-41-ht), int(bar_w), int(ht), 6, 6)
            p.setPen(QColor("#736F67"))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(int(x-22), h-22, 44, 17, Qt.AlignCenter, labels[i])
        p.end()


class HistoryDialog(LightDialog):
    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Transformation details")
        self.resize(850, 610)
        self.record = record
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 22, 24, 22)
        main.setSpacing(15)
        header = QHBoxLayout()
        header.addWidget(label(record["action"], "h2"))
        header.addStretch()
        header.addWidget(label(status_label(record["status"]), "chip"))
        main.addLayout(header)
        main.addWidget(label(f"{time_text(record['created_at'])}   ·   {record['provider_name']} / {record['model']}", "muted"))
        parts = QSplitter(Qt.Horizontal)
        for title, text in (("ORIGINAL", record["input_text"]), ("TRANSFORMED", record["output_text"])):
            box = QWidget()
            layout = QVBoxLayout(box)
            layout.setContentsMargins(1, 1, 1, 1)
            layout.addWidget(label(title, "eyebrow"))
            edit = QPlainTextEdit()
            edit.setReadOnly(True)
            edit.setPlainText(text)
            layout.addWidget(edit, 1)
            parts.addWidget(box)
        main.addWidget(parts, 1)
        main.addWidget(label("Instruction: " + truncated(record["instruction"], 400), "muted", True))
        foot = QHBoxLayout()
        copy_btn = button("Copy transformed text", icon_name="copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(record["output_text"]))
        foot.addWidget(copy_btn)
        foot.addStretch()
        close_btn = button("Close", primary=True)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        main.addLayout(foot)


class MainWindow(QMainWindow):
    RECENT_PAGE_SIZE = 10
    RECENT_MAX_HEIGHT = 350
    scratchpad_requested = Signal(str, str, str)
    scratch_copied = Signal(str)
    provider_test_requested = Signal(object, str)
    action_changed = Signal()
    provider_changed = Signal()
    privacy_changed = Signal()
    shortcuts_changed = Signal()
    HISTORY_PAGE_SIZE = 10

    def __init__(self, store, vault):
        super().__init__()
        self.store, self.vault = store, vault
        self._provider_dirty = False
        self._history_page = 0
        self._history_ids = None          # ids of a text search, or None when browsing
        self._history_token = 0
        self._search_cancel = threading.Event()
        self.search_events = SearchEvents()
        self.search_events.progress.connect(self._search_progress)
        self.search_events.found.connect(self._search_found)
        self.setWindowTitle("FlowWriter Studio · Your writing workspace")
        self.setWindowIcon(app_icon())
        self.resize(1360, 880)
        self.setMinimumSize(920, 620)
        self.setStyleSheet(APP_STYLESHEET)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        wrapper = QHBoxLayout(root)
        wrapper.setContentsMargins(0, 14, 14, 14)
        wrapper.setSpacing(0)
        self._build_sidebar(wrapper)
        workspace = QFrame()
        workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(workspace)
        # Keep rectangular viewports wholly inside the workspace's rounded ends.
        workspace_layout.setContentsMargins(1, 26, 1, 26)
        self.pages = QStackedWidget()
        workspace_layout.addWidget(self.pages)
        wrapper.addWidget(workspace, 1)
        self.page_names = ["Overview", "History", "Scratchpad", "Actions", "Providers", "Privacy", "Insights", "Shortcuts"]
        self.home, self.home_layout = scroll_page()
        self.history, self.history_layout = scroll_page()
        self.scratchpad, self.scratch_layout = scroll_page()
        self.actionpage, self.actions_layout = scroll_page()
        self.providerspage, self.providers_layout = scroll_page()
        self.privacypage, self.privacy_layout = scroll_page()
        self.insights, self.insights_layout = scroll_page()
        self.shortcutspage, self.shortcuts_layout = scroll_page()
        self.insights_panel = InsightsPanel(self.store)
        self.insights_layout.addWidget(self.insights_panel)
        for page in (self.home, self.history, self.scratchpad, self.actionpage, self.providerspage,
                     self.privacypage, self.insights, self.shortcutspage):
            self.pages.addWidget(page)
        self._make_home()
        self._make_history()
        self._make_scratchpad()
        self._make_actions()
        self._make_providers()
        self._make_privacy()
        self._make_shortcuts()
        self.navigate(0)
        self.refresh()
        QTimer.singleShot(0, self._adapt_home)
        # A tray app can run for days: keep the date and the 7-day chart current.
        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    def showEvent(self, event):
        super().showEvent(event)
        if QApplication.platformName() == "windows":
            from .windows import apply_titlebar
            apply_titlebar(int(self.winId()))

    def _build_sidebar(self, parent):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 14)
        layout.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        mark = QLabel()
        mark.setPixmap(icon("brand").pixmap(QSize(30, 30), self.devicePixelRatioF()))
        brand.addWidget(mark)
        brand.addWidget(label("FlowWriter", "logo"), 1)
        layout.addLayout(brand)
        layout.addSpacing(24)
        self.nav_buttons = [None] * 8
        for icon_name, name, i in [
            ("overview", "Overview", 0), ("history", "History", 1), ("insights", "Insights", 6),
            ("edit", "Scratchpad", 2), ("actions", "Actions", 3),
            ("providers", "Providers", 4), ("shield", "Privacy", 5), ("keyboard", "Shortcuts", 7),
        ]:
            btn = button("  " + name, icon_name=icon_name)
            btn.setIconSize(QSize(21, 21))
            btn.setAccessibleName(name)
            btn.setCheckable(True)
            btn.setFixedHeight(38)
            btn.setObjectName("navButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, j=i: self.navigate(j))
            self.nav_buttons[i] = btn
            layout.addWidget(btn)
        layout.addStretch()
        card, box = surface(16)
        self.shortcut_card = card
        box.setSpacing(12)
        box.addWidget(label("A LITTLE SHORTCUT", "eyebrow"))
        box.addWidget(label("Great writing.\nOne selection away.", "h3", True))
        self.shortcut_hint = label(shortcuts.load(self.store).describe(), "muted", True)
        box.addWidget(self.shortcut_hint)
        layout.addWidget(card)
        layout.addSpacing(7)
        self.private_button = button("Private mode: Off", icon_name="lock")
        self.private_button.setCheckable(True)
        self.private_button.setAccessibleName("Private mode")
        self.private_button.clicked.connect(self.toggle_private)
        layout.addWidget(self.private_button)
        layout.addSpacing(8)
        layout.addWidget(label("FLOWWRITER STUDIO", "eyebrow"))
        parent.addWidget(sidebar)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setFocus(Qt.OtherFocusReason)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
            btn.setObjectName("navActive" if i == index else "navButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index in (0, 1):
            self.refresh()
        if index == 3:
            self.load_actions()
        if index == 4 and not self._provider_dirty:
            self.load_profiles()  # never throw away edits that are not saved yet
        if index == 5:
            self.load_privacy()
        if index == 6:
            self.insights_panel.refresh()
        if index == 7:
            self.load_shortcuts()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "shortcut_card"):
            self.shortcut_card.setVisible(self.height() >= 780)
        if hasattr(self, "home_columns"):
            self._adapt_home()
        if hasattr(self, "action_columns"):
            compact = self.width() < 1200
            self.action_columns.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
            self.action_list.setMaximumHeight(180 if compact else 16777215)

    def _adapt_home(self):
        # Stack the rail below the feed at compact desktop window sizes.
        wide = self.width() >= 1200
        self.home_columns.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        if wide:
            self.home_rail.setFixedWidth(268)
        else:
            self.home_rail.setMaximumWidth(16777215)
            self.home_rail.setMinimumWidth(0)
        self.hero_art.setVisible(self.width() >= 1050)

    def _make_home(self):
        heading = QHBoxLayout()
        heading.addLayout(section_heading("Welcome back.", "A little less effort. A lot more flow."))
        heading.addStretch()
        self.home_date = label("", "muted")
        heading.addWidget(self.home_date)
        self._update_date()
        self.home_layout.addLayout(heading)

        self.home_columns = QBoxLayout(QBoxLayout.LeftToRight)
        self.home_columns.setSpacing(26)
        left = QVBoxLayout()
        left.setSpacing(26)
        hero = QFrame()
        hero.setObjectName("hero")
        hbox = QHBoxLayout(hero)
        hbox.setContentsMargins(26, 20, 20, 20)
        text = QVBoxLayout()
        text.setSpacing(8)
        text.addWidget(label("A CLEARER WAY TO WRITE", "heroEyebrow"))
        text.addWidget(label("Good ideas. Better words.", "heroText", True))
        text.addWidget(label("Make your next sentence a great one.", "heroSub", True))
        text.addSpacing(5)
        self.start_writing = button("Start writing", icon_name="edit")
        self.start_writing.setObjectName("heroButton")
        self.start_writing.setMaximumWidth(155)
        self.start_writing.clicked.connect(lambda: self.navigate(2))
        text.addWidget(self.start_writing, 0, Qt.AlignLeft)
        hbox.addLayout(text, 1)
        self.hero_art = FlowArtwork()
        hbox.addWidget(self.hero_art)
        left.addWidget(hero)

        recent_heading = QHBoxLayout()
        recent_heading.addWidget(label("Recent transformations", "h2"))
        recent_heading.addStretch()
        see_all = button("View history", icon_name="arrow-up")
        see_all.setObjectName("textButton")
        see_all.clicked.connect(lambda: self.navigate(1))
        recent_heading.addWidget(see_all)
        left.addLayout(recent_heading)
        recent_card, rv = surface(8, muted=True)
        rv.setSpacing(4)
        # Empty state (built once, shown only when there is no saved history).
        self.home_empty = QWidget()
        content = QVBoxLayout(self.home_empty)
        content.setContentsMargins(22, 30, 22, 30)
        content.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(icon("edit", "#8B8067").pixmap(QSize(30, 30), self.devicePixelRatioF()))
        content.addWidget(mark)
        content.addWidget(label("Room for your next great idea.", "h2", True))
        content.addWidget(label("Start in Scratchpad or select text in any app. Your saved transformations will appear here.", "muted", True))
        start = button("Open Scratchpad", icon_name="arrow")
        start.clicked.connect(lambda: self.navigate(2))
        content.addWidget(start, 0, Qt.AlignLeft)
        rv.addWidget(self.home_empty)
        # Page of entries: scrolls inside the card when taller than RECENT_MAX_HEIGHT.
        self.recent_scroll = FeedScrollArea(max_height=self.RECENT_MAX_HEIGHT)
        self.recent_scroll.setAccessibleName("Recent transformations")
        recent_content = QWidget()
        recent_content.setObjectName("page")
        self.home_recent = QVBoxLayout(recent_content)
        self.home_recent.setContentsMargins(0, 0, 0, 0)
        self.home_recent.setSpacing(0)
        self.recent_scroll.setWidget(recent_content)
        rv.addWidget(self.recent_scroll)
        self.recent_pager = Pager()
        self.recent_pager.page_requested.connect(self.go_to_recent_page)
        rv.addWidget(self.recent_pager)
        self._recent_page = 0
        left.addWidget(recent_card)
        left.addStretch()
        self.home_columns.addLayout(left, 1)

        self.home_rail = QWidget()
        rail = QVBoxLayout(self.home_rail)
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(20)
        metrics, metric_box = surface(23, muted=True)
        metric_box.addWidget(label("YOUR WRITING AT A GLANCE", "eyebrow"))
        metric_box.addSpacing(8)
        self.metric_labels = {}
        for key, title in METRIC_CAPTIONS.items():
            row = QHBoxLayout()
            count = label("0", "bigMetric")
            self.metric_labels[key] = count
            row.addWidget(count)
            row.addSpacing(8)
            row.addWidget(label(title, "muted"), 1, Qt.AlignVCenter)
            metric_box.addLayout(row)
        metric_box.addSpacing(8)
        metric_box.addWidget(divider())
        metric_box.addSpacing(8)
        privacy_row = QHBoxLayout()
        shield = QLabel()
        shield.setPixmap(icon("shield", "#5E7358").pixmap(QSize(20, 20), self.devicePixelRatioF()))
        privacy_row.addWidget(shield)
        self.home_privacy_status = label("Encrypted local history", "h3", True)
        privacy_row.addWidget(self.home_privacy_status, 1)
        metric_box.addLayout(privacy_row)
        self.home_privacy_detail = label("Saved writing stays on this device. You choose your AI provider.", "muted", True)
        metric_box.addWidget(self.home_privacy_detail)
        rail.addWidget(metrics)

        activity, activity_box = surface(20)
        activity_box.addWidget(label("This week", "h2"))
        activity_box.addWidget(label("Transformations over the last 7 days", "muted", True))
        self.activity_chart = ActivityBars()
        activity_box.addWidget(self.activity_chart)
        rail.addWidget(activity)
        rail.addStretch()
        self.home_columns.addWidget(self.home_rail)
        self.home_layout.addLayout(self.home_columns)

    def _make_history(self):
        self.history_layout.addLayout(section_heading("History", "Find, revisit and reuse your past writing."))
        toolbar = QHBoxLayout()
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search text, actions, models...")
        self.history_search.addAction(icon("search", "#81796B"), QLineEdit.LeadingPosition)
        self.history_search.setClearButtonEnabled(True)
        self._history_search_timer = QTimer(self)
        self._history_search_timer.setSingleShot(True)
        self._history_search_timer.setInterval(250)
        self._history_search_timer.timeout.connect(self._history_query_changed)
        self.history_search.textChanged.connect(lambda _value: self._history_search_timer.start())
        toolbar.addWidget(self.history_search, 1)
        self.history_filter = SelectField()
        self.history_filter.addItem("All statuses", "All")
        for key in STATUS_ORDER:
            self.history_filter.addItem(status_label(key), key)
        self.history_filter.setAccessibleName("Filter by status")
        self.history_filter.currentIndexChanged.connect(lambda _index: self._history_query_changed())
        toolbar.addWidget(self.history_filter)
        self.history_layout.addLayout(toolbar)
        self.history_count = label("", "muted")
        self.history_layout.addWidget(self.history_count)
        self.history_cards = QVBoxLayout()
        self.history_cards.setSpacing(12)
        self.history_layout.addLayout(self.history_cards)
        self.history_pager = Pager()
        self.history_pager.page_requested.connect(self.go_to_history_page)
        self.history_layout.addWidget(self.history_pager)
        self.history_layout.addStretch()

    def _make_scratchpad(self):
        self.scratch_layout.addLayout(section_heading("Scratchpad", "Transform text without leaving your writing workspace."))
        top, v = surface(22)
        row = QHBoxLayout()
        row.addWidget(label("Action", "h3"))
        self.scratch_action = SelectField()
        self.scratch_action.setMinimumWidth(220)
        row.addWidget(self.scratch_action)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(label("Original text", "fieldLabel"))
        self.scratch_input = QTextEdit()
        self.scratch_input.setPlaceholderText("Paste or type the text you want to transform...")
        self.scratch_input.setMinimumHeight(165)
        v.addWidget(self.scratch_input)
        v.addWidget(label("Custom instruction (optional; replaces preset instruction)", "fieldLabel"))
        self.scratch_instruction = QLineEdit()
        self.scratch_instruction.setPlaceholderText("e.g. Make this more concise and formal")
        v.addWidget(self.scratch_instruction)
        go = button("Transform text", True, icon_name="sparkles")
        go.setMinimumHeight(43)
        go.clicked.connect(self.submit_scratchpad)
        v.addWidget(go)
        self.scratch_layout.addWidget(top)
        result, v = surface(22)
        title_row = QHBoxLayout()
        title_row.addWidget(label("AI result", "h2"))
        title_row.addStretch()
        self.scratch_state = label("Ready", "statusGood")
        title_row.addWidget(self.scratch_state)
        v.addLayout(title_row)
        self.scratch_result = QTextEdit()
        self.scratch_result.setPlaceholderText("Your transformed text will appear here. You can edit it before copying.")
        self.scratch_result.setMinimumHeight(200)
        v.addWidget(self.scratch_result)
        b = QHBoxLayout()
        copy = button("Copy result", icon_name="copy")
        copy.clicked.connect(self.copy_scratchpad_result)
        b.addWidget(copy)
        use = button("Use result as input", icon_name="reuse")
        use.clicked.connect(lambda: self.scratch_input.setPlainText(self.scratch_result.toPlainText()))
        b.addWidget(use)
        b.addStretch()
        v.addLayout(b)
        self.scratch_layout.addWidget(result)
        self.scratch_layout.addStretch()
        self.reload_scratch_actions()

    def _make_actions(self):
        self.actions_layout.addLayout(section_heading("Actions", "Customize the two-sided selection wheel and your prompts."))
        card, v = surface(22)
        row = QBoxLayout(QBoxLayout.LeftToRight)
        self.action_columns = row
        self.action_list = QListWidget()
        self.action_list.setItemDelegate(SelectionDelegate(self.action_list))
        self.action_list.setMinimumWidth(220)
        self.action_list.currentRowChanged.connect(self.action_selected)
        row.addWidget(self.action_list, 2)
        right = QVBoxLayout()
        right.addWidget(label("Action name", "fieldLabel"))
        self.action_name = QLineEdit()
        right.addWidget(self.action_name)
        right.addWidget(label("Instruction template", "fieldLabel"))
        self.action_prompt = QTextEdit()
        self.action_prompt.setMinimumHeight(185)
        right.addWidget(self.action_prompt)
        right.addWidget(label("Radial menu face", "fieldLabel"))
        self.action_face = SelectField()
        self.action_face.addItems(["Front", "Back"])
        right.addWidget(self.action_face)
        foot = QHBoxLayout()
        new = button("New action", icon_name="plus")
        new.clicked.connect(self.new_action)
        foot.addWidget(new)
        delete = button("Delete", icon_name="trash")
        delete.clicked.connect(self.delete_action)
        foot.addWidget(delete)
        foot.addStretch()
        save = button("Save action", True, icon_name="check")
        save.clicked.connect(self.save_action)
        foot.addWidget(save)
        right.addLayout(foot)
        row.addLayout(right, 5)
        v.addLayout(row)
        v.addWidget(label("Every action uses the active provider. The wheel switches faces using the scroll wheel.", "muted", True))
        self.actions_layout.addWidget(card)
        self.actions_layout.addStretch()
        self._actions_cache = []

    def _make_providers(self):
        self.providers_layout.addLayout(section_heading("Providers", "Bring any OpenAI-compatible API endpoint or a local model, such as Ollama."))
        card, v = surface(22)
        row = QHBoxLayout()
        row.addWidget(label("Saved provider", "h3"))
        self.provider_picker = SelectField()
        self.provider_picker.setMinimumWidth(240)
        self.provider_picker.setAccessibleName("Saved provider")
        self.provider_picker.currentIndexChanged.connect(self._provider_picked)
        row.addWidget(self.provider_picker)
        row.addStretch()
        new = button("Add provider", icon_name="plus")
        new.clicked.connect(self.new_profile)
        row.addWidget(new)
        v.addLayout(row)
        v.addSpacing(8)
        v.addWidget(label("Provider name", "fieldLabel"))
        self.provider_name = QLineEdit()
        v.addWidget(self.provider_name)
        v.addWidget(label("OpenAI-compatible API base URL", "fieldLabel"))
        self.provider_url = QLineEdit()
        self.provider_url.setPlaceholderText("https://api.example.com/v1")
        v.addWidget(self.provider_url)
        v.addWidget(label("Model identifier", "fieldLabel"))
        self.provider_model = QLineEdit()
        self.provider_model.setPlaceholderText("Any model ID your endpoint accepts")
        v.addWidget(self.provider_model)
        v.addWidget(label("API key (if required)", "fieldLabel"))
        keyrow = QHBoxLayout()
        self.provider_key = QLineEdit()
        self.provider_key.setEchoMode(QLineEdit.Password)
        self.provider_key.setPlaceholderText("Stored in the operating system keychain")
        keyrow.addWidget(self.provider_key, 1)
        self.provider_show_key = QCheckBox("Show")
        self.provider_show_key.toggled.connect(self._show_key_toggled)
        keyrow.addWidget(self.provider_show_key)
        self.remove_key_button = button("Remove saved key", icon_name="trash")
        self.remove_key_button.clicked.connect(self.remove_saved_key)
        keyrow.addWidget(self.remove_key_button)
        v.addLayout(keyrow)
        self.provider_stream = QCheckBox("Show the reply as it is written (streaming)")
        self.provider_stream.setChecked(True)
        v.addWidget(self.provider_stream)
        v.addWidget(label("Keys are never stored in SQLite. HTTP endpoints on the LAN support keyless local models; API keys require HTTPS or localhost.", "muted", True))
        for edit in (self.provider_name, self.provider_url, self.provider_model, self.provider_key):
            edit.textEdited.connect(self._mark_provider_dirty)
        self.provider_stream.clicked.connect(self._mark_provider_dirty)
        foot = QHBoxLayout()
        self.test_button = button("Test connection", icon_name="providers")
        self.test_button.clicked.connect(self.test_profile)
        foot.addWidget(self.test_button)
        delete = button("Delete provider", icon_name="trash")
        delete.clicked.connect(self.delete_profile)
        foot.addWidget(delete)
        foot.addStretch()
        save = button("Save and activate", True, icon_name="check")
        save.clicked.connect(self.save_profile)
        foot.addWidget(save)
        v.addLayout(foot)
        self.provider_status = label("", "muted", True)
        v.addWidget(self.provider_status)
        self.providers_layout.addWidget(card)
        self.providers_layout.addStretch()
        self._profiles_cache = []
        self._profile_id = ""
        self._key_shown_from_vault = False

    def _make_privacy(self):
        self.privacy_layout.addLayout(section_heading("Privacy", "You control what is stored and when the assistant is active."))
        card, v = surface(23)
        v.addWidget(label("Local history", "h2"))
        self.history_enabled = QCheckBox("Save transformation history")
        self.history_enabled.toggled.connect(lambda enabled: self._privacy_set("save_history", enabled))
        v.addWidget(self.history_enabled)
        self.private_toggle = QCheckBox("Private mode — never save new transformations")
        self.private_toggle.toggled.connect(lambda enabled: self._privacy_set("private_mode", enabled))
        v.addWidget(self.private_toggle)
        self.privacy_encryption = label("", "muted", True)
        v.addWidget(self.privacy_encryption)
        v.addWidget(label("Excluded window titles (comma-separated)", "fieldLabel"))
        exclude_row = QHBoxLayout()
        self.excluded_titles = QLineEdit()
        self.excluded_titles.setPlaceholderText("e.g. Password manager, Banking Portal")
        exclude_row.addWidget(self.excluded_titles, 1)
        save_excludes = button("Save exclusions")
        save_excludes.clicked.connect(self.save_exclusions)
        exclude_row.addWidget(save_excludes)
        v.addLayout(exclude_row)
        v.addWidget(label("Selection capture is skipped when a source window title contains one of these phrases. Common password managers are listed until you change this. It is not a guarantee against sensitive fields in other apps.", "muted", True))
        v.addWidget(label("Storage location", "fieldLabel"))
        v.addWidget(label(str(self.store.path), "muted", True))
        self.privacy_layout.addWidget(card)
        delete_card, p = surface(23)
        p.addWidget(label("Delete history", "h2"))
        p.addWidget(label("Remove all saved transformations on this device. This action cannot be undone.", "muted", True))
        clear = button("Delete all history", icon_name="trash")
        clear.clicked.connect(self.clear_history)
        clear.setMaximumWidth(185)
        p.addWidget(clear)
        self.privacy_layout.addWidget(delete_card)
        self.privacy_layout.addStretch()

    def _make_shortcuts(self):
        self.shortcuts_layout.addLayout(section_heading("Shortcuts", "Choose how you open the action wheel on selected text."))
        card, v = surface(23)
        v.addWidget(label("Open the action wheel", "h2"))
        v.addWidget(label("Hold keys and drag-select text", "fieldLabel"))
        self.drag_choice = SelectField()
        self.drag_choice.setAccessibleName("Hold keys and drag-select text")
        for text, mods in shortcuts.drag_choices():
            self.drag_choice.addItem(text, "+".join(sorted(mods)))
        self.drag_choice.setMaximumWidth(260)
        v.addWidget(self.drag_choice)
        v.addWidget(label("Pick keys other apps do not use with the mouse. Alt + drag selects columns in many editors.", "muted", True))
        v.addSpacing(6)
        v.addWidget(label("Global shortcut (select text first, then press it)", "fieldLabel"))
        row = QHBoxLayout()
        self.hotkey_edit = QKeySequenceEdit()
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setAccessibleName("Global shortcut")
        self.hotkey_edit.setMaximumWidth(260)
        row.addWidget(self.hotkey_edit)
        turn_off = button("Turn off")
        turn_off.clicked.connect(self.hotkey_edit.clear)
        row.addWidget(turn_off)
        row.addStretch()
        v.addLayout(row)
        v.addWidget(label("Click the box, then press the keys you want. Use two modifier keys (for example Ctrl + Alt) with a letter, number or Space, or one modifier with an F key.", "muted", True))
        v.addSpacing(6)
        self.skip_special = QCheckBox("Do not open in terminals, file managers or on the desktop")
        v.addWidget(self.skip_special)
        self._shortcut_error = ""
        # Every change is saved as soon as it is made, so nothing is lost by forgetting "Save shortcuts".
        self.hotkey_edit.editingFinished.connect(lambda: self.save_shortcuts(auto=True))
        self.drag_choice.currentIndexChanged.connect(lambda _i: self.save_shortcuts(auto=True))
        self.skip_special.toggled.connect(lambda _on: self.save_shortcuts(auto=True))
        v.addWidget(label("The app copies your selection with Ctrl + C (Cmd + C on a Mac). In a terminal that stops the running program, and in a file manager it copies files.", "muted", True))
        v.addSpacing(8)
        foot = QHBoxLayout()
        reset = button("Reset to defaults")
        reset.clicked.connect(self.reset_shortcuts)
        foot.addWidget(reset)
        foot.addStretch()
        save = button("Save shortcuts", True, icon_name="check")
        save.clicked.connect(self.save_shortcuts)
        foot.addWidget(save)
        v.addLayout(foot)
        self.shortcut_status = label("", "muted", True)
        v.addWidget(self.shortcut_status)
        v.addWidget(label("Changes apply straight away. Esc closes the wheel. On a Mac, allow Accessibility access for mouse and key shortcuts.", "muted", True))
        self.shortcuts_layout.addWidget(card)
        self.shortcuts_layout.addStretch()

    def _shortcut_hint_text(self, value):
        if self._shortcut_error:
            return "Your global shortcut is not active. Open Shortcuts to choose another."
        return value.describe()

    def load_shortcuts(self, value=None):
        value = value or shortcuts.load(self.store)
        widgets = (self.drag_choice, self.hotkey_edit, self.skip_special)
        for widget in widgets:
            widget.blockSignals(True)          # filling the form is not a user change
        index = self.drag_choice.findData("+".join(sorted(value.drag)))
        self.drag_choice.setCurrentIndex(max(index, 0))
        self.hotkey_edit.setKeySequence(QKeySequence(value.hotkey))
        self.skip_special.setChecked(value.skip_special_windows)
        for widget in widgets:
            widget.blockSignals(False)
        self.shortcut_status.setText(self._shortcut_error or value.describe())
        self.shortcut_hint.setText(self._shortcut_hint_text(value))

    def show_shortcut_status(self, text, ok=True):
        """Show the result of applying shortcuts. A failure stays visible until the next successful apply."""
        self._shortcut_error = "" if ok else text
        self.shortcut_status.setText(text)
        self.shortcut_hint.setText(self._shortcut_hint_text(shortcuts.load(self.store)))
        if not ok:
            self.statusBar().showMessage(text, 8000)

    def save_shortcuts(self, auto=False):
        text = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        try:
            hotkey = shortcuts.validate_hotkey(text) if text else ""
        except ValueError as exc:
            self.shortcut_status.setText(str(exc))
            MessageBox.warning(self, "Shortcut not saved", str(exc))
            if not auto:
                return
            # An automatic save keeps the other changes and puts the last good key back in the box.
            hotkey = shortcuts.load(self.store).hotkey
            self.hotkey_edit.blockSignals(True)
            self.hotkey_edit.setKeySequence(QKeySequence(hotkey))
            self.hotkey_edit.blockSignals(False)
        value = shortcuts.Shortcuts(
            frozenset(m for m in (self.drag_choice.currentData() or "").split("+") if m),
            hotkey,
            self.skip_special.isChecked(),
        )
        shortcuts.save(self.store, value)
        self.show_shortcut_status(value.describe())
        self.shortcuts_changed.emit()  # the controller may replace the status with a registration error

    def reset_shortcuts(self):
        self.load_shortcuts(shortcuts.Shortcuts())
        self.save_shortcuts()

    def load_privacy(self):
        for item, key in ((self.history_enabled, "save_history"), (self.private_toggle, "private_mode")):
            item.blockSignals(True)
            item.setChecked(self.store.get_pref(key, "true" if key == "save_history" else "false") == "true")
            item.blockSignals(False)
        self.privacy_encryption.setText(
            "History content is encrypted; the encryption key is kept in your OS keychain."
            if self.store.cipher else
            "The system keychain is unavailable. History saving is paused to avoid storing private text unencrypted."
        )
        self._show_private_state(self.private_toggle.isChecked())
        if hasattr(self, "home_privacy_status"):
            private = self.private_toggle.isChecked()
            saving = self.history_enabled.isChecked()
            self.home_privacy_status.setText(
                "Private mode is on" if private else
                "History saving is paused" if not saving or not self.store.cipher else
                "Encrypted local history"
            )
            self.home_privacy_detail.setText(
                "New transformations are not saved on this device."
                if private or not saving or not self.store.cipher else
                "Saved writing stays on this device. You choose your AI provider."
            )
        self.excluded_titles.setText(self.store.get_pref("excluded_titles", DEFAULT_EXCLUDED_TITLES))

    def _privacy_set(self, key, enabled):
        self.store.set_pref(key, "true" if enabled else "false")
        self.load_privacy()
        self.privacy_changed.emit()
        if self.pages.currentIndex() == 6:
            self.insights_panel.refresh()

    def _show_private_state(self, on):
        """The sidebar switch reads as a switch: filled and amber when on."""
        self.private_button.setChecked(on)
        self.private_button.setText("Private mode: " + ("On" if on else "Off"))
        self.private_button.setIcon(icon("lock", "#28241D" if on else "#262626"))
        self.private_button.setObjectName("privateOn" if on else "")
        self.private_button.style().unpolish(self.private_button)
        self.private_button.style().polish(self.private_button)

    def save_exclusions(self):
        self.store.set_pref("excluded_titles", self.excluded_titles.text().strip())
        MessageBox.information(self, "Exclusions saved", "These window titles will be ignored during selection capture.")

    def toggle_private(self):
        self._privacy_set("private_mode", self.store.get_pref("private_mode") != "true")
        self.load_privacy()

    def clear_history(self):
        answer = MessageBox.question(self, "Delete all history", "Permanently remove all saved transformation history?", MessageBox.Yes | MessageBox.No, MessageBox.No)
        if answer != MessageBox.Yes:
            return
        self.store.clear_history()
        self.refresh()

    def reload_scratch_actions(self):
        previous = self.scratch_action.currentData()
        self.scratch_action.clear()
        for action in self.store.actions():
            self.scratch_action.addItem(action.name, action.id)
        ix = self.scratch_action.findData(previous)
        self.scratch_action.setCurrentIndex(max(ix, 0))

    def submit_scratchpad(self):
        text = self.scratch_input.toPlainText()
        if not text.strip():
            MessageBox.information(self, "No text", "Enter some text to transform first.")
            return
        action_id = self.scratch_action.currentData()
        action = next((a for a in self.store.actions() if a.id == action_id), None)
        if action is None:
            return
        instruction = self.scratch_instruction.text().strip() or action.prompt
        self._set_scratch_state("Working…", "statusWarn")
        self.scratchpad_requested.emit(text, action.name, instruction)

    def copy_scratchpad_result(self):
        text = self.scratch_result.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.scratch_copied.emit(text)

    def scratch_thinking(self):
        if not self.scratch_result.toPlainText():
            self._set_scratch_state("Thinking…", "statusWarn")

    def scratch_progress(self, text):
        self.scratch_result.setPlainText(text)
        bar = self.scratch_result.verticalScrollBar()
        bar.setValue(bar.maximum())  # follow the newest words
        self._set_scratch_state("Writing…", "statusWarn")

    def scratch_complete(self, text):
        self.scratch_result.setPlainText(text)
        self._set_scratch_state("Done", "statusGood")
        self.refresh()

    def scratch_error(self, message):
        self._set_scratch_state("Error", "statusError")
        MessageBox.warning(self, "Transformation failed", message)

    def _set_scratch_state(self, text, style):
        self.scratch_state.setText(text)
        self.scratch_state.setObjectName(style)
        self.scratch_state.style().unpolish(self.scratch_state)
        self.scratch_state.style().polish(self.scratch_state)

    def load_actions(self):
        self._actions_cache = self.store.actions()
        self.action_list.blockSignals(True)
        oldid = self.action_list.currentItem().data(Qt.UserRole) if self.action_list.currentItem() else ""
        self.action_list.clear()
        selected_idx = 0
        for i, item in enumerate(self._actions_cache):
            from PySide6.QtWidgets import QListWidgetItem
            entry = QListWidgetItem(icon(action_icon_name(item.name)), item.name)
            entry.setData(Qt.UserRole, item.id)
            self.action_list.addItem(entry)
            if item.id == oldid:
                selected_idx = i
        self.action_list.blockSignals(False)
        if self._actions_cache:
            self.action_list.setCurrentRow(selected_idx)
        self.reload_scratch_actions()

    def action_selected(self, index):
        if 0 <= index < len(self._actions_cache):
            item = self._actions_cache[index]
            self.action_name.setText(item.name)
            self.action_prompt.setPlainText(item.prompt)
            self.action_face.setCurrentIndex(item.face)

    def new_action(self):
        self.action_list.clearSelection()
        self.action_list.setCurrentRow(-1)
        self.action_name.clear()
        self.action_prompt.clear()
        self.action_face.setCurrentIndex(0)
        self.action_name.setFocus()

    def save_action(self):
        name = self.action_name.text().strip()
        prompt = self.action_prompt.toPlainText().strip()
        if not name or not prompt:
            MessageBox.warning(self, "Invalid action", "Action name and instruction are required.")
            return
        index = self.action_list.currentRow()
        action_id = self._actions_cache[index].id if 0 <= index < len(self._actions_cache) else make_id()
        face = self.action_face.currentIndex()
        count = len([a for a in self.store.actions() if a.face == face and a.id != action_id])
        if count >= MAX_ACTIONS_PER_FACE:
            MessageBox.warning(self, "Action limit", f"Each radial face supports {MAX_ACTIONS_PER_FACE} actions. Move or delete another action first.")
            return
        old = next((a for a in self._actions_cache if a.id == action_id), None)
        position = old.position if old and old.face == face else count
        self.store.save_action(Action(action_id, name, prompt, face, position))
        self.load_actions()
        self.action_changed.emit()

    def delete_action(self):
        index = self.action_list.currentRow()
        if not (0 <= index < len(self._actions_cache)):
            return
        item = self._actions_cache[index]
        if MessageBox.question(self, "Delete action", f"Delete '{item.name}'?", MessageBox.Yes | MessageBox.No, MessageBox.No) != MessageBox.Yes:
            return
        self.store.delete_action(item.id)
        self.load_actions()
        self.action_changed.emit()

    def load_profiles(self):
        self._profiles_cache = self.store.profiles()
        self.provider_picker.blockSignals(True)
        self.provider_picker.clear()
        for p in self._profiles_cache:
            self.provider_picker.addItem(p.name, p.id)
        ix = self.provider_picker.findData(self._profile_id or self.store.get_pref("active_profile"))
        self.provider_picker.setCurrentIndex(max(ix, 0))
        self.provider_picker.blockSignals(False)
        self.profile_selected(self.provider_picker.currentIndex())

    def _mark_provider_dirty(self, *_):
        self._provider_dirty = True

    def _confirm_discard(self) -> bool:
        if not self._provider_dirty:
            return True
        return MessageBox.question(
            self, "Unsaved changes", "Discard the changes you made to this provider?",
            MessageBox.Yes | MessageBox.No, MessageBox.No) == MessageBox.Yes

    def _provider_picked(self, index):
        """The user chose another saved provider; do not silently drop unsaved edits."""
        if not self._confirm_discard():
            self.provider_picker.blockSignals(True)
            self.provider_picker.setCurrentIndex(max(self.provider_picker.findData(self._profile_id), 0))
            self.provider_picker.blockSignals(False)
            return
        self.profile_selected(index)

    def _show_key_toggled(self, checked):
        self.provider_key.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        if checked and not self.provider_key.text() and self._profile_id:
            # The saved key is read only when the user asks to see it.
            self.provider_key.setText(self.vault.get("provider-" + self._profile_id))
            self._key_shown_from_vault = True
        elif not checked and self._key_shown_from_vault:
            self.provider_key.clear()
            self._key_shown_from_vault = False

    def _refresh_key_controls(self):
        saved = bool(self._profile_id and self.vault.get("provider-" + self._profile_id))
        self.provider_key.setPlaceholderText(
            "A key is saved in the keychain. Leave empty to keep it." if saved
            else "Stored in the operating system keychain")
        self.remove_key_button.setVisible(saved)

    def remove_saved_key(self):
        if not self._profile_id:
            return
        if MessageBox.question(self, "Remove saved key", "Remove the saved API key for this provider?",
                               MessageBox.Yes | MessageBox.No, MessageBox.No) != MessageBox.Yes:
            return
        self.vault.remove("provider-" + self._profile_id)
        self.provider_key.clear()
        self._key_shown_from_vault = False
        self._refresh_key_controls()
        self.provider_status.setText("Saved key removed.")

    def profile_selected(self, index):
        if not (0 <= index < len(self._profiles_cache)):
            return
        p = self._profiles_cache[index]
        self._profile_id = p.id
        self.provider_name.setText(p.name)
        self.provider_url.setText(p.base_url)
        self.provider_model.setText(p.model)
        self.provider_key.clear()          # the saved key stays in the keychain until asked for
        self._key_shown_from_vault = False
        self.provider_show_key.blockSignals(True)
        self.provider_show_key.setChecked(False)
        self.provider_show_key.blockSignals(False)
        self.provider_key.setEchoMode(QLineEdit.Password)
        self.provider_stream.setChecked(p.stream)
        self._refresh_key_controls()
        self._provider_dirty = False
        self.provider_status.setText("Active" if p.id == self.store.get_pref("active_profile") else "Saved provider")

    def new_profile(self):
        if not self._confirm_discard():
            return
        self._profile_id = ""
        self.provider_picker.blockSignals(True)
        self.provider_picker.setCurrentIndex(-1)
        self.provider_picker.blockSignals(False)
        self.provider_name.clear()
        self.provider_url.setText("https://api.example.com/v1")
        self.provider_model.clear()
        self.provider_key.clear()
        self._key_shown_from_vault = False
        self.provider_stream.setChecked(True)
        self._refresh_key_controls()
        self._provider_dirty = False
        self.provider_status.setText("New provider")

    def _form_profile(self):
        name = self.provider_name.text().strip()
        model = self.provider_model.text().strip()
        if not name or not model:
            raise ValueError("Enter a provider name and a model identifier.")
        return Provider(self._profile_id or make_id(), name, normalized_base_url(self.provider_url.text()), model, self.provider_stream.isChecked())

    def save_profile(self):
        try:
            p = self._form_profile()
            from .domain import permits_key_transport
            typed = self.provider_key.text().strip()
            key = typed or (self.vault.get("provider-" + p.id) if self._profile_id else "")
            if key and not permits_key_transport(p.base_url):
                raise ValueError("API keys require HTTPS or a localhost URL. Keyless LAN models may use HTTP.")
            persisted = True
            if typed:  # an empty box keeps the saved key; use Remove saved key to delete it
                persisted = self.vault.put("provider-" + p.id, typed)
            self.store.save_profile(p)
            self.store.set_pref("active_profile", p.id)
            self._profile_id = p.id
            self._provider_dirty = False
            self.load_profiles()
            self.provider_changed.emit()
            self.provider_status.setText("Saved & active." + (" API key is session-only (keychain unavailable)." if typed and not persisted else ""))
        except ValueError as exc:
            MessageBox.warning(self, "Invalid configuration", str(exc))

    def delete_profile(self):
        if not self._profile_id:
            return
        if MessageBox.question(self, "Delete provider", "Remove this provider and its saved key?", MessageBox.Yes | MessageBox.No, MessageBox.No) != MessageBox.Yes:
            return
        try:
            self.store.delete_profile(self._profile_id)
        except ValueError as exc:
            MessageBox.warning(self, "Cannot delete", str(exc))
            return
        self.vault.remove("provider-" + self._profile_id)
        self._profile_id = ""
        self._provider_dirty = False
        self.load_profiles()
        self.provider_changed.emit()

    def test_profile(self):
        try:
            p = self._form_profile()
            key = self.provider_key.text().strip() or (self.vault.get("provider-" + self._profile_id) if self._profile_id else "")
            self.provider_status.setText("Testing connection...")
            self.test_button.setEnabled(False)
            self.provider_test_requested.emit(p, key)
        except ValueError as exc:
            MessageBox.warning(self, "Invalid configuration", str(exc))

    def test_finished(self, message, ok):
        self.test_button.setEnabled(True)
        self.provider_status.setText(message)
        if not ok:
            MessageBox.warning(self, "Connection test failed", message)

    def _update_date(self) -> bool:
        text = datetime.now().strftime("%B %d, %Y")
        changed = text != self.home_date.text()
        if changed:
            self.home_date.setText(text)
        return changed

    def _tick(self):
        if self._update_date():  # midnight passed: relabel rows ("Today" -> "Yesterday") and the chart
            self.refresh()

    def refresh(self):
        self.load_privacy()
        self._update_date()
        stats = self.store.stats()
        for k, widget in self.metric_labels.items():
            widget.setText(f"{stats[k]:,}")
        self._load_recent_page(stats["total"])
        counts = self.store.daily_counts(7)  # timestamps only: nothing is decrypted for the chart
        today = datetime.now().astimezone().date()
        self.activity_chart.set_series([counts.get(today - timedelta(days=d), 0) for d in range(6, -1, -1)])
        # History is read only while it is on screen; navigating to it refreshes it.
        if self.pages.currentIndex() == 1:
            self.refresh_history()
        if self.pages.currentIndex() == 6:
            self.insights_panel.refresh()

    def go_to_recent_page(self, page):
        self._recent_page = max(0, int(page))
        self._load_recent_page(self.store.history_count())
        self.recent_scroll.verticalScrollBar().setValue(0)

    def _load_recent_page(self, total):
        """Show one numbered page of recent transformations, newest first."""
        size = self.RECENT_PAGE_SIZE
        page_count = max(1, -(-total // size))
        # A delete or a clear can leave the current page past the end.
        self._recent_page = min(self._recent_page, page_count - 1)
        records = self.store.history_page(limit=size, offset=self._recent_page * size) if total else []
        self._clear_layout(self.home_recent)
        for i, r in enumerate(records):
            if i:
                self.home_recent.addWidget(divider())
            entry = RecentEntry(r, f"{day_text(r['created_at'])}\n{clock_text(r['created_at'])}")
            entry.setToolTip(time_text(r["created_at"]))
            entry.opened.connect(lambda row=r: HistoryDialog(row, self).exec())
            entry.copied.connect(lambda row=r: QApplication.clipboard().setText(row["output_text"]))
            self.home_recent.addWidget(entry)
        self.home_empty.setVisible(not records)
        self.recent_scroll.setVisible(bool(records))
        first = self._recent_page * size + 1
        self.recent_pager.set_state(self._recent_page, page_count, first, first + len(records) - 1, total)
        self.recent_scroll.fit()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                MainWindow._clear_layout(item.layout())

    # -- history: numbered pages, filters in SQL, text search on a background thread ------
    def _history_filters(self):
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        status = (self.history_filter.currentData() or "All") if hasattr(self, "history_filter") else "All"
        return query, status

    def _history_query_changed(self):
        self._history_page = 0
        self.refresh_history()

    def refresh_history(self):
        if not hasattr(self, "history_search"):
            return
        query, status = self._history_filters()
        self._search_cancel.set()  # stop an older scan that is still running
        if not query:
            self._history_ids = None
            self._show_history_page()
            return
        self._history_token += 1
        token, cancel = self._history_token, threading.Event()
        self._search_cancel = cancel
        self.history_count.setText("Searching…")

        def work():
            try:
                ids = self.store.search_history_ids(
                    query, status, cancel, lambda done, total: self.search_events.progress.emit(token, done, total))
            except Exception:  # the store may have closed while quitting
                ids = None
            self.search_events.found.emit(token, ids)

        threading.Thread(target=work, name="flowwriter-history-search", daemon=True).start()

    def _search_progress(self, token, done, total):
        if token == self._history_token and total:
            self.history_count.setText(f"Searching… {done:,} of {total:,} entries")

    def _search_found(self, token, ids):
        if token != self._history_token or ids is None:
            return
        self._history_ids = ids
        self._show_history_page()

    def go_to_history_page(self, page):
        self._history_page = max(0, int(page))
        self._show_history_page()
        self.history.verticalScrollBar().setValue(0)

    def _show_history_page(self):
        size = self.HISTORY_PAGE_SIZE
        _query, status = self._history_filters()
        searching = self._history_ids is not None
        total = len(self._history_ids) if searching else self.store.history_count(status)
        page_count = max(1, -(-total // size))
        self._history_page = min(self._history_page, page_count - 1)
        start = self._history_page * size
        if searching:
            records = self.store.history_rows(self._history_ids[start:start + size])
        else:
            records = self.store.history_page(limit=size, offset=start, status=status) if total else []
        self._render_history(records, total, page_count, start)

    def _render_history(self, records, total, page_count, start):
        searching = self._history_ids is not None
        self._clear_layout(self.history_cards)
        self.history_count.setText(f"{total:,} " + ("matching entries" if searching else "saved entries"))
        if not records:
            self.history_cards.addWidget(label("No matching records. Your future transformations will appear here.", "muted", True))
        for record in records:
            card, v = surface(17)
            heading = QHBoxLayout()
            heading.addWidget(label(record["action"], "h3", True))
            heading.addWidget(label(status_label(record["status"]), "chip"))
            heading.addStretch()
            heading.addWidget(label(time_text(record["created_at"]), "muted"))
            v.addLayout(heading)
            excerpt = ReadableText(truncated(record["output_text"] or record["input_text"], 300))
            excerpt.setObjectName("body")
            v.addWidget(excerpt)
            footer = QHBoxLayout()
            source = label(truncated(record["source_app"], 55), "muted", True)
            source.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            footer.addWidget(source, 1)
            footer.addStretch()
            inspect = button("View", icon_name="arrow-up")
            inspect.clicked.connect(lambda checked=False, r=record: HistoryDialog(r, self).exec())
            footer.addWidget(inspect)
            reuse = button("Reuse", icon_name="reuse")
            reuse.clicked.connect(lambda checked=False, r=record: self.reuse_history(r))
            footer.addWidget(reuse)
            copy = button("Copy", icon_name="copy")
            copy.clicked.connect(lambda checked=False, r=record: QApplication.clipboard().setText(r["output_text"]))
            footer.addWidget(copy)
            star = icon_button("star-filled" if record["is_favorite"] else "star", "Remove from favorites" if record["is_favorite"] else "Add to favorites")
            star.setCheckable(True)
            star.setChecked(bool(record["is_favorite"]))
            star.clicked.connect(lambda checked=False, r=record: self.toggle_favorite(r))
            footer.addWidget(star)
            delete = icon_button("trash", "Delete this history entry")
            delete.clicked.connect(lambda checked=False, r=record: self.delete_history_row(r))
            footer.addWidget(delete)
            v.addLayout(footer)
            self.history_cards.addWidget(card)
        self.history_pager.set_state(self._history_page, page_count, start + 1, start + len(records), total)

    def toggle_favorite(self, record):
        self.store.favorite(record["id"], not record["is_favorite"])
        self.refresh()

    def delete_history_row(self, record):
        if MessageBox.question(self, "Delete entry", "Delete this history entry?", MessageBox.Yes | MessageBox.No, MessageBox.No) == MessageBox.Yes:
            self.store.delete_history(record["id"])
            self.refresh()

    def reuse_history(self, record):
        self.navigate(2)
        self.scratch_input.setPlainText(record["input_text"])
        self.scratch_instruction.setText(record["instruction"])
        index = self.scratch_action.findText(record["action"])
        if index >= 0:
            self.scratch_action.setCurrentIndex(index)
        self.scratch_input.setFocus()

    def closeEvent(self, event):
        # Windows asks every window to close when it shuts down or signs out. Refusing
        # would make it wait for this app, so let that close through.
        app = QGuiApplication.instance()
        if app is not None and app.isSavingSession():
            event.accept()
            return
        # Otherwise remain available in the system tray.
        self.hide()
        event.ignore()
