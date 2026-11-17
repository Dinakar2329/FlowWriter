"""Native usage dashboard over existing saved history; no network requests."""
from __future__ import annotations

from datetime import date, timedelta
import sqlite3

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QTabBar, QStackedWidget,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyle,
)

from .dashboard_widgets import label, surface, button, divider
from .insights import UsageSummary, ranked_counts
from .sources_ui import SourcesCard


class RankedUsage(QWidget):
    """Directly labeled composition bars; the labels also work without color."""

    def __init__(self):
        super().__init__()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)

    def set_counts(self, counts):
        while self.body.count():
            self.body.takeAt(0).widget().deleteLater()
        total = sum(counts.values())
        if not total:
            self.body.addWidget(label("Your saved activity will appear here.", "muted", True))
            return
        for name, count in ranked_counts(counts):
            row = QWidget()
            content = QVBoxLayout(row)
            content.setContentsMargins(0, 0, 0, 0)
            content.setSpacing(7)
            heading = QHBoxLayout()
            title = label(name[:38] + ("…" if len(name) > 38 else ""), wrap=True)
            title.setToolTip(name)
            title.setAccessibleName(name)
            heading.addWidget(title, 1)
            heading.addWidget(label(f"{count:,} · {count / total:.0%}", "muted"))
            content.addLayout(heading)
            bar = QProgressBar()
            bar.setObjectName("usageBar")
            bar.setRange(0, total)
            bar.setValue(count)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setAccessibleName(f"{name}: {count} of {total} transformations")
            content.addWidget(bar)
            self.body.addWidget(row)


