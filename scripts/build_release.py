"""Build an unsigned native bundle on the OS where it will run.

The result is a platform-specific executable or .app produced by PyInstaller.
Cross-compilation is intentionally not claimed or supported.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_arguments(icon_path=None):
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--onedir", "--name", "FlowWriterStudio", "--collect-all", "pynput",
        "--collect-all", "keyring", "--collect-all", "cryptography",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if icon_path is not None:
        args += ["--icon", str(icon_path)]
    return args + [str(ROOT / "run.py")]


def main():
    icon_path = None
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from flowwriter.icons import write_app_ico
        app = QApplication.instance() or QApplication([])
        icon_path = ROOT / "build" / "flowwriter.ico"
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        write_app_ico(icon_path)
    args = build_arguments(icon_path)
    print("Building a platform-specific, unsigned FlowWriter Studio bundle")
    subprocess.run(args, cwd=ROOT, check=True)
    print("Finished. See:", ROOT / "dist" / "FlowWriterStudio")

if __name__ == "__main__":
    main()
