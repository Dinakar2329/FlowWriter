"""Presentation-only pieces composed by the desktop dashboard."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal, QRect, QEvent, QTimer
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                          QTextDocument, QTextCursor, QTextBlockFormat, QPalette, QAbstractTextDocumentLayout)
from PySide6.QtWidgets import (QComboBox, QFrame, QLabel, QPushButton, QHBoxLayout,
                              QVBoxLayout, QWidget, QScrollArea, QAbstractScrollArea, QApplication,
                              QStyledItemDelegate, QStyle, QStyleOptionButton, QStylePainter)

from .icons import icon


def label(text, style="", wrap=False):
    item = QLabel(str(text))
    item.setTextFormat(Qt.PlainText)
    if style:
        item.setObjectName(style)
    item.setWordWrap(wrap)
    return item


def surface(inner_padding=18, muted=False):
    card = QFrame()
    card.setObjectName("surfaceMuted" if muted else "surface")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(inner_padding, inner_padding, inner_padding, inner_padding)
    layout.setSpacing(9)
    return card, layout


class AppButton(QPushButton):
    """A push button whose icon and text sit together with an even gap, centred on both axes.

    Qt's own layout puts the icon about 4 px from the text and rounds its position, so icons
    look cramped and a pixel off. Here the background still comes from the stylesheet, and the
    icon and text are drawn as one centred group with GAP pixels between them.
    """
    GAP = 8
    LEFT_ALIGNED = frozenset({"navButton", "navActive", "recentRow"})   # these keep Qt's own layout

    def _has_group(self) -> bool:
        return (not self.icon().isNull() and bool(self.text())
                and self.objectName() not in self.LEFT_ALIGNED)

    def sizeHint(self):
        hint = super().sizeHint()
        return hint + QSize(self.GAP - 4, 0) if self._has_group() else hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return hint + QSize(self.GAP - 4, 0) if self._has_group() else hint

    def paintEvent(self, event):
        if not self._has_group():
            return super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text, icon_ = option.text, QIcon(self.icon())    # a copy: clearing the option must not clear it
        option.text, option.icon = "", QIcon()
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)       # background, border, focus ring
        area = self.style().subElementRect(QStyle.SE_PushButtonContents, option, self)
        size = self.iconSize()
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        left = area.left() + (area.width() - (size.width() + self.GAP + text_width)) / 2
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        pixmap = icon_.pixmap(size, self.devicePixelRatioF(), mode, QIcon.Off)
        painter.drawPixmap(round(left), round(area.center().y() + 0.5 - size.height() / 2), pixmap)
        group = QPalette.Active if self.isEnabled() else QPalette.Disabled
        painter.setPen(self.palette().color(group, QPalette.ButtonText))
        painter.setFont(self.font())
        painter.drawText(QRect(round(left) + size.width() + self.GAP, area.top(), text_width + 4, area.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, text)


def button(text, primary=False, icon_name=None):
    item = AppButton(text)
    if primary:
        item.setObjectName("primary")
    item.setCursor(Qt.PointingHandCursor)
    if icon_name:
        # Match the icon to the text colour of the button style it sits in.
        item.setIcon(icon(icon_name, "#28241D" if primary else "#302E2B"))
        item.setIconSize(QSize(18, 18))
    return item


def icon_button(name, tooltip):
    item = button("", icon_name=name)
    item.setObjectName("iconButton")
    item.setFixedSize(34, 34)
    item.setToolTip(tooltip)
    item.setAccessibleName(tooltip)
    return item


def divider():
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


class ScrollFade(QWidget):
    def __init__(self, parent, top=False, color="#FFFFFF"):
        super().__init__(parent)
        self.top = top
        self.color = QColor(color)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        solid, clear = QColor(self.color), QColor(self.color)
        solid.setAlpha(255)
        clear.setAlpha(0)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, solid if self.top else clear)
        gradient.setColorAt(1, clear if self.top else solid)
        painter.fillRect(self.rect(), gradient)
        painter.end()


class SoftScrollArea(QScrollArea):
    """Fade scroll boundaries into the surface behind them without intercepting input."""

    def __init__(self, fade="#FFFFFF"):
        super().__init__()
        self.top_fade = ScrollFade(self.viewport(), top=True, color=fade)
        self.bottom_fade = ScrollFade(self.viewport(), color=fade)
        self.viewport().installEventFilter(self)
        self.verticalScrollBar().valueChanged.connect(self._position_fades)
        self.verticalScrollBar().rangeChanged.connect(self._position_fades)

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Resize:
            self._position_fades()
        return super().eventFilter(watched, event)

    def _position_fades(self, *_):
        bounds = self.viewport().rect()
        bar = self.verticalScrollBar()
        self.top_fade.setGeometry(0, 0, bounds.width(), 22)
        self.bottom_fade.setGeometry(0, max(0, bounds.height() - 28), bounds.width(), 28)
        self.top_fade.setVisible(bar.value() > bar.minimum())
        self.bottom_fade.setVisible(bar.value() < bar.maximum())
        self.top_fade.raise_()
        self.bottom_fade.raise_()


class FeedScrollArea(SoftScrollArea):
    """A scroller that is only as tall as its content, up to `max_height`.

    Short pages stay compact; long pages get their own scrollbar instead of
    stretching the whole dashboard.
    """

    def __init__(self, max_height=460, fade="#F7F7F7"):
        super().__init__(fade=fade)
        self.max_height = max_height
        self._fit_pending = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)

    def setWidget(self, widget):
        super().setWidget(widget)
        # Rows added after the first measurement are laid out later. Re-measure when the
        # content settles, or the list can stay at the height it had before they existed.
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.widget() and event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self._schedule_fit()
        return super().eventFilter(watched, event)

    def _schedule_fit(self):
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._deferred_fit)

    def _deferred_fit(self):
        self._fit_pending = False
        self.fit()

    def fit(self):
        content = self.widget()
        layout = content.layout() if content else None
        if layout is None:
            return
        layout.activate()
        width = self.viewport().width() or self.width()
        needed = layout.totalHeightForWidth(width)
        if needed <= 0:
            needed = content.sizeHint().height()
        height = max(1, min(needed, self.max_height))
        if self.height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def wheelEvent(self, event):
        """Hand the wheel to the page behind once this list can't scroll further.

        Qt does not chain an ignored wheel event out of a scroll area, so without
        this the page would appear frozen while the pointer is over the list.
        """
        bar = self.verticalScrollBar()
        delta = event.angleDelta().y() or event.pixelDelta().y()
        stuck = (delta > 0 and bar.value() <= bar.minimum()) or (delta < 0 and bar.value() >= bar.maximum())
        if bar.maximum() <= bar.minimum() or stuck:
            outer = self.parentWidget()
            while outer is not None and not isinstance(outer, QAbstractScrollArea):
                outer = outer.parentWidget()
            if outer is not None:
                QApplication.sendEvent(outer.viewport(), event)
            event.accept()
            return
        super().wheelEvent(event)


def page_numbers(current, total, span=1):
    """Page buttons to show: first, last, and `span` pages around the current one.

    Gaps are returned as None so the caller can draw an ellipsis. `current` is
    zero-based; the returned numbers are too.
    """
    if total <= 0:
        return []
    keep = {0, total - 1, *range(max(0, current - span), min(total, current + span + 1))}
    shown, previous = [], None
    for page in sorted(keep):
        if previous is not None and page - previous > 1:
            shown.append(None)
        shown.append(page)
        previous = page
    return shown


class Pager(QWidget):
    """Compact 'Showing 1–10 of 87' bar with previous/next and numbered pages."""

    page_requested = Signal(int)

    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 4, 10, 6)
        row.setSpacing(4)
        self.summary = label("", "muted")
        row.addWidget(self.summary, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(2)
        row.addLayout(self.buttons)

    def _control(self, text, tooltip, target, *, current=False, enabled=True, icon_name=None):
        item = QPushButton(text)
        item.setObjectName("pageActive" if current else "pageButton")
        item.setCursor(Qt.PointingHandCursor)
        item.setAccessibleName(tooltip)
        item.setToolTip(tooltip)
        item.setEnabled(enabled)
        if icon_name:
            item.setIcon(icon(icon_name, "#686256"))
            item.setIconSize(QSize(16, 16))
        if current:
            item.setAccessibleDescription("Current page")
        item.clicked.connect(lambda checked=False, page=target: self.page_requested.emit(page))
        self.buttons.addWidget(item)
        return item

    def set_state(self, page, page_count, first, last, total):
        while self.buttons.count():
            part = self.buttons.takeAt(0).widget()
            if part is not None:
                part.hide()
                part.deleteLater()
        self.summary.setText(f"{first:,}–{last:,} of {total:,}" if total else "")
        self.setVisible(page_count > 1)
        if page_count <= 1:
            return
        self._control("", "Previous page", page - 1, enabled=page > 0, icon_name="chevron-left")
        for number in page_numbers(page, page_count):
            if number is None:
                gap = label("…", "muted")
                gap.setAlignment(Qt.AlignCenter)
                gap.setFixedWidth(22)
                self.buttons.addWidget(gap)
            else:
                self._control(str(number + 1), f"Page {number + 1} of {page_count}", number, current=number == page)
        self._control("", "Next page", page + 1, enabled=page < page_count - 1, icon_name="chevron")


class SelectField(QComboBox):
    """Native combo-box behavior with the shared vector disclosure icon."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        bounds = QRect(self.width() - 26, (self.height() - 14) // 2, 14, 14)
        icon("chevron-down", "#736F67").paint(painter, bounds)
        painter.end()


