# Architecture

## Application overview

One native PySide6 desktop process, **not** a remote web application or microservice. The radial menu lives in `flowwriter/radial.py` and the result card in `flowwriter/overlay.py`. The dashboard in `flowwriter/dashboard.py` is a separate view of the same application state and storage.

```text
 OS foreground selection     Scratchpad / history reuse
           |                          |
    SelectionBridge               Dashboard
           |                          |
           +--> Controller <----------+
                   |
             Prompt actions
                   |
             ChatClient (httpx)
                   |
              local/remote
          /v1/chat/completions
                   |
            Preview / status
              /         \
        Copy/Discard    Verified replacement
              \         /
              Store (SQLite)
                   |
        Fernet encrypted text blobs
                   |
       Keyring secret / optional env key
```

## Key modules

- `domain.py` — immutable profile/action/session contracts, URL validation, storage paths.
- `radial.py` — circular two-faced selection menu (inspired by Filee's radial menu), reading its actions from the database.
- `overlay.py` — floating preview card with Copy result and an explicit replacement-failure state.
- `selection.py` — Qt clipboard MIME backup and native target restoration/revalidation.
- `provider.py` — OpenAI-compatible Chat Completions with live SSE streaming. It reports reasoning tokens (`reasoning` / `reasoning_content`) as a "thinking" signal and hides a leading `<think>` block. Limits: 300 s total, 120 s of silence, 1M reply characters, 8 MB per reply, 50k input characters. The request guard closes the connection on Cancel or deadline so a stalled read stops at once and the model server stops generating. A random per-request boundary wraps the selected text. Errors never include server text.
- `shortcuts.py` — Qt-free trigger settings: hold-and-drag modifier choices, global key validation and conversion for pynput, and load/save to preferences.
- `labels.py` — the one table of status names and the one date format used by every screen.
- `storage.py` — SQLite migrations, encrypted content fields, history/statuses and action/provider CRUD.
- `vault.py` — OS keychain and Fernet history encryption key, fail closed without secret persistence.
- `controller.py` — UI coordination, nonblocking daemon model workers, cancel IDs and source integration.
- `dashboard.py` + `styles.py` — overview, history, scratchpad, action library, provider management and privacy UI.
- `dialogs.py` — explicitly light transformation-details and confirmation/message dialogs. The app palette/scheme and native captions are coordinated with the widget stylesheet, including on dark desktops; confirmation return values and safe defaults retain QMessageBox semantics.
- `dashboard_widgets.py` — presentation-only history previews, banner artwork and native select controls; no storage or provider calls.
- `icons.py` — shared original SVG outline icons rendered by Qt's vector icon engine, including disabled and high-DPI rendering. No icon fonts, downloads or asset package are required.
- `insights.py` — pure aggregation contracts for words generated, completed/used results, action/source counts, local-day activity and streaks.
- `insights_ui.py` — native Insights usage/writing tabs, directly labeled composition bars and accessible daily calendar. Reads the existing store in bounded batches using an owned Qt timer; no network, new persistence, or model inference.
- `__main__.py` — single process guard and startup lifecycle.
- `windows.py` — explicitly typed Windows handles/clipboard probes, application identity and optional native title-bar colors. Unsupported platforms retain their defaults.

## Invariants

1. **Never blind paste.** On Windows, restore the same source HWND, copy the selection again and require exact match before sending Paste. On unsupported OSes or any failed validation, use Copy. No network request is part of replacement.
2. **Only a real user action transmits selected text.** Global selection capture only stores session state; the chosen radial action starts the model request.
3. **Never persist sensitive text without encryption.** If keyring/env-key unavailable, SQLite history recording stops. Metadata rows aren't written without content.
4. **No credentials in SQLite.** Keyring or in-memory session only. Do not send API keys over insecure remote HTTP.
5. **No stale responses.** Request IDs and cancellation events discard results from superseded operations.
6. **No model-specific logic.** Model is an opaque provider-supplied identifier. Only minimal Chat Completions fields are sent.
7. **History survives profile deletion.** Snapshots of provider/model/action names are stored with each transformation, not foreign-keyed to the current profiles.

## Performance and limits

- Input and output are memory resident while a model call is in progress; no background telemetry.
- SQLite WAL mode and one process guard. The History screen shows 10 cards per page. The status filter runs in SQL; a text search scans all rows in batches of 100 on a background thread (progress shown, cancelled when the query changes) and returns matching ids, then decrypts only the visible page. The overview refresh reads statistics with SQL, one page of 10 decrypted rows, and the 7-day chart from timestamps only (`daily_counts`), so it no longer decrypts up to 1,300 rows. The overview's Recent transformations card shows one numbered page (10 rows) at a time, read with `LIMIT/OFFSET` over `(created_at DESC, id DESC)` plus a `COUNT(*)`, so it covers all saved history with no cap and holds at most 10 decrypted rows in widgets. The card scrolls inside itself (`FeedScrollArea`, max 350px) and hands the mouse wheel to the page once it reaches either end. A refresh keeps the current page and clamps it if rows were deleted. `Pager` renders previous/next and a windowed list of page numbers.
- The overview feed and statistics rail stack below 1200px window width; the action editor stacks its list above the form at the same breakpoint. All eight pages scroll vertically within the desktop workspace. Overview statistics keep their all-history counts; the weekly chart counts the last seven local calendar days from timestamps.
- Insights reads all saved history, independently of the history screen's search limit. A refresh pins the current maximum record ID, then reads/decrypts up to 128 rows per timer turn. Only word counts and source/action/day/outcome totals survive aggregation; input/output text is not cached or persisted by Insights. The calendar has 182 cells and the composition charts collapse long tails into an explicit Other row.
- Insights refreshes when opened, on explicit Refresh, and when history/privacy changes while visible. An unsuccessful read preserves the previous values with a visible retry message. Missing encryption excludes unreadable records from word/source counts, with a visible qualification; metadata totals remain available.
- Qt UI remains responsive while the model uses a separate daemon Python thread. Cancel closes the connection, so streaming and non-streaming calls both stop promptly. While a reply streams, the floating card shows the text read-only (updates are limited to about 25 a second) and enables Replace only when the reply is complete.
- The Controller takes its model client, selection bridge and hook start as arguments so the request lifecycle can be tested with fakes. Global hooks track which modifier keys are held and compare them with the chosen combination exactly; the global key is re-registered when Shortcuts are saved. `shutdown()` runs once from Quit or `aboutToQuit`, and the dashboard lets a Windows shutdown/sign-out close through instead of hiding to the tray.
- Local HTTP models and cloud APIs have no artificial retry loop, preventing duplicate billed requests without explicit user action.
- Clipboard copy waits for modifier release, contention probes and a fresh clipboard revision, with target guards before and after copy. Paste rechecks the target immediately before the shortcut and defers best-effort MIME restoration for 1.2 seconds; a changed revision prevents overwriting later user clipboard operations. Qt event pumping excludes user-input events to reduce reentrant approval while servicing OLE. Issuing paste does not prove that a third-party editor accepted it.

## Future production hardening

- Native target-validation adapters for macOS, X11 and controlled web-editor integrations.
- Keyboard focus and clipboard integration QA across applications; atomic foreign-editor replacement is not generally possible.
- Native signing/notarization, accessibility permission onboarding, structured diagnostic logs, export and key migration workflow.
- OS integration and UI smoke tests in CI; tests can currently run the Qt dashboard offscreen where PySide6 is installed.
