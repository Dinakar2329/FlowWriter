"""Render the action wheel and the result card from synthetic data (for docs and visual checks).

Run: python scripts/preview_overlays.py --output-dir docs/screenshots
No hooks, API requests, keychain calls or real application data are used.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from flowwriter.overlay import PreviewPopupCard
from flowwriter.radial import RadialMenuWindow
from flowwriter.storage import Store
from flowwriter.styles import configure_theme


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_theme(app)
    with TemporaryDirectory(prefix="flowwriter-preview-") as temporary:
        store = Store(Path(temporary) / "preview.db", Fernet(Fernet.generate_key()))
        wheel = RadialMenuWindow()
        wheel.set_actions(store.actions())
        wheel.show()
        card = PreviewPopupCard()
        card.show_loading(QPoint(100, 100), "Polish")
        card.show_result("Thanks for sharing your thoughts. I have updated the proposal to reflect "
                         "our conversation and would love to hear what you think.")
        card.show()

        def capture():
            wheel.is_back_face = False      # a stray scroll event can flip it; always show the front
            wheel.update()
            for name, widget in (("wheel", wheel), ("result-card", card)):
                target = args.output_dir / f"{name}.png"
                if not widget.grab().save(str(target)):
                    raise RuntimeError(f"Could not save {target}")
                print("Saved", target)
            app.quit()

        QTimer.singleShot(500, capture)
        app.exec()
        wheel.hide()
        card.hide()
        store.close()


if __name__ == "__main__":
    main()
