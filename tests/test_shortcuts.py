import pytest
from cryptography.fernet import Fernet

from flowwriter import shortcuts
from flowwriter.shortcuts import Shortcuts
from flowwriter.storage import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "s.db", Fernet(Fernet.generate_key()))
    yield s
    s.close()


@pytest.mark.parametrize("text", ["Ctrl+Alt+Space", "Ctrl+Shift+K", "Alt+F8", "Ctrl+F9", "Ctrl+Alt+7", "Ctrl+Alt+Shift+Q"])
def test_good_hotkeys_are_accepted(text):
    assert shortcuts.validate_hotkey(text)


@pytest.mark.parametrize("text,reason", [
    ("", "one key"),
    ("Space", "Ctrl, Alt"),                 # no modifier
    ("Shift+K", "Shift alone"),             # would fire while typing
    ("Ctrl+C", "two modifier"),             # the key the app itself sends
    ("Ctrl+V", "two modifier"),
    ("Ctrl+A", "two modifier"),
    ("Ctrl+Alt", "one key"),                # modifiers only
    ("Ctrl+Alt+Esc", "Esc"),                # Esc closes the wheel
    ("Ctrl+Alt+A+B", "one key"),
    ("Ctrl+Alt+Nonsense", "cannot be used"),
])
def test_unsafe_hotkeys_are_refused_with_a_plain_reason(text, reason):
    with pytest.raises(ValueError) as caught:
        shortcuts.validate_hotkey(text)
    assert reason.lower() in str(caught.value).lower()


def test_hotkey_conversion_for_pynput(monkeypatch):
    monkeypatch.setattr(shortcuts, "MAC", False)
    assert shortcuts.hotkey_to_pynput("Ctrl+Alt+Space") == "<ctrl>+<alt>+<space>"
    assert shortcuts.hotkey_to_pynput("ctrl + shift + k") == "<ctrl>+<shift>+k"
    assert shortcuts.hotkey_to_pynput("Alt+F8") == "<alt>+<f8>"
    assert shortcuts.hotkey_to_pynput("Ctrl+Alt+Del") == "<ctrl>+<alt>+<delete>"
    monkeypatch.setattr(shortcuts, "MAC", True)
    assert shortcuts.hotkey_to_pynput("Ctrl+Alt+Space") == "<cmd>+<alt>+<space>"  # Qt's Ctrl is Cmd on a Mac


def test_modifier_names_and_exact_drag_match():
    assert shortcuts.modifier_name("ctrl_l") == "ctrl"
    assert shortcuts.modifier_name("alt_gr") == "alt"
    assert shortcuts.modifier_name("cmd_r") == "cmd"
    assert shortcuts.modifier_name("space") is None
    assert shortcuts.drag_matches({"ctrl"}, {"ctrl"})
    assert not shortcuts.drag_matches({"ctrl"}, {"ctrl", "shift"})   # a different gesture
    assert not shortcuts.drag_matches({"ctrl", "alt"}, {"ctrl"})
    assert not shortcuts.drag_matches(frozenset(), set())            # off never matches
    assert not shortcuts.drag_matches(frozenset(), {"ctrl"})


def test_choices_never_offer_shift_alone():
    labels = [text for text, _ in shortcuts.drag_choices()]
    assert "Shift" not in labels and labels[-1] == "Off"
    assert len(labels) == len(set(labels))


def test_defaults_match_the_original_behaviour(store):
    value = shortcuts.load(store)
    assert value == Shortcuts()
    assert value.drag == shortcuts.DEFAULT_DRAG and value.hotkey == "Ctrl+Alt+Space" and value.skip_special_windows


def test_settings_round_trip_and_off_is_remembered(store):
    chosen = Shortcuts(frozenset({"alt", "shift"}), "Ctrl+Shift+K", False)
    shortcuts.save(store, chosen)
    assert shortcuts.load(store) == chosen
    off = Shortcuts(frozenset(), "", True)
    shortcuts.save(store, off)
    loaded = shortcuts.load(store)
    assert loaded.drag == frozenset() and loaded.hotkey == ""        # "off" is not mistaken for "unset"
    assert "No shortcut is on" in loaded.describe()


def test_a_bad_saved_hotkey_falls_back_instead_of_breaking_start(store):
    store.set_pref("hotkey", "Ctrl+C")
    assert shortcuts.load(store).hotkey == shortcuts.DEFAULT_HOTKEY
    with pytest.raises(ValueError):
        shortcuts.save(store, Shortcuts(frozenset(), "Ctrl+C", True))


def test_description_is_plain_english():
    text = Shortcuts(frozenset({"alt"}), "Ctrl+Alt+Space", True).describe()
    assert text.startswith("Hold") and "drag-select" in text and "Ctrl+Alt+Space" in text
