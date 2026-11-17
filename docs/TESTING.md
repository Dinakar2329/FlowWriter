# Test plan and release gates

## Automated tests

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests
python -m compileall -q flowwriter
```

Covered:
- SQLite migration, encryption, readback, status transitions, delete and privacy mode.
- User profiles/actions persistence after reopening a DB.
- Secret storage and absence of plaintext fallback when keychain unavailable.
- OpenAI Chat Completions request fields, responses, SSE streaming, model-agnostic ID, cancellation, auth/HTTP errors and insecure API-key transport rejection.
- Selection replacement never pastes after target mismatch.
- Real HTTP E2E against a localhost mock server (no paid API calls).
- Offscreen dashboard navigation, transformation submission, clipboard actions, history search/filter/favorite/reuse, privacy summaries and empty states (only if PySide6 installed).
- Layout bounds for all eight screens at 920×620, 1360×880 and 1920×1080; scalable vector icon rendering at 1×/2×; preview footer bounds, edited-output copying and replacement-failure controls.
- Insights analytics tests cover all-history batching beyond 800 entries, refresh snapshot boundaries, failed/cancelled/unused result denominators, locked content, local dates and streaks. UI tests cover both Insights tabs, calendar colors and keyboard navigation, privacy/deletion refresh and error recovery.

## Repeatable UI previews

```powershell
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/overview.png
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/empty-overview.png --empty
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/compact.png --width 920 --height 620
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/scratchpad.png --page 2
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/insights.png --page 6
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/insights-writing.png --page 6 --insights-tab writing
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/transformation-details.png --dialog details
.\.venv\Scripts\python.exe scripts/preview_ui.py --output out/delete-confirmation.png --dialog delete
```

The script uses a disposable encrypted database, synthetic history and a fake keychain. It starts no OS hooks and makes no API calls. Page indices follow Overview (0), History (1), Scratchpad (2), Actions (3), Providers (4), Privacy (5), Insights (6), Shortcuts (7). Add `--native` to render with the real Windows style instead of the offscreen one, and `--open-app N` (with `--page 6`) to open an app's details in Writing sources. `scripts/preview_overlays.py` renders the action wheel and result card. The Privacy page prints the storage path, so do not publish its screenshot. Insights previews add deterministic synthetic activity across 26 weeks; `--empty` skips all sample data. On other platforms, use the equivalent virtualenv Python executable. Do not use screenshot fixtures to claim native input-hook or third-party editor support.

Earlier Insights validation on November 14, 2026: **45 tests passed** with PySide6 6.12.0 on Windows; Python compilation passed. Offscreen previews were inspected, including empty, compact and 150% scale layouts. The current packaging/reliability coverage is listed below.

Windows packaging/reliability pass: **64 tests**, covering paginated history beyond 800 rows, scroll-triggered feed loading, rounded workspace corners, pointer-transparent scroll fades, small/large badge contrast, multi-resolution ICO output, positive font point sizes, clipboard contention/modifier waits, clipboard version races, target changes and disabled-approval shortcuts. Native Windows construction produced no `QFont::setPointSize` warnings. All four native DWM attribute setters returned success on the test host; explicit caption colors require Windows 11.

Review-fix pass: **150 tests passed**, plus `compileall` and `python -m flowwriter --smoke-test`. New coverage: `tests/test_streaming.py` (a real local HTTP server that behaves like Ollama: words arrive one by one over time, reasoning tokens, `<think>` blocks split across chunks, in-stream errors, Cancel on a stalled stream returning in under 2 s, total-time limit, reply and input size limits, random prompt boundary); `tests/test_shortcuts.py` (validation, pynput conversion, exact modifier matching, saved settings, "off" kept distinct from "unset"); `tests/test_controller.py` (stream to the card, thinking state, scratchpad refresh once, cancel, stale results, failure and retry, replace success and failure, discard and copy, environment-key rules, terminal and excluded-title skipping, live shortcut change, repeat shutdown, and a real client streaming into the real card); `tests/test_ui_features.py` (History pages and background search, page clamping, one status vocabulary, page names, refresh decrypts at most one page, date handling, providers form keeps edits and does not load the saved key, system-shutdown close, Private-mode switch, Shortcuts page, streaming card); and storage tests for search, status filters and `daily_counts`. Checked by hand with the real global hooks: register, change, turn off and stop the hotkey.

Not covered by automation: a real Ctrl+drag in Excel, Explorer and a terminal; a real Windows shutdown; a real Ollama reasoning model (no model is installed on the build machine, so Ollama's stream format is imitated by the test server).

Recent-transformations pagination pass: **78 tests passed**. New coverage: numbered pages without gaps or duplicates, pager hidden for one page, page kept on refresh and clamped after deletes, inner scrollbar and fades, wheel chaining from the list to the page, compact-height behaviour, page-number windowing, and `history_page(offset)` / `history_count()` in storage.

Latest selection/dialog pass: **71 tests passed**, compilation passed, and the executable under `dist/ui-update/FlowWriterStudio` passed its isolated packaged smoke check. Coverage includes removal of native selection frames while preserving keyboard navigation, readable dialogs under a dark palette, safe No defaults, Yes/No deletion decisions, Escape cancellation, and parentless messages. Rendered dialog previews and a native Windows dark-palette check were also verified.

The Windows CMD build was exercised with `--no-shortcut --no-pause`; it produced the executable and embedded icon. The final packaged executable is checked with `--smoke-test`. Desktop-shortcut creation is left to the user-run script; it was not written to the desktop during automated validation. This remains an unsigned folder bundle, not a signed installer.

Clipboard tests use an in-memory clipboard and fake native targets. They do not certify replacement behavior in every real editor. For native QA, repeat steps 6–9 below with gesture keys released, including a clipboard manager or slow editor. Confirm copy fallback and retry work during transient contention, and newer clipboard content is preserved after the delayed restoration window.

## Manual smoke (required before external deployment)

1. Launch on Windows/macOS/Linux. Main dashboard opens without a traceback; close window -> tray persists; Quit exits. Check second app process is blocked.
2. Configure no-key `mock-text-model` at `http://127.0.0.1:8765/v1` and run an action in Scratchpad; test both streaming enabled and disabled. Confirm non-empty transformed output.
3. Run `python scripts/mock_provider.py`; configure its connection. Restart app, ensure model profile persists.
4. Check history entry is persisted and can be searched, viewed, favorited, reused, copied and deleted. Confirm raw SQLite file does not include literal text.
5. Add a custom prompt action to the second radial face. Flip via scroll and test custom center prompt.
6. Select ordinary text in a disposable Notepad document with Ctrl+drag. Verify wheel, preview, Discard leaves original unchanged, Copy result works, and validated Replace operates only on the same selection.
7. Change target selection *after* generation but *before* approval. Verify app does **not** replace unrelated text.
8. Close the source editor during inference, then click Approve; confirm Copy fallback, no blind paste.
9. Test in browsers, VS Code, Outlook and rich editors. Where source validation fails, Copy fallback must work.
10. Test private mode and excluded window titles: new history entries are not created and excluded windows don't trigger selection capture.
11. Test API failure modes: invalid URL, model 404, missing/incorrect API key, offline model, timeout, streaming disconnect, user cancellation.
12. Test keychain unavailable (Linux without Secret Service). Privacy UI must warn and new sensitive history must not be written.
13. Test display scaling, multiple monitors, session lock/unlock and app restart.
14. Build platform-specific PyInstaller bundle and repeat launch/kill/restart/manual checks **on each OS**. Sign/notarize builds before public rollout.

## Validation status for the source release

- Python syntax compilation: checked.
- Backend unit/integration tests: checked.
- Original ZIP build: Qt UI and OS global hook tests were **not run in the build container** (PySide6 package unavailable, network disabled). Current source has the offscreen UI validation above; native OS integration remains a manual release gate.
- Signed native installer for Windows, macOS or Linux: **not generated**.

A successful automated test run is not equivalent to verifying third-party editors or OS input permissions.
