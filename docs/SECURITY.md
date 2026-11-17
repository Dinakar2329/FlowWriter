# Security & privacy model

**Default:** selected input, transformed output and instruction are encrypted in SQLite using Fernet before persistence; secret key is saved in OS keychain. History is disabled when secure key storage cannot be established. Provider API keys go to OS keyring and are held in memory during requests. No user content is sent until the user runs an action.

- **Trust boundary:** selected text may contain malicious instructions. The prompt explicitly labels it as untrusted data, though LLM prompt-injection resistance is not guaranteed.
- **Transport:** API keys only travel over HTTPS or localhost HTTP. Keyless LAN inference supports HTTP. A compromised local model or endpoint can still access everything sent to it.
- **Clipboard:** selection capture and replacement temporarily use the system clipboard and try to preserve all Qt-exposed MIME formats. Other apps may observe clipboard changes. Clipboard restoration intentionally refrains from overwriting a newer unrelated clipboard value.
- **Target safety:** on Windows only, the source window handle is reactivated and selected text re-copied. The app refuses paste if either check fails. An editor can still reject synthetic paste or corrupt rich-text formatting; use Copy manually when uncertain. On Linux/macOS, automatic replacement is disabled for this release.
- **Global input hooks:** to detect the chosen shortcut the app listens to key presses and mouse clicks system-wide. It only uses which modifier keys are held (Ctrl/Alt/Shift/Cmd), the Esc key, the configured global key and left-button drag distance; typed characters are not read, stored or sent. Hooks are removed on Quit.
- **Where the shortcut fires:** selection capture sends Ctrl+C (Cmd+C on a Mac) to the foreground app. That interrupts a program in a terminal and copies files in a file manager, so terminals, file managers and the desktop are skipped by default (Shortcuts, Windows only). Common password managers are excluded by default (Privacy). Both lists can be changed.
- **Prompt boundary:** the selected text is wrapped in a tag with a random name made for each request, so the text cannot close the block early. This lowers, but does not remove, prompt-injection risk; the result still needs your approval before it replaces anything.
- **Limits:** a request ends after 300 s in total or 120 s of silence; a reply over 1,000,000 characters or 8 MB is stopped; selected text over 50,000 characters is refused. Cancel closes the connection.
- **Environment key:** `FLOWWRITER_API_KEY` is only sent to localhost or to the URL in `FLOWWRITER_API_KEY_URL`.
- **API key in the interface:** a saved key is not loaded into the form. It is read from the keychain only when you click Show.
- **Memory:** while a history entry is on screen its text is held in plain form in widget memory. Only the visible page (10 entries) is decrypted. Text search decrypts in batches and keeps only the matching ids.
- **Sensitive controls:** the application cannot reliably identify all password/secure fields across arbitrary applications. Window-title exclusions are a user-controllable mitigation, not a guarantee. Do not process secrets, financial credentials, private chat messages or protected records without the necessary organizational authorization.
- **Local storage:** content encrypted; metadata such as model IDs and action/status/timestamps not encrypted; window titles are encrypted. Full disk encryption is recommended. Backing up only the SQLite file is insufficient without a matching history key.
- **Private mode:** prevents **new SQLite history entries**, not model API calls or clipboard access.
- **No telemetry, tracking, background service or local HTTP endpoint** is started by the main application; the optional mock server binds only to 127.0.0.1 when manually launched.
- **Logging:** no raw text or provider errors are written to disk by default. No custom crash reporter.
- **Dependencies:** use trusted package sources. PyInstaller app bundles remain unsigned until a maintainer signs them with a code-signing certificate (not done: no certificate is held). CI actions are pinned to commit hashes, the workflow has read-only permissions, and `requirements.lock` pins every dependency with hashes (regenerate with `uv pip compile pyproject.toml --extra test --extra build --universal --generate-hashes --python-version 3.12 -o requirements.lock`). PySide6 uses Qt's open-source licensing terms; validate obligations when redistributing.

## Known gaps before an enterprise production rollout

User-specific application exclusions, secure-field detection, macOS/Linux target restoration, clipboard-format fidelity, transactional replacement of rich editors, cross-platform packaging/signing, monitoring of security releases, and manual QA remain required. The source archive is a technical preview/release candidate, not certified enterprise software.
