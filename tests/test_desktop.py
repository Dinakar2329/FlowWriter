"""Packaging arguments and Windows theme contracts; no real target is changed."""
import ctypes
from pathlib import Path


def test_native_titlebar_uses_light_neutral_colors(monkeypatch):
    from flowwriter import windows
    from types import SimpleNamespace
    calls = []
    def attribute(hwnd, key, pointer, size):
        value = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value
        calls.append((hwnd, key, value))
        return 0
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.ctypes, "WinDLL", lambda name: SimpleNamespace(DwmSetWindowAttribute=attribute), raising=False)
    assert windows.apply_titlebar(123456789012)
    assert calls == [(123456789012, 20, 0), (123456789012, 35, 0xF5F5F5),
                     (123456789012, 36, 0x262626), (123456789012, 34, 0xE5E5E5)]


def test_unsupported_titlebar_api_is_optional(monkeypatch):
    from flowwriter import windows
    monkeypatch.setattr(windows.sys, "platform", "linux")
    assert not windows.apply_titlebar(1)


def test_build_includes_windowed_executable_and_badge():
    from scripts.build_release import build_arguments, ROOT
    icon_path = ROOT / "build" / "flowwriter.ico"
    args = build_arguments(icon_path)
    assert "--windowed" in args
    assert "--onedir" in args
    assert args[args.index("--icon") + 1] == str(icon_path)
    assert args[-1] == str(ROOT / "run.py")
