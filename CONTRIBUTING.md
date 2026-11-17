# Contributing

Thanks for helping. Bug reports, fixes, docs and ideas are all welcome.

## Set up

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q
```

The tests run without a display, a model endpoint or an OS keychain. Please run them before opening a pull request.

## Guidelines

- **Keep changes small and focused.** One fix or feature per pull request.
- **Add a test** for behaviour you change. UI changes should include a screenshot from `scripts/preview_ui.py` (synthetic data only).
- **Never include real data** in issues, screenshots or tests: no personal text, API keys, window titles or file paths.
- **Privacy rules are firm.** No telemetry, no sending text anywhere except the user's chosen model endpoint, and no storing readable text on disk.
- **Icons** come from Lucide. To add one, edit `ICONS` in `scripts/fetch_icons.py` and run it. Do not edit `flowwriter/lucide_icons.py` by hand.
- **Platform claims** should match what you tested. If you could only test on one system, say so.

## Reporting a security problem

Please do not open a public issue for a vulnerability. Contact the maintainers privately through the repository's security advisory feature.
