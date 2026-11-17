"""Run FlowWriter Studio with: python -m flowwriter"""
from __future__ import annotations
import sys
import os
from pathlib import Path


def smoke_test(app):
    """Exercise bundled UI imports using disposable data, without OS hooks or keys."""
    from tempfile import TemporaryDirectory
    from cryptography.fernet import Fernet
    from PySide6.QtCore import QEvent
    from .dashboard import MainWindow
    from .storage import Store

    class NoSecrets:
        def get(self, _name):
            return ""

    with TemporaryDirectory(prefix="flowwriter-smoke-") as temporary:
        store = Store(Path(temporary) / "smoke.db", Fernet(Fernet.generate_key()))
        window = MainWindow(store, NoSecrets())
        try:
            window.show()
            for index in range(len(window.page_names)):
                window.navigate(index)
                app.processEvents()
                if window.grab().isNull():
                    return 1
            return 0
        finally:
            window.hide()
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            store.close()


def main():
    if "--smoke-test" in sys.argv:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QLockFile, Qt
    from PySide6.QtWidgets import QApplication
    from .dialogs import MessageBox
    from .styles import configure_theme
    from .domain import data_directory
    from .storage import Store
    from .vault import SecretVault
    from .controller import Controller
    from .windows import configure_process
    from .icons import app_icon

    configure_process()
    app = QApplication(sys.argv)
    app.setApplicationName("FlowWriter Studio")
    app.setOrganizationName("FlowWriter")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    configure_theme(app)
    if "--smoke-test" in sys.argv:
        return smoke_test(app)
    base = data_directory()
    base.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(base / "flowwriter.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        MessageBox.information(None, "FlowWriter Studio", "FlowWriter Studio is already running. Check the system tray.")
        return 0
    vault = SecretVault()
    cipher = vault.history_cipher(base / "flowwriter.db")
    store = Store(base / "flowwriter.db", cipher)
    controller = Controller(app, store, vault)
    result = app.exec()
    if not controller._closed:
        controller.quit()
    lock.unlock()
    return result


if __name__ == "__main__":
    sys.exit(main())
