"""Writing sources: apps first, then a fade-in detail view for the app you pick."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRectF, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget, QProgressBar,
    QGraphicsOpacityEffect, QLabel,
)

from .dashboard_widgets import label, button, divider
from .icons import icon

ACCENT = "#216D68"
FADE_MS = 220


def fade_in(widget: QWidget, duration: int = FADE_MS) -> None:
    """Fade a freshly shown page from transparent to opaque, then drop the effect."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._fade = animation          # keep a reference while it runs
    animation.start()


def day_phrase(day: date | None, today: date) -> str:
    if day is None:
        return "—"
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%b} {day.day}" + (f", {day.year}" if day.year != today.year else "")


def bar(value: int, total: int, name: str) -> QProgressBar:
    item = QProgressBar()
    item.setObjectName("usageBar")
    item.setRange(0, max(total, 1))
    item.setValue(value)
    item.setTextVisible(False)
    item.setFixedHeight(8)
    item.setAccessibleName(name)
    return item


class MiniBars(QWidget):
    """The last 14 days as small bars; the busiest day sets the height."""

    DAYS = 14

    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)
        self._counts: list[int] = []
        self._days: list[date] = []

    def set_days(self, counts, today: date) -> None:
        self._days = [today - timedelta(days=self.DAYS - 1 - i) for i in range(self.DAYS)]
        self._counts = [counts.get(day, 0) for day in self._days]
        total = sum(self._counts)
        self.setAccessibleName(f"{total} transformations in the last {self.DAYS} days")
        self.setToolTip("\n".join(f"{day:%a %b} {day.day}: {n}" for day, n in zip(self._days, self._counts) if n)
                        or "No activity in the last 14 days")
        self.update()

    def paintEvent(self, event):
        if not self._counts:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        peak = max(max(self._counts), 1)
        slot = self.width() / self.DAYS
        width = min(slot * 0.62, 18.0)
        for i, n in enumerate(self._counts):
            height = 4.0 if n == 0 else 6.0 + (self.height() - 6.0) * n / peak * 0.92
            height = min(height, self.height())
            x = i * slot + (slot - width) / 2
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT if n else "#DCE4E3"))
            painter.drawRoundedRect(QRectF(x, self.height() - height, width, height), 3, 3)


class AppRow(QPushButton):
    """One app: name, share, bar and a chevron. The whole row is the click target."""

    def __init__(self, name: str, count: int, total: int):
        super().__init__()
        self.setObjectName("appRow")
        self.setCursor(Qt.PointingHandCursor)
        share = count / total if total else 0
        self.setAccessibleName(f"{name}: {count} transformations, {share:.0%}. Open details.")
        self.setMinimumHeight(60)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 10, 10)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        title = label(name if len(name) <= 36 else name[:35] + "…")
        title.setToolTip(name)
        head.addWidget(title, 1)
        head.addWidget(label(f"{count:,} · {share:.0%}", "muted"))
        chevron = QLabel()
        chevron.setPixmap(icon("chevron", "#8A8A8A").pixmap(QSize(16, 16)))
        chevron.setFixedSize(16, 16)
        head.addWidget(chevron)
        outer.addLayout(head)
        outer.addWidget(bar(count, total, name))
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)


