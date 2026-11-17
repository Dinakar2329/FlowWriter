# Advanced guide

Details that do not belong on the front page: how selection and replacement behave, where data lives,
encryption keys, a zero-cost test server, and building the executable.

## Text selection flow

By default **hold Ctrl (Cmd on macOS) while drag-selecting text** (20+ pixels), or press `Ctrl + Alt + Space` (`Cmd + Option + Space` on macOS) after a selection. Both can be changed or turned off in **Shortcuts**: pick another modifier combination for hold-and-drag, record your own global key, and choose whether terminals, file managers and the desktop are skipped (they are by default). Changes apply straight away. The circular wheel appears, actions can be changed in the Actions screen, and its center opens Custom Prompt.

When the model finishes, you may revise the text before choosing:

- **Approve & replace:** only performs a verified-target paste on Windows, after restoring the original source and re-copying the selected text to check it still matches. This is a conservative best-effort operation; an editor can still refuse synthetic paste or alter formatting. If verification fails, nothing is pasted and the card offers Copy Result.
- **Copy result:** copies the edited output into the clipboard, so it can be pasted manually into any app. Supported on Windows/macOS/Linux where Qt clipboard is available.
- **Discard:** does not change the source text.

**macOS and Linux currently use Copy Result instead of direct replacement** because target restoration has not been safely implemented/tested there. Password fields and custom editors are not guaranteed detectable; configure title exclusions under Privacy and avoid selecting secrets.

## Scratchpad and history

Scratchpad lets you type/paste any text without using global selection, choose an action, customize an instruction and transform it. History shows decrypted results ten per page with a numbered pager. The status filter runs in SQL. Text search covers **every saved entry**; because content is encrypted it cannot use a database index, so it decrypts in small batches on a background thread, shows progress, and keeps nothing readable afterwards. The underlying SQLite database retains all entries unless deleted.

SQLite content columns (`input`, `output`, `instruction`) are encrypted, while metadata such as timestamps, action names, model IDs and status remain readable; source window titles are encrypted. Encryption protects the database file at rest but **does not replace full-disk encryption**, nor does it prevent the operating system or other apps with access to your live session from reading clipboard text. Never commit the data directory or environment keys to source control.

If the OS keychain is not available, FlowWriter does **not** store sensitive text in plaintext. Enable an OS Secret Service (on Linux), or supply a stable `FLOWWRITER_HISTORY_KEY` environment variable, generated with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep that key private and backed up securely. It must be **the same for every restart**. Losing or changing the key makes saved text unreadable; the app will not silently overwrite old encrypted history. On shared machines, use your own OS account and enable full-disk encryption.

Application data resides in:

- Windows: `%LOCALAPPDATA%\FlowWriterStudio\flowwriter.db`
- macOS: `~/Library/Application Support/FlowWriterStudio/flowwriter.db`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/flowwriter-studio/flowwriter.db`

Override storage path for testing/portable profiles with `FLOWWRITER_DATA_DIR`. Provider keys are not saved in that database. `FLOWWRITER_API_KEY` is a session fallback when no provider key was saved. It is only sent to a local server (localhost / 127.0.0.1), or to the exact base URL named in `FLOWWRITER_API_KEY_URL`; it is never sent to other providers you add.

## Test with zero API cost

In a separate terminal run:

```bash
python scripts/mock_provider.py
```

Then add a provider with base URL `http://127.0.0.1:8765/v1`, model `mock-text-model`, **no API key**, and click Test. It responds with labeled mock text instead of using an LLM; both streaming and non-streaming work. Use model ID `mock-thinking-model` to see the "Thinking…" step that reasoning models show. This is designed to check UI, providers, SQLite and the full approval flow without model charges.

## Create a per-OS executable bundle

On Windows, double-click **`Build-Desktop-App.cmd`**. It installs the declared build/test dependencies, runs checks, builds the windowed app with its own icon, and creates a desktop shortcut, then waits for a key press and opens the new app (`--no-pause` skips both). The result is `dist\FlowWriterStudio\FlowWriterStudio.exe`; Python is not required on a machine running that bundle. Keep the entire `FlowWriterStudio` output folder together. The build machine needs Python 3.11+ and internet access for dependencies on the first build.

For a build without a desktop shortcut or a final pause:

```powershell
.\Build-Desktop-App.cmd --no-shortcut --no-pause
```

The app uses a contrast-safe badge in the taskbar/tray. Windows 11's native title bar takes the same light color as the app; other operating systems retain their supported native frame behavior. Existing pinned shortcuts can retain Windows' cached icon: unpin the old shortcut and pin the new executable if needed.

From a virtualenv on the actual operating system:

```bash
python -m pip install -e ".[build,test]"
python -m pytest -q
python scripts/build_release.py
```

Outputs an unsigned `dist/FlowWriterStudio` app directory (macOS may produce `FlowWriterStudio.app`). **PyInstaller cannot cross-build:** building for Windows requires Windows, macOS requires macOS, and Linux requires Linux. The included GitHub Actions workflow can produce unsigned artifacts on all three OS families after the repository is pushed to GitHub.

Before distributing to users, complete OS-level interaction QA, installer signing/notarization, vulnerability review and package smoke tests. The signed multi-OS installers are **not** bundled with this source ZIP.

The bundled executable accepts `--smoke-test` for an offscreen check using disposable encrypted data, without global hooks, live app data, keychain access or API calls.

## Publishing a release (maintainers)

The GitHub Actions workflow tests and builds the app on Windows, macOS and Linux for every push and pull request, and keeps each build as a downloadable artifact.

To publish a release, push a version tag:

```bash
git tag v0.9.0
git push origin v0.9.0
```

When all three builds pass, the workflow creates a **pre-release** with the three zip files attached (`FlowWriterStudio-Windows.zip`, `-macOS.zip`, `-Linux.zip`). The builds are unsigned, so Windows may show a SmartScreen warning. Edit the release notes on GitHub if you want to say more.
