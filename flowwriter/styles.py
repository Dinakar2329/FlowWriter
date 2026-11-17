"""Shared neutral desktop design tokens and Qt widget treatments."""

APP_STYLESHEET = r'''
QWidget { font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"; color: #262626; font-size: 10.5pt; }
QMainWindow, QWidget#root { background: #F5F5F5; }
QDialog, QMessageBox { background: #FFFFFF; color: #262626; }
QMessageBox QLabel { color: #262626; background: transparent; font-size: 10.5pt; }
QMessageBox QPushButton { min-width: 68px; padding: 9px 14px; }
QMessageBox QPushButton:default { background: #FFB44D; border-color: #E3A046; color: #28241D; }
QMessageBox QPushButton:focus { border-color: #DDDDDD; }
QWidget#page, QScrollArea, QStackedWidget { background: transparent; }
QFrame#workspace { background: #FFFFFF; border: 1px solid #E8E8E8; border-radius: 26px; }
QFrame#sidebar { background: #F5F5F5; border: none; }
QFrame#surface { background: #FFFFFF; border: 1px solid #E6E6E6; border-radius: 18px; }
QFrame#surfaceMuted { background: #F7F7F7; border: 1px solid #EBEBEB; border-radius: 18px; }
QFrame#hero { background: #181818; border: none; border-radius: 18px; }
QFrame#divider { background: #E6E6E6; border: none; }
QLabel { background: transparent; border: none; }
QLabel#logo { font-weight: 700; font-size: 17.25pt; letter-spacing: -0.8px; }
QLabel#h1 { font-weight: 500; font-size: 20.25pt; letter-spacing: -0.6px; color: #222222; }
QLabel#h2 { font-weight: 600; font-size: 13.5pt; letter-spacing: -0.2px; }
QLabel#h3 { font-weight: 600; font-size: 10.5pt; }
QLabel#muted { font-size: 9pt; color: #666666; }
QLabel#eyebrow { font-weight: 600; font-size: 7.5pt; letter-spacing: 1.6px; color: #6A6A6A; }
QLabel#fieldLabel { font-weight: 600; font-size: 9pt; color: #5E5E5E; }
QLabel#bigMetric { font-family: "Cambria", "Times New Roman"; font-size: 29.25pt; font-weight: 400; letter-spacing: -1.5px; color: #282828; }
QLabel#heroText { font-size: 18.75pt; font-weight: 500; letter-spacing: -0.8px; color: #FAFAFA; }
QLabel#heroSub { color: #D2D2D2; font-size: 9.75pt; }
QLabel#heroEyebrow { color: #C2C2C2; font-size: 7.5pt; font-weight: 600; letter-spacing: 1.8px; }
QLabel#chip { color: #625339; background: #F3EEDD; border-radius: 7px; padding: 4px 8px; font-weight: 500; font-size: 8.25pt; }
QLabel#statusGood { color: #35614C; background: #EDF4EE; border-radius: 7px; padding: 4px 8px; font-size: 8.25pt; }
QLabel#statusWarn { color: #895318; background: #FFF0D8; border-radius: 7px; padding: 4px 8px; font-size: 8.25pt; }
QLabel#statusError { color: #A24436; background: #FCEEEA; border-radius: 7px; padding: 4px 8px; font-size: 8.25pt; }
QLabel#body { color: #333333; font-size: 10.5pt; }
QPushButton { border: 1px solid #DDDDDD; background: #FFFFFF; padding: 10px 14px; border-radius: 9px; font-weight: 500; }
QPushButton:hover { background: #F3F3F3; border-color: #BBBBBB; }
QPushButton:pressed { background: #E8E8E8; }
QPushButton:focus { border: 1px solid #777777; }
QPushButton:disabled { color: #999999; background: #F1F1F1; border-color: #E6E6E6; }
QPushButton#primary { background: #FFB44D; border: 1px solid #E3A046; color: #28241D; }
QPushButton#primary:hover { background: #FFAA35; border-color: #A97530; }
QPushButton#primary:pressed { background: #EE9D30; }
QPushButton#heroButton { background: #FFB44D; color: #262626; border: 1px solid #FFB44D; padding: 10px 16px; }
QPushButton#heroButton:hover { background: #FFAA35; border-color: #FFAA35; }
QPushButton#navButton, QPushButton#navActive { border: 1px solid transparent; padding: 8px 12px; border-radius: 9px; text-align: left; font-size: 10.5pt; }
QPushButton#navButton { color: #515151; background: transparent; }
QPushButton#navButton:hover { background: #EDEDED; }
QPushButton#navActive { color: #242424; background: #EAEAEA; font-weight: 600; }
QPushButton#navButton:focus { background: #EDEDED; border-color: transparent; }
QPushButton#navActive:focus { border-color: transparent; }
QPushButton#textButton { color: #555555; background: transparent; border: 1px solid transparent; padding: 5px 6px; font-size: 9pt; }
QPushButton#textButton:hover { color: #28241D; background: #F1F1F1; }
QPushButton#iconButton { padding: 7px; background: transparent; border: 1px solid transparent; border-radius: 7px; }
QPushButton#iconButton:hover { background: #ECECEC; }
QPushButton#iconButton:focus, QPushButton#textButton:focus { border-color: #777777; }
QPushButton#pageButton, QPushButton#pageActive { min-width: 16px; padding: 5px 7px; border: 1px solid transparent; border-radius: 8px; font-size: 9pt; background: transparent; color: #555555; }
QPushButton#pageButton:hover { background: #ECECEC; }
QPushButton#pageButton:focus { border-color: #777777; }
QPushButton#pageButton:disabled { background: transparent; border-color: transparent; color: #8A8A8A; }
QPushButton#privateOn { background: #FFF0D8; border: 1px solid #E3A046; color: #28241D; font-weight: 600; }
QPushButton#privateOn:hover { background: #FFE6BF; border-color: #A97530; }
QPushButton#pageActive { background: #262626; color: #FFFFFF; font-weight: 600; }
QPushButton#pageActive:focus { border-color: #FFB44D; }
QPushButton#recentRow { text-align: left; border: none; background: transparent; border-radius: 9px; padding: 16px 12px; }
QPushButton#recentRow:hover { background: #EFEBE2; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QListWidget { background: #FFFFFF; border: 1px solid #DDDDDD; border-radius: 9px; padding: 10px 12px; selection-background-color: #F3D3A0; selection-color: #28241D; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #A47B3B; }
QDialog QPlainTextEdit:focus { border: 1px solid #DDDDDD; }
QTextEdit, QPlainTextEdit { font-size: 10.5pt; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #262626; selection-background-color: #EEEEEE; selection-color: #262626; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 6px 0; }
QScrollBar::handle:vertical { background: #D2D2D2; border-radius: 3px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QCheckBox { spacing: 10px; color: #444444; padding: 4px 0; }
QCheckBox:disabled { color: #8A8A8A; }
QPushButton#appRow { text-align: left; background: transparent; border: 1px solid transparent; border-radius: 12px; padding: 0; }
QPushButton#appRow:hover { background: #ECEEED; }
QPushButton#appRow:focus { border: 1px solid #777777; }
QPushButton#appRow:pressed { background: #E3E6E5; }
QWidget#miniTile { background: #FFFFFF; border: 1px solid #E6E6E6; border-radius: 12px; }
QLabel#miniValue { font-size: 15pt; font-weight: 500; letter-spacing: -0.4px; color: #252525; }
QSplitter::handle { background: transparent; width: 16px; }
QListWidget::item { padding: 11px 8px; border-radius: 7px; }
QListWidget::item:selected { background: #EEEEEE; color: #342D20; }
QToolTip { background: #292B25; color: #FAF8F1; border: none; padding: 7px 10px; }

QLabel#insightValue { color: #252525; font-size: 21pt; font-weight: 500; letter-spacing: -0.6px; }
QTabBar::tab { color: #676767; background: transparent; border: none; border-bottom: 2px solid transparent; padding: 10px 6px; margin-right: 18px; }
QTabBar::tab:selected { color: #242424; border-bottom: 2px solid #242424; }
QTabBar::tab:focus { background: #EFEFEF; }
QProgressBar#usageBar { background: #E6ECEB; border: none; border-radius: 3px; height: 8px; }
QProgressBar#usageBar::chunk { background: #216D68; border-radius: 3px; }
QTableWidget#calendar { background: transparent; border: none; selection-background-color: #D7EDEA; selection-color: #242424; }
QTableWidget#calendar::item { border: 2px solid #F7F7F7; }
QTableWidget#calendar::item:selected { border: 2px solid #242424; }
'''

