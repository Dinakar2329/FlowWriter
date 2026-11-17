"""Radial (donut) action menu with two faces, inspired by the radial menu in Filee. Actions come from the database."""
from __future__ import annotations
import math
import time
from typing import NamedTuple
from PySide6.QtCore import QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"]

class ActionSlice(NamedTuple):
    label: str
    prompt: str

FRONT_SLICES: list[ActionSlice] = [ActionSlice("Summarize", "Summarize the selected text.")]
BACK_SLICES: list[ActionSlice] = [ActionSlice("Fix Grammar", "Correct the selected text.")]

def ui_font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font

def screen_bounds(point: QPoint) -> QRect:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    return screen.availableGeometry()

def clamp_into(bounds: QRect, x: int, y: int, w: int, h: int, margin: int=8) -> QPoint:
    min_x, max_x = bounds.left()+margin, bounds.right()-w+1-margin
    min_y, max_y = bounds.top()+margin, bounds.bottom()-h+1-margin
    return QPoint(max(min_x,min(x,max_x)), max(min_y,min(y,max_y)))

class RadialMenuWindow(QWidget):
    action_selected = Signal(str, str)  # label, prompt
    custom_prompt_requested = Signal()

    SIZE = 300
    OUTER = 135
    INNER = 50
    GAP_DEG = 2.5
    DISMISS_DISTANCE = OUTER + 90  # cursor wandering this far from the ring closes it
    HUB, NONE = -2, -1

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus  # never steal focus from the target app
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(self.SIZE, self.SIZE)

        self.is_back_face = False
        self.hovered_index = self.NONE
        self._last_flip = 0.0
        self._center_global = QPoint()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(120)

        self._watch = QTimer(self)
        self._watch.setInterval(100)
        self._watch.timeout.connect(self._dismiss_if_cursor_far)

    def set_actions(self, actions) -> None:
        faces = {0: [], 1: []}
        for action in actions:
            faces[action.face if action.face in (0, 1) else 0].append(ActionSlice(action.name, action.prompt))
        self._faces = {face: slices or [ActionSlice("Custom", "")] for face, slices in faces.items()}

    @property
    def active_slices(self) -> list[ActionSlice]:
        if hasattr(self, "_faces"):
            return self._faces[1 if self.is_back_face else 0]
        return BACK_SLICES if self.is_back_face else FRONT_SLICES

    def _start_offset(self, step: float) -> float:
        """Degrees (clockwise from 3 o'clock) where slice 0 begins: centers it at 12 o'clock."""
        return -90.0 - step / 2

    # -- lifecycle -----------------------------------------------------------
    def pop_at_cursor(self) -> None:
        pos = QCursor.pos()
        self.is_back_face = False
        self.hovered_index = self.NONE

        top_left = clamp_into(
            screen_bounds(pos),
            pos.x() - self.SIZE // 2,
            pos.y() - self.SIZE // 2,
            self.SIZE,
            self.SIZE,
            margin=0,
        )
        self.move(top_left)
        self._center_global = top_left + QPoint(self.SIZE // 2, self.SIZE // 2)

        self.setWindowOpacity(0.0)
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self.update()

    def showEvent(self, event) -> None:
        self._watch.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._watch.stop()
        super().hideEvent(event)

    def _dismiss_if_cursor_far(self) -> None:
        delta = QCursor.pos() - self._center_global
        if math.hypot(delta.x(), delta.y()) > self.DISMISS_DISTANCE:
            self.hide()

    # -- interaction -----------------------------------------------------------
    def _index_at(self, pos: QPointF) -> int:
        dx = pos.x() - self.width() / 2
        dy = pos.y() - self.height() / 2
        dist = math.hypot(dx, dy)
        if dist < self.INNER:
            return self.HUB
        if dist > self.OUTER:
            return self.NONE
        step = 360.0 / len(self.active_slices)
        angle = (math.degrees(math.atan2(dy, dx)) - self._start_offset(step)) % 360.0
        return int(angle // step)

    def _set_hover(self, index: int) -> None:
        if index != self.hovered_index:
            self.hovered_index = index
            self.update()

    def wheelEvent(self, event) -> None:
        """Scroll flips Front <-> Back (debounced so trackpads don't flicker)."""
        now = time.monotonic()
        if now - self._last_flip < 0.18:
            return
        self._last_flip = now
        self.is_back_face = not self.is_back_face
        self._set_hover(self._index_at(QPointF(self.mapFromGlobal(QCursor.pos()))))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._set_hover(self._index_at(event.position()))

    def leaveEvent(self, event) -> None:
        self._set_hover(self.NONE)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.hide()
            return
        index = self._index_at(event.position())
        self.hide()
        if index == self.HUB:
            self.custom_prompt_requested.emit()
        elif 0 <= index < len(self.active_slices):
            action = self.active_slices[index]
            self.action_selected.emit(action.label, action.prompt)

    # -- painting ----------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cx, cy = self.width() / 2, self.height() / 2
        center = QPointF(cx, cy)
        slices = self.active_slices
        step = 360.0 / len(slices)
        offset = self._start_offset(step)

        # Soft shadow ring so the menu lifts off any background
        halo_r = self.OUTER + 14
        halo = QRadialGradient(center, halo_r)
        halo.setColorAt(0.0, QColor(0, 0, 0, 0))
        halo.setColorAt(0.84, QColor(0, 0, 0, 0))
        halo.setColorAt(0.91, QColor(0, 0, 0, 70))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, halo_r, halo_r)

        outer_rect = QRectF(cx - self.OUTER, cy - self.OUTER, self.OUTER * 2, self.OUTER * 2)
        inner_rect = QRectF(cx - self.INNER, cy - self.INNER, self.INNER * 2, self.INNER * 2)
        text_radius = (self.INNER + self.OUTER) / 2

        for i, action in enumerate(slices):
            start = offset + i * step + self.GAP_DEG / 2
            sweep = step - self.GAP_DEG

            path = QPainterPath()
            path.arcMoveTo(outer_rect, -start)
            path.arcTo(outer_rect, -start, -sweep)
            path.arcTo(inner_rect, -(start + sweep), sweep)
            path.closeSubpath()

            hovered = i == self.hovered_index
            if hovered:
                painter.setBrush(QColor(255, 180, 77, 255))
                painter.setPen(Qt.NoPen)
            else:
                painter.setBrush(QColor(37, 39, 32, 242))
                painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
            painter.drawPath(path)

            mid = math.radians(offset + i * step + step / 2)
            tx = cx + text_radius * math.cos(mid)
            ty = cy + text_radius * math.sin(mid)
            painter.setPen(QColor(40, 36, 29) if hovered else QColor(243, 240, 230))
            painter.setFont(ui_font(9, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(tx - 42, ty - 14, 84, 28), Qt.AlignCenter | Qt.TextWordWrap, action.label
            )

        # Center hub: custom prompt + face indicator
        hub_hovered = self.hovered_index == self.HUB
        fg = QColor(40, 36, 29) if hub_hovered else QColor(243, 240, 230)
        muted = QColor(40, 36, 29, 180) if hub_hovered else QColor(200, 204, 186, 200)

        painter.setBrush(QColor(255, 180, 77, 255) if hub_hovered else QColor(45, 48, 39, 250))
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawEllipse(center, self.INNER - 4, self.INNER - 4)

        painter.setPen(fg)
        painter.setFont(ui_font(10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(cx - 30, cy - 24, 60, 18), Qt.AlignCenter, "Custom")

        painter.setPen(Qt.NoPen)
        for dot_x, active in ((cx - 5, not self.is_back_face), (cx + 5, self.is_back_face)):
            painter.setBrush(fg if active else muted)
            painter.drawEllipse(QPointF(dot_x, cy + 5), 2.2, 2.2)

        painter.setPen(muted)
        painter.setFont(ui_font(7))
        painter.drawText(QRectF(cx - 34, cy + 12, 68, 14), Qt.AlignCenter, "scroll to flip")


