"""Floating result and edit card shown next to the selected text."""
from __future__ import annotations
from PySide6.QtCore import QPoint, QPropertyAnimation, Qt, Signal, QTimer, QSize
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QTextEdit)
from .radial import screen_bounds, clamp_into
from .icons import icon
from .dashboard_widgets import AppButton

CARD_STYLE = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; }
QFrame#card {
    background-color: #252720;
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 14px;
}
QLabel { background: transparent; border: none; }
QLabel#title { color: #F7F5EC; font-size: 10.5pt; font-weight: 600; }
QLabel#status { color: #BABDAF; font-size: 9pt; }
QLabel#hint { color: #A5AA99; font-size: 8.25pt; }
QLabel#error { color: #F0A3A3; font-size: 9pt; }

QLineEdit, QTextEdit {
    background-color: #1C1E19;
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 10px;
    padding: 9px 12px;
    color: #F3F0E6;
    font-size: 9.75pt;
    selection-background-color: #5C543B;
}
QLineEdit:focus, QTextEdit:focus { border: 1px solid rgba(255, 255, 255, 56); }

QPushButton { border-radius: 8px; padding: 7px 14px; font-size: 9pt; font-weight: 600; }
QPushButton#primaryBtn { background-color: #FFB44D; color: #28241D; border: none; }
QPushButton#primaryBtn:hover { background-color: #FFAA35; }
QPushButton#primaryBtn:disabled { background-color: #2A2A31; color: #6B6B74; }
QPushButton#ghostBtn {
    background-color: transparent; color: #DDDCD3;
    border: 1px solid rgba(255, 255, 255, 26);
}
QPushButton#ghostBtn:hover { background-color: rgba(255, 255, 255, 15); color: #FFFFFF; }
QPushButton#iconBtn {
    background-color: transparent; color: #8B8B94; border: none;
    font-size: 12.75pt; padding: 0px; border-radius: 6px;
}
QPushButton#iconBtn:hover { background-color: rgba(255, 255, 255, 20); color: #FFFFFF; }

