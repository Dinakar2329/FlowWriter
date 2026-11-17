"""Consistent light dialogs, including on desktops using a dark system theme."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .icons import app_icon
from .styles import APP_STYLESHEET, light_palette


def _style_dialog(dialog):
    dialog.setStyleSheet(APP_STYLESHEET)
    dialog.setPalette(light_palette())
    dialog.setWindowIcon(app_icon())


def _style_caption(dialog):
    if QApplication.platformName() == "windows":
        from .windows import apply_titlebar
        apply_titlebar(int(dialog.winId()))


class LightDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        _style_dialog(self)

    def showEvent(self, event):
        super().showEvent(event)
        _style_caption(self)


class MessageBox(QMessageBox):
    def __init__(self, icon, title, text, buttons, parent=None):
        super().__init__(icon, title, text, buttons, parent)
        self.setOption(QMessageBox.Option.DontUseNativeDialog, True)
        self.setTextFormat(Qt.PlainText)
        _style_dialog(self)

    def showEvent(self, event):
        super().showEvent(event)
        _style_caption(self)

    @classmethod
    def _open(cls, parent, title, text, icon, buttons, default):
        dialog = cls(icon, title, text, buttons, parent)
        dialog.setDefaultButton(default)
        escape = cls.No if buttons & cls.No else cls.Cancel if buttons & cls.Cancel else cls.Ok
        if buttons & escape:
            dialog.setEscapeButton(escape)
        try:
            return cls.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()

    @classmethod
    def question(cls, parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, default=QMessageBox.No):
        return cls._open(parent, title, text, cls.Question, buttons, default)

    @classmethod
    def information(cls, parent, title, text, buttons=QMessageBox.Ok, default=QMessageBox.Ok):
        return cls._open(parent, title, text, cls.Information, buttons, default)

    @classmethod
    def warning(cls, parent, title, text, buttons=QMessageBox.Ok, default=QMessageBox.Ok):
        return cls._open(parent, title, text, cls.Warning, buttons, default)
