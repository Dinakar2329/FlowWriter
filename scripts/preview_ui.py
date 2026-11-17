"""Render the dashboard offscreen using disposable, explicitly synthetic history.

Run: python scripts/preview_ui.py --output artifacts/overview.png
No hooks, API requests, OS keychain calls, or real application data are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

if "--native" not in sys.argv:   # --native uses the real platform style (e.g. Windows 11 widgets)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from flowwriter.dashboard import MainWindow, HistoryDialog
from flowwriter.dialogs import MessageBox
from flowwriter.styles import configure_theme
from flowwriter.storage import Store
from flowwriter.vault import SecretVault


SAMPLE_SOURCES = (
    "Scratchpad", "Scratchpad", "Q3 plan.xlsx - Excel", "Budget review.xlsx - Excel", "Inbox - Alex - Outlook",
    "Chat | Sam Rivera | Microsoft Teams", "Scratchpad", "Chat | Design team | Microsoft Teams",
    "Release notes - Notepad", "Launch brief - Word", "Roadmap - Google Chrome", "Draft - Slack", "Notes - Obsidian",
)


class PreviewKeychain:
    def get_password(self, *args):
        return ""

    def set_password(self, *args):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/overview.png"))
    parser.add_argument("--page", type=int, choices=range(8), default=0)
    parser.add_argument("--native", action="store_true", help="use the real platform style instead of offscreen")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=880)
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--insights-tab", choices=("usage", "writing"), default="usage")
    parser.add_argument("--open-app", type=int, default=None, help="Insights: open the Nth app in Writing sources")
    parser.add_argument("--dialog", choices=("details", "delete"))
    args = parser.parse_args()
    if args.empty and args.dialog == "details":
        parser.error("A details preview needs synthetic history; omit --empty.")
    app = QApplication([])
    configure_theme(app)
    # Windows' offscreen platform does not enumerate installed fonts.
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf", "georgia.ttf"):
            QFontDatabase.addApplicationFont(str(fonts / filename))
    with TemporaryDirectory(prefix="flowwriter-preview-") as temporary:
        store = Store(Path(temporary) / "preview.db", Fernet(Fernet.generate_key()))
        if not args.empty:
            samples = [
                ("Polish", "Thanks for sharing your thoughts. I have updated the proposal to reflect our conversation and would love to hear what you think.", "copied"),
                ("Shorten", "A quieter workspace. A clearer mind. More room for the ideas that matter.", "replaced"),
                ("Fix grammar", "The best ideas often start with a simple conversation. Let's make a little time for one this week.", "copied"),
                ("Professional", "The first draft is ready for review. Please share your feedback by Thursday so we can prepare the final version together.", "replaced"),
            ]
            for index, (action, text, status) in enumerate(reversed(samples)):
                row_id = store.log_action(action, input_text="Synthetic preview text.", output_text=text,
                                          instruction="Synthetic preview instruction.", source_app="Preview document",
                                          provider_name="Demo provider", model="preview-model", status=status)
                created = datetime.now(timezone.utc) - timedelta(minutes=(3-index) * 21)
                with store.conn:
                    store.conn.execute("UPDATE history SET created_at=? WHERE id=?", (created.isoformat(), row_id))
            if args.page == 6:
                # Deterministic synthetic usage spread across the calendar for visual QA.
                for days_ago in range(1, 177):
                    if days_ago % 11 >= 7:
                        continue
                    for item in range(1 + days_ago % 4):
                        action, output, status = samples[(days_ago + item) % len(samples)]
                        status = ("copied", "replaced", "generated", "rejected")[(days_ago + item) % 4]
                        row_id = store.log_action(
                            action, input_text="Synthetic preview text.", output_text=output,
                            source_app=SAMPLE_SOURCES[(days_ago * 7 + item) % len(SAMPLE_SOURCES)],
                            provider_name="Demo provider", model="preview-model", status=status,
                        )
                        created = datetime.now(timezone.utc) - timedelta(days=days_ago)
                        with store.conn:
                            store.conn.execute("UPDATE history SET created_at=? WHERE id=?", (created.isoformat(), row_id))
        window = MainWindow(store, SecretVault(PreviewKeychain()))
        window.resize(args.width, args.height)
        window.navigate(args.page)
        if args.page == 6 and args.insights_tab == "writing":
            window.insights_panel.tabs.setCurrentIndex(1)
        window.show()
        if args.open_app is not None and args.page == 6:
            for _ in range(60):          # let the background aggregation finish
                app.processEvents()
                if window.insights_panel.summary is not None:
                    break
            sources = window.insights_panel.sources
            ranked, other = window.insights_panel.summary.app_ranking(sources.MAX_ROWS)
            sources.open_app((ranked + ([other] if other else []))[args.open_app])
            app.processEvents()
        preview_dialog = None
        if args.dialog == "details":
            preview_dialog = HistoryDialog(store.recent(limit=1)[0], window)
        elif args.dialog == "delete":
            preview_dialog = MessageBox(MessageBox.Question, "Delete entry", "Delete this history entry?",
                                        MessageBox.Yes | MessageBox.No, window)
            preview_dialog.setDefaultButton(MessageBox.No)
            preview_dialog.setEscapeButton(MessageBox.No)
        if preview_dialog is not None:
            preview_dialog.show()

        def capture():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            target = preview_dialog if preview_dialog is not None else window
            if not target.grab().save(str(args.output)):
                raise RuntimeError(f"Could not save preview: {args.output}")
            print(f"Saved {args.output.resolve()}")
            app.quit()

        QTimer.singleShot(600 if args.open_app is not None else 250, capture)
        app.exec()
        if preview_dialog is not None:
            preview_dialog.close()
            preview_dialog.deleteLater()
        window.hide()
        window.deleteLater()
        app.processEvents()
        store.close()


if __name__ == "__main__":
    main()
