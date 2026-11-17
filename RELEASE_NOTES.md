# FlowWriter Studio v0.9.0 — desktop source release candidate

## Latest changes
- **Writing sources** (Insights) are grouped by app (Excel, Outlook, Microsoft Teams…). Click an app to fade in its details in the same card: transformations, words, results used, last 14 days, most-used actions and the window titles you wrote in. The app is read from the end of the window title, so it works for saved history without a migration.
- **Buttons**: icon and text are drawn as one centred group with an even 8 px gap; slightly heavier icon strokes; "Start writing" uses a pen icon and "Transform text" a sparkles icon.
- **Check boxes** now draw a dark box with a white tick (they were filled with the Windows accent colour and the tick could not be seen). The Windows accent colour is also kept out of other native controls.
- **Global shortcut on Windows** is registered with Windows itself. If another app already uses the combination, Shortcuts says so and you can pick another; while FlowWriter holds it, other apps no longer open from the same keys.
- New **Prompt** action on the front of the wheel: turns rough text into a structured prompt (Role, Task, Context, Requirements, Output format) without answering it. Added once to existing databases (schema 2); delete or edit it freely. Up to 8 actions per face.

## Changes after the review
- New **Shortcuts** page: choose the hold-and-drag modifier keys, record your own global key, skip terminals and file managers. Applies without a restart.
- Streaming is now visible: the floating card shows the reply as it is written, with a "Thinking…" step for reasoning models. Cancel stops the model server too.
- Recent transformations and History are paged (10 per page). History search covers every saved entry.
- Overview refresh no longer decrypts up to 1,300 rows (0.41 s freeze per refresh).
- Security: random prompt boundary, time and size limits on replies and input, environment API key no longer sent to other providers, saved key no longer loaded into the form, pinned CI actions and a hashed lock file.
- Consistency: one status vocabulary, one date format, page names match the sidebar, lining digits, better contrast, a real on/off look for Private mode.

The radial menu is inspired by Filee's. The wheel, result card and everything around them are original to this project. New local SQLite history dashboard, prompt action manager, OpenAI-compatible Chat Completions transport, multiple profiles, encryption/keyring integration, cancellation support, private mode, and safe copy/replacement paths are included.

## Validation completed in current environment
- Python source syntax: pass.
- Provider client + real loopback mock server: pass.
- Encrypted history and key management: pass.
- Replacement refusal on target mismatch and stale sessions: pass.
- 167 tests pass on Windows (Python 3.12, PySide6 6.12) as of November 17, 2026, including offscreen UI tests. The continuous-integration workflow has not yet run on macOS or Linux.

## Unverified before a production rollout
- Desktop Qt rendering and interactions in actual OS environments.
- Global input monitoring and permission setup on Windows/macOS/X11/Wayland.
- Windows verified-target paste reliability with real external editors.
- PyInstaller binaries on each target platform, signing and notarization.
- Security assessment for your particular model endpoint and organization.

This source distribution is runnable where dependencies are installed. It is **not** a signed installer or an enterprise-certified build.