# --- check boxes ---------------------------------------------------------------------
# Qt's Windows 11 style fills a ticked box with the Windows accent colour (purple on many
# PCs) and draws a dark tick on it, so the tick is invisible. The app draws its own boxes
# once at start-up and the stylesheet points at them. They are plain PNGs (with @2x copies),
# so they also work inside the packaged exe, which cannot rely on an SVG image plugin.
_BOX = 17
_BOX_STATES = {          # name: (fill, border, tick or None)
    "off":          ("#FFFFFF", "#8A8A8A", None),
    "off-hover":    ("#F3F3F3", "#262626", None),
    "off-disabled": ("#F1F1F1", "#D6D6D6", None),
    "on":           ("#262626", "#262626", "#FFFFFF"),
    "on-hover":     ("#000000", "#000000", "#FFFFFF"),
    "on-disabled":  ("#C4C4C4", "#C4C4C4", "#FFFFFF"),
}


def _draw_box(path, fill, border, tick, scale):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
    size = _BOX * scale
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(scale, scale)
    painter.setPen(QPen(QColor(border), 1.4))
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(.9, .9, _BOX - 1.8, _BOX - 1.8), 4.5, 4.5)
    if tick:
        mark = QPainterPath(QPointF(4.6, 8.9))
        mark.lineTo(7.4, 11.7)
        mark.lineTo(12.5, 5.6)
        painter.setPen(QPen(QColor(tick), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(mark)
    painter.end()
    return image.save(str(path))


def checkbox_rules() -> str:
    """Stylesheet rules for check boxes, or '' if the images cannot be written."""
    import tempfile
    from pathlib import Path
    try:
        folder = Path(tempfile.gettempdir()) / "FlowWriterStudio-ui"
        folder.mkdir(parents=True, exist_ok=True)
        for name, (fill, border, tick) in _BOX_STATES.items():
            for scale, suffix in ((1, ""), (2, "@2x")):
                if not _draw_box(folder / f"box-{name}{suffix}.png", fill, border, tick, scale):
                    return ""
    except OSError:
        return ""
    url = lambda name: f'url("{(folder / f"box-{name}.png").as_posix()}")'
    return (
        f"QCheckBox::indicator {{ width: {_BOX}px; height: {_BOX}px; }}\n"
        f"QCheckBox::indicator:unchecked {{ image: {url('off')}; }}\n"
        f"QCheckBox::indicator:unchecked:hover {{ image: {url('off-hover')}; }}\n"
        f"QCheckBox::indicator:unchecked:disabled {{ image: {url('off-disabled')}; }}\n"
        f"QCheckBox::indicator:checked {{ image: {url('on')}; }}\n"
        f"QCheckBox::indicator:checked:hover {{ image: {url('on-hover')}; }}\n"
        f"QCheckBox::indicator:checked:disabled {{ image: {url('on-disabled')}; }}\n"
    )


APP_STYLESHEET += checkbox_rules()


def light_palette():
    """Keep every dialog's background and foreground in the same color scheme."""
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    for role, color in (
        (QPalette.Window, "#FFFFFF"), (QPalette.WindowText, "#262626"),
        (QPalette.Base, "#FFFFFF"), (QPalette.AlternateBase, "#F7F7F7"),
        (QPalette.Text, "#262626"), (QPalette.Button, "#FFFFFF"),
        (QPalette.ButtonText, "#262626"), (QPalette.Highlight, "#EAEAEA"),
        (QPalette.HighlightedText, "#262626"), (QPalette.PlaceholderText, "#6F6F6F"),
        (QPalette.Link, "#216D68"), (QPalette.ToolTipBase, "#292929"),
        (QPalette.ToolTipText, "#FAFAFA"),
    ):
        palette.setColor(role, QColor(color))
    if hasattr(QPalette, "Accent"):   # Qt 6.6+: stops the Windows accent colour leaking into native controls
        palette.setColor(QPalette.Accent, QColor("#262626"))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        palette.setColor(QPalette.Disabled, role, QColor("#999999"))
    return palette


def configure_theme(app):
    """Request the app's light scheme without changing the operating system theme."""
    from PySide6.QtCore import Qt
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(light_palette())
    app.setStyleSheet(APP_STYLESHEET)
