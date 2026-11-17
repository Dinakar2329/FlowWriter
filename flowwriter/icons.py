"""Lucide outline icons on a 24px grid, rendered by Qt at display resolution."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt, QBuffer, QIODevice, QPointF
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap, QColor, QPen
from PySide6.QtSvg import QSvgRenderer

from .lucide_icons import LUCIDE


# The app's own logo mark; every other icon comes from Lucide (see lucide_icons.py).
BRAND = '<path d="M3 5v14M7.5 9v6M12 3v18M16.5 7v10M21 5v14" stroke-width="2.8"/>'

PATHS = {**LUCIDE, "brand": BRAND}
PATHS["star-filled"] = PATHS["star"].replace("/>", ' fill="currentColor"/>')

# Which icon each built-in action shows in lists; anything else (your own actions) gets the bolt.
ACTION_ICONS = {
    "summarize": "summarize", "rephrase": "rephrase", "refine": "refine", "improve": "improve",
    "professional": "professional", "concise": "concise", "fix grammar": "grammar", "bulletize": "bullets",
    "friendly": "friendly", "expand": "expand", "executive": "executive", "code / tech": "code",
    "prompt": "prompt", "translate": "translate", "custom": "custom",
}


def action_icon_name(action_name: str) -> str:
    return ACTION_ICONS.get(action_name.strip().casefold(), "actions")


class _OutlineIcon(QIconEngine):
    def __init__(self, name: str, color: str):
        super().__init__()
        self.name, self.color = name, color

    def clone(self):
        return _OutlineIcon(self.name, self.color)

    def paint(self, painter, rect, mode, state):
        color = "#8A8A8A" if mode == QIcon.Disabled else self.color  # 3.2:1 on the light cards
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" color="{color}" stroke-width="1.9" '
            'stroke-linecap="round" stroke-linejoin="round">'
            + PATHS[self.name] + '</svg>'
        )
        QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, pixmap.rect(), mode, state)
        painter.end()
        return pixmap


@lru_cache(maxsize=128)
def icon(name: str, color: str = "#302E2B") -> QIcon:
    """Return a vector icon; reject unknown names rather than showing blanks."""
    if name not in PATHS:
        raise ValueError(f"Unknown icon: {name}")
    return QIcon(_OutlineIcon(name, color))


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """A self-contained amber badge remains legible on light and dark taskbars."""
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FFB44D"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), size * .24, size * .24)
        painter.setPen(QPen(QColor("#252525"), max(2, size * .065), Qt.SolidLine, Qt.RoundCap))
        for x, half_height in ((.23, .24), (.365, .13), (.5, .32), (.635, .20), (.77, .24)):
            painter.drawLine(QPointF(x * size, (.5 - half_height) * size),
                             QPointF(x * size, (.5 + half_height) * size))
        painter.end()
        result.addPixmap(pixmap)
    return result


def write_app_ico(path):
    """Write all badge sizes into a PNG-backed Windows ICO, without Pillow."""
    import struct
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not app_icon().pixmap(size, size).save(buffer, "PNG"):
            raise RuntimeError("Could not encode the application icon.")
        frames.append((size, bytes(data)))
    offset = 6 + 16 * len(frames)
    headers = []
    for size, data in frames:
        headers.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(headers) + b"".join(data for _, data in frames))
