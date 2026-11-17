import sys
import time

import pytest

from flowwriter import winhotkey
from flowwriter.winhotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, WindowsHotkey, to_windows


def test_combination_maps_to_windows_flags_and_key_codes():
    assert to_windows("Ctrl+Alt+Space") == (MOD_CONTROL | MOD_ALT, 0x20)
    assert to_windows("Ctrl+Shift+K") == (MOD_CONTROL | MOD_SHIFT, ord("K"))
    assert to_windows("Ctrl+Alt+7") == (MOD_CONTROL | MOD_ALT, ord("7"))
    assert to_windows("Ctrl+F9") == (MOD_CONTROL, 0x78)
    assert to_windows("Ctrl+Meta+Left") == (MOD_CONTROL | MOD_WIN, 0x25)
    assert to_windows("Ctrl+Alt+;", vk_scan=lambda ch: 0x01BA) == (MOD_CONTROL | MOD_ALT, 0xBA)
    with pytest.raises(ValueError):
        to_windows("K")                      # too easy to hit while typing


@pytest.mark.skipif(sys.platform != "win32", reason="uses the Windows shortcut registry")
def test_second_owner_of_a_shortcut_is_told_it_is_taken_and_stop_releases_it():
    combo = "Ctrl+Alt+Shift+F23"
    hits = []
    first = WindowsHotkey(combo, lambda: hits.append(1))
    assert first.start() == ""
    second = WindowsHotkey(combo, lambda: None)
    assert "already used by another app" in second.start()
    first.stop()
    third = WindowsHotkey(combo, lambda: None)
    try:
        assert third.start() == ""           # released by stop()
    finally:
        third.stop()
