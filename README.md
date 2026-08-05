# Aashi

Aashi is a modular, local-first, cloud-enhanced personal AI desktop companion for Windows.

## Status

Early foundation stage. Module **UI-01 (Project Foundation)** is complete: package
structure, configuration and path management, and a minimal PySide6 bootstrap that
opens a temporary "Aashi UI Foundation" window. This temporary window is **not** the
real Aashi interface; it only proves that the foundation works. Later UI modules will
replace it.

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

For a runtime-only install use `pip install -r requirements.txt` instead.

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
  ui/              desktop UI; subpackages are boundaries for future modules
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
