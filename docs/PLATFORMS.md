# Platform matrix (v0.9.0)

| Capability | Windows | macOS | Linux X11 | Linux Wayland |
|---|---|---|---|---|
| Native PySide6 dashboard | Expected | Expected | Expected | Expected with Qt plugin setup |
| Provider API/SQLite/History | Shared Python | Shared Python | Shared Python | Shared Python |
| Scratchpad transformations | Shared Python | Shared Python | Shared Python | Shared Python |
| Hold-and-drag selection hook (key combination configurable) | pynput, test required | pynput + Accessibility permission | pynput, X server + DISPLAY | Partial: XWayland apps may work only |
| Clipboard capture | Qt + synthetic Ctrl+C | Qt + synthetic Cmd+C | Qt + synthetic Ctrl+C | App-specific |
| Replace after approval | Validated target algorithm; *manual QA required* | Copy-only fallback | Copy-only fallback | Copy-only fallback |
| Tray icon | Expected | Expected | Depends on desktop shell | Depends on desktop shell |

Because global input and selection access is restricted by OS security policy, the Python source can be run cross-platform while **global capture/replace does not have identical guarantees on every OS**. In particular, Wayland globally restricts event access and may require dedicated compositor portals. We do not bypass OS protection or ask users to run as root.

On macOS, grant Accessibility permissions to the **executable actually receiving input**, which might be the Terminal/Python interpreter in source mode or the packaged application in binary mode.

Reference: https://pynput.readthedocs.io/en/latest/limitations.html
