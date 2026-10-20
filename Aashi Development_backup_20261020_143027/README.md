# Aashi

Aashi is a modular, local-first, cloud-enhanced personal AI desktop companion for Windows.

## Status

Aashi is an existing PySide6 desktop chat application with SQLite conversation and
project persistence, local Ollama/OpenRouter routing, image/document attachments,
themes, and an emotion presentation layer. The desktop-assistant slice now adds a
long-lived shell, compact floating mode, optional tray lifecycle, structured and
permission-checked folder/application actions, change-aware foreground screen
monitoring, modular speech ports, proactive policy gates, supported test execution,
user-facing privacy settings, and explicit non-sensitive memory storage. See
[docs/desktop-assistant.md](docs/desktop-assistant.md) for architecture,
configuration, security boundaries, and verified limitations.

## Requirements

- Python 3.12+
- Windows 11 (primary target; development also works on other platforms)

## Setup

From the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

For a runtime-only install use `pip install -r requirements.txt` instead. Talking
mode is optional and can be enabled with `python -m pip install -e ".[voice]"`.

## Running

```powershell
python -m aashi        # run Aashi (environment auto-detected)
python run_dev.py      # run Aashi forcing the development environment
aashi                  # installed GUI launcher (after pip install)
```

## Testing

```powershell
pytest
```

## Project structure

```
src/aashi/         application package (src layout)
  app.py           QApplication bootstrap and entry point
  constants.py     application-wide constants
  paths.py         centralized path management
  config/          configuration foundation (Environment, Settings)
  automation/      permission boundary, file/app/screen/speech/proactive services
  ui/              desktop UI, chat surface, and desktop shell
assets/            bundled static assets (icons, fonts, images)
config/            bundled environment configuration (TOML)
docs/              project and module documentation
tests/             pytest test suite
```

## Configuration and data locations

- `AASHI_ENV` selects the environment: `development` or `production`.
  Unset: frozen/packaged builds default to production, source runs to development.
- Bundled config is read from `config/<environment>.toml`.
- Per-user writable data (logs, application data) lives under
  `%LOCALAPPDATA%\Aashi` on Windows; override with `AASHI_DATA_DIR`.
- No secrets or API keys are stored in configuration files.

## Documentation

Module records live in `docs/modules/`. The authoritative Aashi specifications
(Architecture, UI/UX) should be placed under `docs/` when available.

The current desktop-assistant implementation and user instructions are in
`docs/desktop-assistant.md`.