class SelectionDelegate(QStyledItemDelegate):
    """Keep native selection and keyboard behavior without a focus rectangle."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus


class FlowArtwork(QWidget):
    """Quiet, resolution-independent ribbon illustration for the welcome banner."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(130)
        self.setMinimumHeight(120)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 130, self.height() / 160)
        gradient = QLinearGradient(0, 0, 0, 160)
        gradient.setColorAt(0, QColor(190, 190, 190, 0))
        gradient.setColorAt(.1, QColor(190, 190, 190, 0))
        gradient.setColorAt(.3, QColor(190, 190, 190, 160))
        gradient.setColorAt(.6, QColor(160, 160, 160, 190))
        gradient.setColorAt(.9, QColor(160, 160, 160, 0))
        gradient.setColorAt(1, QColor(160, 160, 160, 0))
        painter.setPen(QPen(gradient, 1.2))
        for offset in range(0, 60, 5):
            path = QPainterPath()
            path.moveTo(12 + offset * .55, 150)
            path.cubicTo(120 + offset * .1, 95, -10 + offset * .45, 80, 85 + offset * .55, 10)
            painter.drawPath(path)
        painter.end()


class ReadableText(QLabel):
    """Plain text layout with modest leading above the native font metrics."""

    def __init__(self, text):
        super().__init__(text)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _document(self, width):
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(self.font())
        document.setPlainText(self.text())
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.Document)
        block = QTextBlockFormat()
        block.setLineHeight(self.fontMetrics().height() * 1.15, QTextBlockFormat.FixedHeight.value)
        cursor.mergeBlockFormat(block)
        document.setTextWidth(max(1, width))
        return document

    def heightForWidth(self, width):
        return int(self._document(width).size().height()) + 2

    def sizeHint(self):
        return QSize(360, self.heightForWidth(360))

    def minimumSizeHint(self):
        return QSize(0, int(self.fontMetrics().height() * 1.15) + 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.Text, self.palette().color(QPalette.WindowText))
        document = self._document(self.width())
        document.documentLayout().draw(painter, context)
        painter.end()


