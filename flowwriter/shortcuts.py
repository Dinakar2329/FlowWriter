"""User-chosen ways to open the action wheel, kept free of Qt and pynput so they are easy to test.

Two triggers exist:
  * hold modifier keys and drag-select text (the original behaviour), and
  * press a global key combination.
Each can be changed or turned off in Shortcuts. Settings are saved in the
preferences table and applied right away, without a restart.
"""
from __future__ import annotations
from dataclasses import dataclass
import sys

MAC = sys.platform == "darwin"
PRIMARY = "cmd" if MAC else "ctrl"          # the key the app has always used for drag-select
DEFAULT_DRAG = frozenset({PRIMARY})
DEFAULT_HOTKEY = "Ctrl+Alt+Space"            # Qt text: Ctrl is the Cmd key on a Mac

_NAMES = {"ctrl": "Cmd" if MAC else "Ctrl", "alt": "Option" if MAC else "Alt", "shift": "Shift", "cmd": "Cmd"}
_ORDER = ("ctrl", "cmd", "alt", "shift")


def drag_label(modifiers) -> str:
    return " + ".join(_NAMES[m] for m in _ORDER if m in modifiers) or "Off"


def drag_choices() -> list[tuple[str, frozenset]]:
    """Combinations offered for hold-and-drag. Shift alone is left out: it extends selections everywhere."""
    p = PRIMARY
    options = [frozenset({p}), frozenset({"alt"}), frozenset({p, "alt"}), frozenset({p, "shift"}), frozenset({"alt", "shift"})]
    return [(drag_label(o), o) for o in options] + [("Off", frozenset())]


def modifier_name(key_name: str) -> str | None:
    """'ctrl_l' / 'alt_gr' / 'cmd_r' -> 'ctrl' / 'alt' / 'cmd'. Other keys give None."""
    for base in ("ctrl", "alt", "shift", "cmd"):
        if key_name == base or key_name.startswith(base + "_"):
            return base
    return None


def drag_matches(required, held) -> bool:
    """True when exactly the chosen modifiers are down (extra keys mean a different gesture)."""
    return bool(required) and set(held) == set(required)


# --- global hotkey -------------------------------------------------------------------
_MODS = {"ctrl", "alt", "shift", "meta"}
_NAMED = {
    "space": "<space>", "tab": "<tab>", "return": "<enter>", "enter": "<enter>",
    "backspace": "<backspace>", "del": "<delete>", "delete": "<delete>", "ins": "<insert>",
    "insert": "<insert>", "home": "<home>", "end": "<end>", "pgup": "<page_up>",
    "pgdown": "<page_down>", "up": "<up>", "down": "<down>", "left": "<left>", "right": "<right>",
}
_PUNCT = set(",./;'[]-=`\\")
_DISPLAY = {
    "space": "Space", "tab": "Tab", "return": "Return", "enter": "Enter", "backspace": "Backspace",
    "del": "Del", "delete": "Del", "ins": "Ins", "insert": "Ins", "home": "Home", "end": "End",
    "pgup": "PgUp", "pgdown": "PgDown", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
}


def parse_hotkey(text: str) -> tuple[frozenset, str]:
    """Split Qt-style text such as 'Ctrl+Alt+Space' into (modifiers, key). Raises ValueError."""
    parts = [p.strip() for p in (text or "").replace(" ", "").split("+")]
    mods, keys = set(), []
    for part in parts:
        if part.lower() in _MODS:
            mods.add(part.lower())
        elif part:
            keys.append(part)
    if len(keys) != 1:
        raise ValueError("Choose one key together with the modifier keys, for example Ctrl+Alt+Space.")
    key = keys[0]
    low = key.lower()
    if low in ("esc", "escape"):
        raise ValueError("Esc is used to close the wheel. Choose another key.")
    if not (low in _NAMED or (len(key) == 1 and (key.isalnum() or key in _PUNCT))
            or (low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24)):
        raise ValueError(f"'{key}' cannot be used as a shortcut key.")
    return frozenset(mods), key


def validate_hotkey(text: str) -> str:
    """Return the cleaned text, or raise ValueError with a plain-English reason.

    Rules keep the shortcut from firing during normal typing or from firing on the
    Ctrl+C / Ctrl+V the app itself sends: use two or more modifier keys, or one
    modifier with a function key.
    """
    mods, key = parse_hotkey(text)
    is_function_key = key.lower().startswith("f") and key[1:].isdigit()
    solid = mods - {"shift"}
    if not solid:
        raise ValueError("Include Ctrl, Alt or the Windows/Cmd key. Shift alone would trigger while typing.")
    if len(mods) < 2 and not is_function_key:
        raise ValueError("Use at least two modifier keys (for example Ctrl+Alt), or one modifier with an F key.")
    shown = [m.title() for m in ("ctrl", "alt", "shift", "meta") if m in mods]
    return "+".join(shown + [_DISPLAY.get(key.lower(), key.upper())])


def hotkey_to_pynput(text: str) -> str:
    """'Ctrl+Alt+Space' -> '<ctrl>+<alt>+<space>' for pynput's GlobalHotKeys."""
    mods, key = parse_hotkey(validate_hotkey(text))
    # Qt's Ctrl is the Cmd key on a Mac; Qt's Meta is the Control key there.
    names = {"ctrl": "<cmd>" if MAC else "<ctrl>", "meta": "<ctrl>" if MAC else "<cmd>",
             "alt": "<alt>", "shift": "<shift>"}
    out = [names[m] for m in ("ctrl", "meta", "alt", "shift") if m in mods]
    low = key.lower()
    if low in _NAMED:
        out.append(_NAMED[low])
    elif len(key) == 1:
        out.append(key.lower())
    else:
        out.append(f"<{low}>")
    return "+".join(out)


# --- saved settings ------------------------------------------------------------------
@dataclass(frozen=True)
class Shortcuts:
    drag: frozenset = DEFAULT_DRAG       # empty means hold-and-drag is off
    hotkey: str = DEFAULT_HOTKEY         # empty means the global key is off
    skip_special_windows: bool = True    # terminals, file managers and the desktop

    def describe(self) -> str:
        parts = []
        if self.drag:
            parts.append(f"hold {drag_label(self.drag)} and drag-select text")
        if self.hotkey:
            parts.append(f"press {self.hotkey} with text selected")
        if not parts:
            return "No shortcut is on. Turn one on in Shortcuts."
        sentence = " or ".join(parts)
        return sentence[0].upper() + sentence[1:] + "."  # not str.capitalize(): it would lowercase the key names


def load(store) -> Shortcuts:
    raw = store.get_pref("drag_modifiers", None)
    drag = DEFAULT_DRAG if raw is None else frozenset(m for m in raw.split("+") if m in _ORDER)
    hotkey = store.get_pref("hotkey", DEFAULT_HOTKEY)
    try:
        if hotkey:
            hotkey = validate_hotkey(hotkey)
    except ValueError:
        hotkey = DEFAULT_HOTKEY
    return Shortcuts(drag, hotkey, store.get_pref("skip_special_windows", "true") == "true")


def save(store, value: Shortcuts) -> None:
    if value.hotkey:
        validate_hotkey(value.hotkey)
    store.set_pref("drag_modifiers", "+".join(m for m in _ORDER if m in value.drag))
    store.set_pref("hotkey", value.hotkey)
    store.set_pref("skip_special_windows", "true" if value.skip_special_windows else "false")
