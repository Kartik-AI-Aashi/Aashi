# UI-01 — Project Foundation

## Purpose

Establish the repository, package structure, configuration, path management and
minimal PySide6 bootstrap that every later Aashi UI module builds on. UI-01 adds
no product behaviour and no visual design.

## Scope

In scope: project structure, packaging metadata, application constants, path
management, development/production configuration, logging setup, a minimal
`QApplication` bootstrap with a temporary window, and foundation tests.

Out of scope: design tokens, themes, components, the Orb, navigation, windows,
overlays, accessibility implementation, and every non-UI subsystem.

## Layout

```
src/aashi/
  __init__.py        version — single source of truth, read by the build backend
  __main__.py        `python -m aashi`
  app.py             ApplicationContext, QApplication bootstrap, entry point
  constants.py       identity, env var names, filesystem names, logging defaults
  paths.py           AashiPaths, resolve_paths()
  logging_setup.py   configure_logging(), get_logger(), reset_logging()
  config/
    __init__.py      public surface of the configuration layer
    environment.py   Environment, detect_environment()
    settings.py      Settings, load_settings(), ConfigError
  ui/
    bootstrap.py     TEMPORARY FoundationWindow
    core/ tokens/ themes/ components/ orb/ icons/ accessibility/
    windows/ overlays/ navigation/ models/ services/ utils/
                     empty package boundaries reserved for later modules
assets/              bundled icons, fonts, images
config/              development.toml, production.toml
docs/                specifications and module records
tests/               foundation test suite
run_dev.py           development launcher (forces the development environment)
```

## Public interface

```python
from aashi import __version__
from aashi.config import ConfigError, Environment, Settings, detect_environment, load_settings
from aashi.paths import AashiPaths, is_frozen, resolve_paths
from aashi.logging_setup import configure_logging, get_logger, reset_logging
from aashi.app import ApplicationContext, create_application, create_context, main, run
```

`aashi.constants` holds application metadata and the names of every environment
variable and bundled directory Aashi uses.

## Configuration

Layered, lowest precedence first:

1. Built-in per-environment defaults in `config/settings.py`.
2. `config/<environment>.toml` (missing file is not an error).
3. Environment variables.

| Variable | Effect |
| --- | --- |
| `AASHI_ENV` | `development` / `production` (aliases: `dev`, `prod`, `release`, `debug`) |
| `AASHI_DATA_DIR` | Overrides the per-user writable data root |
| `AASHI_CONFIG_DIR` | Overrides the bundled configuration directory |
| `AASHI_LOG_LEVEL` | Overrides the log level |
| `AASHI_DEBUG` | Overrides the debug flag |

Unknown *tables* in a config file are ignored, reserving them for later modules.
Unknown *keys inside a known table* raise `ConfigError`, so typos surface at
startup. An unrecognized `AASHI_ENV` value falls back to the detected default
rather than aborting startup.

No secrets are read or stored. Credentials belong to Aashi's future secure
credential system.

## Paths

`resolve_paths()` is the only place that builds absolute paths.

| Location | Source run | Frozen build |
| --- | --- | --- |
| `bundle_root` | repository root | `sys._MEIPASS`, else the executable's directory |
| `assets_dir` | `<root>/assets` | `<bundle_root>/assets` |
| `bundled_config_dir` | `<root>/config` | `<bundle_root>/config` |
| `user_data_dir` | `%LOCALAPPDATA%\Aashi` on Windows; XDG/`Application Support` elsewhere | same |
| `logs_dir`, `cache_dir` | under `user_data_dir` | same |

Read-only bundle directories are never created — a missing `assets/` or
`config/` means a broken install and must surface as an error. Writable
directories are created only by an explicit `ensure_user_directories()` call, so
importing the package has no filesystem side effects.

## Environment distinction

`detect_environment()` resolves `AASHI_ENV` first; otherwise frozen builds
default to production and source runs default to development. Development
enables `debug`, `DEBUG` logging and console output; production uses `INFO` and
file-only logging, because packaged Windows builds have no console attached.

## Logging

`configure_logging()` configures only the `aashi` logger namespace, never the
root logger, and sets `propagate = False`. It is idempotent — repeated calls
replace handlers instead of accumulating them. A rotating file handler
(1 MiB × 3 backups, UTF-8, `delay=True`) writes to `logs_dir/aashi.log`. If the
log file cannot be opened, file logging is skipped with a warning rather than
preventing startup. `reset_logging()` closes handlers, which Windows requires
before a log file can be moved or deleted.

## Usage

```powershell
pip install -r requirements-dev.txt

python -m aashi        # environment auto-detected
python run_dev.py      # development environment forced
aashi                  # installed GUI launcher
pytest
```

## Design decisions

- **src layout.** Tests import the installed package, so a broken package
  manifest fails in tests rather than after packaging.
- **`aashi/__init__.py` imports nothing.** Importing `aashi` must never pull in
  PySide6, keeping non-GUI consumers and tests Qt-free.
- **Qt-free context.** `create_context()` resolves paths, settings and logging
  without touching Qt; only `run()` requires a display.
- **Explicit context over globals.** `ApplicationContext` is passed to the
  components that need it; there is no module-level application singleton.
- **Injectable environment mappings.** `resolve_paths`, `detect_environment` and
  `load_settings` accept an `env` mapping, so tests never mutate real process
  state.
- **Frozen `Settings` and `AashiPaths`.** Startup state is immutable, so no
  module can mutate configuration behind another's back.
- **`gui-scripts` entry point.** On Windows this produces a console-free
  launcher, which is correct for a desktop companion.
- **Version in one place.** `aashi.__version__` is read by the build backend, so
  packaging metadata cannot drift from the package.

## Testing

`tests/` covers package imports and metadata, environment detection and its
aliases, settings layering and precedence, `ConfigError` on invalid input, path
resolution and overrides, log configuration and idempotency, and a pytest-qt
smoke test of the `QApplication` bootstrap and the temporary window.

## Known limitations

- The foundation window is scaffolding and is deleted by a later UI module.
- Configuration is intentionally minimal; the real settings system is separate.
- Packaging (PyInstaller spec, installer) is not part of UI-01. Path resolution
  is frozen-build aware but has not been exercised against a real frozen build.