QProgressBar { background-color: rgba(255, 255, 255, 15); border: none; border-radius: 1px; }
QProgressBar::chunk { background-color: #FFB44D; border-radius: 1px; }
"""


class PreviewPopupCard(QWidget):
    approved = Signal(str)
    copied = Signal(str)
    custom_submitted = Signal(str)
    retry_requested = Signal()
    cancelled = Signal()  # user dismissed the card (x / Cancel / Esc)

    WIDTH = 480
    SHADOW_MARGIN = 20  # transparent margin that holds the drop shadow
    PREVIEW_MIN_H, PREVIEW_MAX_H = 96, 240

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(CARD_STYLE)

        self._state = "idle"  # idle | custom | loading | result | error
        self._anchor = QPoint()
        self._drag_offset: QPoint | None = None
        self._user_moved = False

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(140)

        self._build_ui()

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._on_cancel)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._on_primary)

    # -- UI construction ---------------------------------------------------------
    def _build_ui(self) -> None:
        m = self.SHADOW_MARGIN
        outer = QVBoxLayout(self)
        outer.setContentsMargins(m, m, m, m)

        self.card = QFrame()
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(16, 12, 16, 14)
        body.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(6)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.title_label = QLabel("")
        self.title_label.setObjectName("title")
        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.status_label)
        header.addLayout(title_col)
        header.addStretch()

        self.close_btn = QPushButton()
        self.close_btn.setIcon(icon("close", "#C8CABC"))
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.setObjectName("iconBtn")
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.setAccessibleName("Close preview")
        self.close_btn.clicked.connect(self._on_cancel)
        header.addWidget(self.close_btn, 0, Qt.AlignTop)
        body.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        body.addWidget(self.progress)

        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("e.g. Convert to JSON, or make it witty")
        self.prompt_input.returnPressed.connect(self._on_submit_custom)
        body.addWidget(self.prompt_input)

        self.preview_box = QTextEdit()
        body.addWidget(self.preview_box)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        body.addWidget(self.error_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("hint")
        body.addWidget(self.hint_label)
        footer.addStretch()

        self.copy_btn = AppButton("Copy result")   # icon and text with an even gap
        self.copy_btn.setIcon(icon("copy", "#DDDCD3"))
        self.copy_btn.setIconSize(QSize(15, 15))
        self.copy_btn.setObjectName("ghostBtn")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy)
        footer.addWidget(self.copy_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("ghostBtn")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        footer.addWidget(self.cancel_btn)

        self.primary_btn = QPushButton("Replace")
        self.primary_btn.setObjectName("primaryBtn")
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary)
        footer.addWidget(self.primary_btn)
        body.addLayout(footer)

    # -- states ------------------------------------------------------------------
    def _set_visible_parts(
        self,
        *,
        progress: bool = False,
        prompt: bool = False,
        preview: bool = False,
        error: bool = False,
        primary: bool = False,
    ) -> None:
        self.progress.setVisible(progress)
        self.prompt_input.setVisible(prompt)
        self.preview_box.setVisible(preview)
        self.error_label.setVisible(error)
        self.primary_btn.setVisible(primary)
        self.copy_btn.setVisible(preview)

    def show_custom_prompt_mode(self, anchor: QPoint) -> None:
        self._state = "custom"
        self.title_label.setText("Custom instruction")
        self.status_label.setText("Describe how the selected text should change")
        self.prompt_input.clear()
        self.cancel_btn.setText("Close")
        self.hint_label.setText("Enter to run")
        self._set_visible_parts(prompt=True)
        self._present(anchor, focus_input=True)

    def show_loading(self, anchor: QPoint, label: str) -> None:
        self._state = "loading"
        self.title_label.setText(label)
        self.status_label.setText("Waiting for the model\u2026")
        self.preview_box.setReadOnly(False)
        self.cancel_btn.setText("Cancel")
        self.hint_label.setText("Esc to cancel")
        self._set_visible_parts(progress=True)
        self._present(anchor)

    def show_thinking(self) -> None:
        """The model is reasoning before it writes (common with local reasoning models)."""
        if self._state == "loading":
            self.status_label.setText("Thinking…")

    def show_stream(self, text: str) -> None:
        """Show the reply as it is written. The card stays cancellable and cannot replace yet."""
        if self._state not in ("loading", "streaming"):
            return
        first = self._state == "loading"
        self._state = "streaming"
        self.status_label.setText("Writing…")
        self.hint_label.setText("Esc to cancel")
        self.preview_box.setReadOnly(True)
        self.preview_box.setPlainText(text)
        bar = self.preview_box.verticalScrollBar()
        bar.setValue(bar.maximum())  # follow the newest words
        before = self.preview_box.height()
        self._fit_preview_height(grow_only=True)
        self._set_visible_parts(progress=True, preview=True)
        self.copy_btn.setVisible(False)
        if first or self.preview_box.height() != before:
            self._refit()

    def show_result(self, text: str) -> None:
        self._state = "result"
        self.status_label.setText("Review your result before applying")
        self.preview_box.setReadOnly(False)
        self.preview_box.setPlainText(text)
        self._fit_preview_height()
        self.cancel_btn.setText("Discard")
        self.primary_btn.setText("Approve and replace")
        self.primary_btn.setEnabled(True)
        self.hint_label.setText("Ctrl+Enter to replace")
        self._set_visible_parts(preview=True, primary=True)
        self._present(self._anchor)

    def show_replace_failed(self, reason="", retry=False) -> None:
        self._state = "result"
        self.error_label.setText(reason or "Could not safely restore and verify the original selection. Use Copy result instead.")
        self.error_label.show()
        self.primary_btn.setEnabled(retry)
        if retry:
            self.primary_btn.setText("Try replace again")

    def _on_copy(self) -> None:
        if self._state == "result":
            self.copied.emit(self.preview_box.toPlainText())
            self.hide()

    def show_error(self, message: str) -> None:
        self._state = "error"
        self.status_label.setText("Couldn't finish")
        self.error_label.setText(message)
        self.cancel_btn.setText("Close")
        self.primary_btn.setText("Retry")
        self.primary_btn.setEnabled(True)
        self.hint_label.setText("")
        self._set_visible_parts(error=True, primary=True)
        self._present(self._anchor)

    def _fit_preview_height(self, grow_only: bool = False) -> None:
        text_width = self.WIDTH - 2 * self.SHADOW_MARGIN - 32 - 26
        doc = self.preview_box.document()
        doc.setTextWidth(text_width)
        height = int(doc.size().height()) + 28
        height = max(self.PREVIEW_MIN_H, min(height, self.PREVIEW_MAX_H))
        if grow_only and self.preview_box.isVisible():
            height = max(height, self.preview_box.height())  # no jumping while words arrive
        self.preview_box.setFixedHeight(height)

    # -- placement -----------------------------------------------------------------
    def _present(self, anchor: QPoint, focus_input: bool = False) -> None:
        first_show = not self.isVisible()
        self._anchor = anchor
        if first_show:
            self._user_moved = False

        self._refit()
        if first_show:
            self.setWindowOpacity(0.0)
            self.show()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            QTimer.singleShot(0, self._refit)  # re-measure once real fonts/metrics exist

        if focus_input:
            self.activateWindow()
            self.prompt_input.setFocus()

    def _refit(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.adjustSize()
        self._place()

    def _place(self) -> None:
        """Prefer just below the cursor, flip above if it won't fit, never leave the screen."""
        if self._user_moved:
            return
        bounds = screen_bounds(self._anchor)
        m = self.SHADOW_MARGIN
        w, h = self.width(), self.height()
        gap = 14

        x = self._anchor.x() - w // 2
        y = self._anchor.y() + gap - m  # below the cursor
        if y + h - m > bounds.bottom() - 8:
            y = self._anchor.y() - gap - h + m  # above the cursor

        # margin is relative to the transparent shadow border, so the visible card stays 8px in
        self.move(clamp_into(bounds, x, y, w, h, margin=8 - m))

    # -- actions ---------------------------------------------------------------------
    def _on_submit_custom(self) -> None:
        text = self.prompt_input.text().strip()
        if text:
            self.custom_submitted.emit(text)

    def _on_primary(self) -> None:
        if not self.primary_btn.isEnabled():
            return
        if self._state == "result":
            final_text = self.preview_box.toPlainText()
            if final_text.strip():
                self.approved.emit(final_text)
        elif self._state == "error":
            self.retry_requested.emit()

    def _on_cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    # -- drag to move ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._user_moved = True

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None