class CalendarCell(QStyledItemDelegate):
    """Paint heat colors explicitly while retaining Qt's accessible table model."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        brush = index.data(Qt.BackgroundRole)
        painter.setBrush(brush if brush is not None else QColor("#E9E9E7"))
        selected = option.state & QStyle.State_Selected
        painter.setPen(QPen(QColor("#262626"), 2) if selected else Qt.NoPen)
        painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 2, 2)
        painter.restore()


class ActivityCalendar(QWidget):
    """26 weeks of daily counts, with native keyboard and accessible cell names."""

    COLORS = ("#E9E9E7", "#CCE5E1", "#9BCEC6", "#559E94", "#216D68")

    def __init__(self):
        super().__init__()
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self.range_label = label("", "muted")
        body.addWidget(self.range_label)
        self.grid = QTableWidget(7, 26)
        self.grid.setObjectName("calendar")
        self.grid.setItemDelegate(CalendarCell(self.grid))
        self.grid.horizontalHeader().hide()
        self.grid.verticalHeader().hide()
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grid.horizontalHeader().setMinimumSectionSize(8)
        self.grid.verticalHeader().setMinimumSectionSize(18)
        self.grid.verticalHeader().setDefaultSectionSize(22)
        self.grid.setFixedHeight(156)
        self.grid.setShowGrid(False)
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setAccessibleName("Daily transformations. Use arrow keys to inspect dates.")
        self.grid.currentCellChanged.connect(self._select_day)
        calendar_row = QHBoxLayout()
        days = QVBoxLayout()
        days.setSpacing(0)
        for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            item = label(day, "muted")
            item.setFixedHeight(22)
            days.addWidget(item)
        calendar_row.addLayout(days)
        calendar_row.addWidget(self.grid, 1)
        body.addLayout(calendar_row)
        self.selected_day = label("", "muted", True)
        body.addWidget(self.selected_day)
        legend = QHBoxLayout()
        legend.addWidget(label("Daily totals", "muted"))
        for color, caption in zip(self.COLORS, ("0", "1", "2–3", "4–7", "8+")):
            swatch = label("  ")
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background: {color}; border-radius: 2px;")
            legend.addWidget(swatch)
            legend.addWidget(label(caption, "muted"))
        legend.addStretch()
        body.addLayout(legend)

    def set_summary(self, summary):
        today = summary.today
        start = today - timedelta(days=today.weekday() + 25 * 7)
        self.range_label.setText(f"{start:%b %d, %Y} – {today:%b %d, %Y}")
        for column in range(26):
            for row in range(7):
                day = start + timedelta(days=column * 7 + row)
                count = summary.days.get(day, 0)
                description = f"{day:%a, %b %d, %Y}: {count} transformations"
                item = QTableWidgetItem()
                item.setData(Qt.AccessibleTextRole, description)
                item.setToolTip(description)
                index = 0 if count == 0 else 1 if count == 1 else 2 if count < 4 else 3 if count < 8 else 4
                item.setBackground(QColor(self.COLORS[index] if day <= today else "#F7F7F7"))
                if day > today:
                    item.setFlags(Qt.NoItemFlags)
                self.grid.setItem(row, column, item)
        self.grid.setCurrentCell(today.weekday(), 25)
        self._select_day(today.weekday(), 25)

    def _select_day(self, row, column, *_):
        item = self.grid.item(row, column)
        if item:
            self.selected_day.setText(item.data(Qt.AccessibleTextRole))


class InsightsPanel(QWidget):
    """Composes metrics and charts; aggregates bounded storage batches on demand."""

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.summary = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next_batch)
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(24)
        heading = QHBoxLayout()
        heading.addWidget(label("Insights", "h1"))
        heading.addStretch()
        refresh = button("Refresh", icon_name="reuse")
        refresh.clicked.connect(self.refresh)
        heading.addWidget(refresh)
        body.addLayout(heading)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("Your usage")
        self.tabs.addTab("Your writing")
        body.addWidget(self.tabs)
        body.addWidget(divider())
        self.status = label("Saved activity, all time. Calendar shows the last 26 weeks.", "muted", True)
        body.addWidget(self.status)
        self.pages = QStackedWidget()
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        body.addWidget(self.pages)
        usage = QWidget()
        usage_body = QVBoxLayout(usage)
        usage_body.setContentsMargins(0, 0, 0, 0)
        usage_body.setSpacing(22)
        self.metrics_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.metrics_row.setSpacing(18)
        self.metrics = {}
        self.metric_captions = {}
        for key, title, caption in (
            ("words", "WORDS GENERATED", "Words in saved output, including discarded results"),
            ("completed", "TRANSFORMATIONS", "Completed generations in saved history"),
            ("used", "RESULTS USED", "Copied or applied to the original selection"),
        ):
            card, content = surface(20, muted=True)
            value = label("—", "insightValue")
            self.metrics[key] = value
            content.addWidget(value)
            content.addWidget(label(title, "eyebrow"))
            content.addSpacing(8)
            content.addWidget(divider())
            caption_label = label(caption, "muted", True)
            self.metric_captions[key] = caption_label
            content.addWidget(caption_label)
            self.metrics_row.addWidget(card, 1)
        usage_body.addLayout(self.metrics_row)
        self.charts_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.charts_row.setSpacing(22)
        source_card, source = surface(20, muted=True)
        source.addWidget(label("Writing sources", "h2"))
        self.source_count = label("", "muted", True)
        source.addWidget(self.source_count)
        source.addSpacing(12)
        self.sources = SourcesCard()
        source.addWidget(self.sources)
        source.addStretch()
        self.charts_row.addWidget(source_card, 1)
        streak_card, streak = surface(20, muted=True)
        self.streak_title = label("Your writing streak", "h2")
        streak.addWidget(self.streak_title)
        self.longest = label("", "muted", True)
        streak.addWidget(self.longest)
        streak.addSpacing(12)
        self.calendar = ActivityCalendar()
        streak.addWidget(self.calendar)
        streak.addStretch()
        self.charts_row.addWidget(streak_card, 1)
        usage_body.addLayout(self.charts_row)
        self.pages.addWidget(usage)
        writing = QWidget()
        writing_body = QVBoxLayout(writing)
        writing_body.setContentsMargins(0, 0, 0, 0)
        writing_body.setSpacing(22)
        for title, caption, attr in (
            ("Your most-used actions", "Completed generations, grouped by the saved action name.", "actions"),
            ("What happened to your results", "All saved requests, including failed and cancelled attempts.", "outcomes"),
        ):
            card, content = surface(22, muted=True)
            content.addWidget(label(title, "h2"))
            content.addWidget(label(caption, "muted", True))
            content.addSpacing(14)
            chart = RankedUsage()
            setattr(self, attr, chart)
            content.addWidget(chart)
            writing_body.addWidget(card)
        self.pages.addWidget(writing)
        self.note = label("", "muted", True)
        body.addWidget(self.note)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = QBoxLayout.LeftToRight if self.width() >= 860 else QBoxLayout.TopToBottom
        self.charts_row.setDirection(direction)
        self.metrics_row.setDirection(QBoxLayout.LeftToRight if self.width() >= 700 else QBoxLayout.TopToBottom)

    def refresh(self):
        self._timer.stop()
        self.status.setText("Updating your saved activity…")
        self._pending = UsageSummary(date.today())
        self._after_id = 0
        try:
            self._through_id = self.store.insight_boundary()
        except sqlite3.Error:
            self.status.setText("Could not load saved activity. Try Refresh.")
            return
        self._timer.start(0)

    def _next_batch(self):
        try:
            records = self.store.insight_batch(self._after_id, self._through_id)
        except sqlite3.Error:
            self.status.setText("Could not load saved activity. Try Refresh.")
            return
        for record in records:
            self._pending.add(record)
        if records:
            self._after_id = records[-1].id
        if records and self._after_id < self._through_id:
            self._timer.start(0)
            return
        self.summary = self._pending
        self._render()

    def _render(self):
        summary = self.summary
        self.metrics["words"].setText(f"{summary.words:,}" if summary.unreadable < summary.completed or not summary.completed else "—")
        self.metrics["completed"].setText(f"{summary.completed:,}")
        self.metrics["used"].setText(f"{summary.used_percent:.0f}%")
        self.metric_captions["used"].setText(f"{summary.used:,} of {summary.completed:,} results copied or applied")
        self.metrics["used"].setToolTip(f"{summary.used:,} of {summary.completed:,} completed results were copied or applied.")
        apps = len(summary.apps)
        self.source_count.setText(f"{apps} app{'s' if apps != 1 else ''} · select one to see details" if apps else "Grouped by app")
        self.sources.set_summary(summary)
        self.actions.set_counts(summary.actions)
        names = {"generated": "Generated", "replaced": "Applied to source", "copied": "Copied",
                 "rejected": "Discarded", "failed": "Failed", "cancelled": "Cancelled"}
        self.outcomes.set_counts({names.get(key, key): value for key, value in summary.outcomes.items()})
        days = summary.current_streak
        self.streak_title.setText(f"{days} day{'s' if days != 1 else ''} in a row")
        longest = summary.longest_streak
        self.longest.setText(f"Longest streak: {longest} day{'s' if longest != 1 else ''}. Current streak may end yesterday.")
        self.calendar.set_summary(summary)
        self.status.setText("Saved activity, all time. Calendar shows the last 26 weeks.")
        note = "Based on saved history on this device. Private or unsaved activity is excluded. Word counts use whitespace-separated output."
        if summary.unreadable:
            note += f" {summary.unreadable:,} completed records could not be unlocked; word and source totals cover readable records only."
        if self.store.get_pref("private_mode") == "true" or self.store.get_pref("save_history", "true") != "true" or self.store.cipher is None:
            note += " New activity is not being saved."
        self.note.setText(note)