class SourcesCard(QStackedWidget):
    """Page 0: apps ranked by use. Page 1: details for the app that was clicked."""

    MAX_ROWS = 6

    def __init__(self):
        super().__init__()
        self._summary = None
        self._open_key: str | None = None
        self.list_page = QWidget()
        self.list_body = QVBoxLayout(self.list_page)
        self.list_body.setContentsMargins(0, 0, 0, 0)
        self.list_body.setSpacing(2)
        self.detail_page = QWidget()
        self.detail_body = QVBoxLayout(self.detail_page)
        self.detail_body.setContentsMargins(0, 0, 0, 0)
        self.detail_body.setSpacing(12)
        self.addWidget(self.list_page)
        self.addWidget(self.detail_page)

    # -- list ------------------------------------------------------------------------
    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                SourcesCard._clear(item.layout())

    def set_summary(self, summary) -> None:
        self._summary = summary
        self._clear(self.list_body)
        ranked, other = summary.app_ranking(self.MAX_ROWS)
        total = sum(a.count for a in summary.apps.values())
        if not total:
            self.list_body.addWidget(label("Your saved activity will appear here.", "muted", True))
        for app in ranked + ([other] if other else []):
            row = AppRow(app.name, app.count, total)
            row.clicked.connect(lambda _=False, a=app: self.open_app(a))
            self.list_body.addWidget(row)
        self.list_body.addStretch()
        if self._open_key is not None:            # a refresh while a detail view is open keeps it open
            match = next((a for a in ranked + ([other] if other else []) if a.name.casefold() == self._open_key), None)
            if match:
                self._fill_detail(match)
                return
            self._open_key = None
        self.setCurrentIndex(0)

    # -- detail ----------------------------------------------------------------------
    def open_app(self, app) -> None:
        self._open_key = app.name.casefold()
        self._fill_detail(app)
        self.setCurrentIndex(1)
        fade_in(self.detail_page)

    def close_detail(self) -> None:
        self._open_key = None
        self.setCurrentIndex(0)
        fade_in(self.list_page)

    def _fill_detail(self, app) -> None:
        self._clear(self.detail_body)
        today = self._summary.today
        back = button("All apps", icon_name="chevron-left")
        back.setObjectName("textButton")
        back.setAccessibleName("Back to all apps")
        back.clicked.connect(self.close_detail)
        top = QHBoxLayout()
        top.addWidget(back)
        top.addStretch()
        self.detail_body.addLayout(top)
        title = label(app.name, "h2")
        title.setToolTip(app.name)
        self.detail_body.addWidget(title)
        last = day_phrase(app.last_day, today)
        last = last.lower() if last in ("Today", "Yesterday") else last
        self.detail_body.addWidget(label(
            f"Last used {last} · {len(app.days)} active day{'s' if len(app.days) != 1 else ''}", "muted", True))

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for value, caption in ((f"{app.count:,}", "TRANSFORMATIONS"), (f"{app.words:,}", "WORDS"),
                               (f"{app.used_percent:.0f}%", "RESULTS USED")):
            tile = QWidget()
            tile.setObjectName("miniTile")
            inner = QVBoxLayout(tile)
            inner.setContentsMargins(12, 10, 12, 10)
            inner.setSpacing(2)
            inner.addWidget(label(value, "miniValue"))
            inner.addWidget(label(caption, "eyebrow"))
            tiles.addWidget(tile, 1)
        self.detail_body.addLayout(tiles)

        self.detail_body.addWidget(label("Last 14 days", "fieldLabel"))
        chart = MiniBars()
        chart.set_days(app.days, today)
        self.detail_body.addWidget(chart)

        self._section("Most-used actions", [(n, c) for n, c in sorted(app.actions.items(), key=lambda p: (-p[1], p[0].casefold()))[:4]], app.count)
        if app.members:
            self._section("Apps in this group", [(m.name, m.count) for m in sorted(app.members, key=lambda a: (-a.count, a.name.casefold()))[:6]], app.count)
        else:
            docs = sorted(app.documents.items(), key=lambda p: (-p[1], p[0].casefold()))[:4]
            if docs:
                self._section("Where you wrote", docs, app.count)
        self.detail_body.addStretch()

    def _section(self, heading: str, items, total: int) -> None:
        if not items:
            return
        self.detail_body.addWidget(divider())
        self.detail_body.addWidget(label(heading, "fieldLabel"))
        for name, count in items:
            line = QHBoxLayout()
            text = label(name if len(name) <= 44 else name[:43] + "…")
            text.setToolTip(name)
            line.addWidget(text, 1)
            line.addWidget(label(f"{count:,}", "muted"))
            self.detail_body.addLayout(line)
            self.detail_body.addWidget(bar(count, total, f"{name}: {count} of {total}"))