class RecentEntry(QFrame):
    """Readable history preview with explicit, keyboard-accessible row actions."""

    opened = Signal()
    copied = Signal()

    def __init__(self, record, timestamp: str):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 18, 10, 18)
        layout.setSpacing(20)
        time = QLabel(timestamp)  # "Today\n12:54 PM": two short lines, so rows from different days differ
        time.setObjectName("muted")
        time.setFixedWidth(76)
        layout.addWidget(time, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(9)
        title = QLabel(record["action"])
        title.setTextFormat(Qt.PlainText)
        title.setObjectName("h3")
        text.addWidget(title)
        content = " ".join((record["output_text"] or record["input_text"]).split())
        excerpt = ReadableText(content[:210] + ("…" if len(content) > 210 else ""))
        excerpt.setTextFormat(Qt.PlainText)
        excerpt.setObjectName("body")
        excerpt.setWordWrap(True)
        text.addWidget(excerpt)
        layout.addLayout(text, 1)
        for name, tooltip, signal in (
            ("copy", "Copy transformed text", self.copied),
            ("arrow-up", "Open transformation details", self.opened),
        ):
            control = QPushButton()
            control.setObjectName("iconButton")
            control.setIcon(icon(name, "#686256"))
            control.setIconSize(QSize(18, 18))
            control.setFixedSize(32, 32)
            control.setToolTip(tooltip)
            control.setAccessibleName(tooltip)
            control.setCursor(Qt.PointingHandCursor)
            control.clicked.connect(lambda checked=False, target=signal: target.emit())
            layout.addWidget(control, 0, Qt.AlignVCenter)
