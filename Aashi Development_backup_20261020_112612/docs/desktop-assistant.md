# Aashi desktop-assistant architecture

## What was already present

Aashi is an all-in-one PySide6 desktop application. The existing
`AashiChatWindow` owns the conversation UI, SQLite persistence, projects,
attachments, theme system, emotion presentation layer, and background AI
requests. Text requests route through the existing local Ollama/OpenRouter
adapters; image attachments already use the existing OpenRouter vision route.

There was no speech service, screen-capture service, structured computer-action
layer, permission boundary, proactive policy engine, or long-term user-approved
memory store. The existing chat flow is preserved; the new services do not
replace the model provider or conversation database.

## Implemented architecture

```text
PySide6 QApplication
  └── AashiDesktopWindow
        └── existing AashiChatWindow
              ├── existing SQLite conversation/project storage
              ├── existing local/Ollama + OpenRouter reasoning adapters
              ├── AssistantRuntime (structured desktop intent boundary)
              │     ├── PermissionService + FileService
              │     ├── allowlisted ApplicationLauncher
               │     ├── ScreenMonitor + Windows foreground provider
               │     ├── modular SpeechService
               │     ├── ProactiveDecisionEngine
               │     └── TaskExecutor + supported test runner
               ├── persisted AutomationSettings + MemoryStore
              └── background Qt worker pools
```

The desktop shell provides the long-lived window lifecycle, compact floating
mode, minimize/restore, optional system tray, task-state display, and the
application-scoped `Ctrl+Shift+A` foreground shortcut. It wraps the existing
chat widget; it does not create a second assistant or a second `QApplication`.

The runtime recognizes only unambiguous, supported local intents. Unknown
requests continue through the original AI conversation path:

```text
request → intent boundary → permission check → structured service call
        → actual result/verification → user-facing report
```

The model is never allowed to emit an arbitrary shell command for execution.

## Supported local requests

When the folder is inside an authorized root, the following requests are
executed locally rather than answered as fictional instructions:

- `Open the HIH folder`
- `Open HIH in VS Code`
- `Open HIH in Antigravity` (only with an explicit command configuration)
- `Tell me what's inside HIH`
- `Look at my screen` / `Explain this error`
- `Run tests in HIH` when a recognized Python or npm test manifest exists
- `Read README.md in HIH`
- `Create file notes.txt in HIH containing ...` (confirmation required)
- `Edit file notes.txt in HIH to ...` (confirmation required)

Folder names are searched under configured roots. Multiple exact matches are
returned as a choice list rather than silently selecting one. Directory reads
return bounded metadata summaries; arbitrary project files are not read just to
produce a summary. Explicit read/create/edit requests are supported, while
create/edit requests stop at a visible confirmation state. Reply `yes`/`confirm`
to continue the pending change; the resulting file operation is independently
verified by reading the resulting file metadata.

## Security boundary

`PermissionService` canonicalizes configured roots and requested paths, rejects
explicit `..` traversal, and checks resolved symlinks. Reads, listings, launch
requests, and explicit screen captures are low-risk. File create/edit/delete
and memory writes/deletes are confirmation-required. The settings UI exposes
only confirmed memory deletion; arbitrary file deletion and terminal commands
remain unavailable from natural language.

`ApplicationLauncher` supports only `explorer`, `vscode`, `terminal`,
`powershell`, `chrome`, and explicitly configured `antigravity`. Arguments are
passed as separate `argv` values with `shell=False`; it never interpolates a
model-generated command string. A non-zero `CompletedProcess.returncode` is
reported as a failure.

Screen monitoring is opt-in and change-aware. While enabled, a visible timer
polls the active foreground application at the configured interval. A capture
is skipped when the application/window and image fingerprint have not changed;
the proactive engine additionally suppresses repeated evidence. Monitoring is
stopped immediately when paused. Sensitive/excluded applications are blocked
before an image is sent for analysis. Vision analysis uses the existing
`fetch_vision_response` provider only when the user has explicitly enabled the
external-analysis privacy setting. Captured images are encoded through a
temporary file and are not persisted by Aashi.

On Windows, `WindowsForegroundProvider` obtains only the foreground process
name, window title, process ID, and executable metadata through Win32. It does
not read window contents. The current Linux test environment cannot verify the
Win32 calls against a physical desktop.

The JSON `MemoryStore` requires explicit approval and rejects credential-like
keys and values. It supports listing, updating, deleting, and clearing facts;
it is intentionally not fed arbitrary chat, screenshots, passwords, or file
contents automatically.

## Configuration

The application reads secrets only from environment variables. Never put them
in TOML files or committed documentation.

| Variable | Purpose |
| --- | --- |
| `AASHI_ALLOWED_ROOTS` | Authorized folder roots. Use `;` on Windows and `:` on Linux/macOS. If unset, existing Desktop/Documents/Downloads folders are used. |
| `AASHI_ANTIGRAVITY_COMMAND` | Explicit Antigravity launcher, including quoted arguments when needed. There is no guessed command. |
| `AASHI_PROACTIVE_ENABLED` | Opt-in startup greeting (`1`, `true`, `yes`, or `on`). |
| `AASHI_PROACTIVE_SPEECH` | Speak enabled proactive messages when an audio adapter is configured. |
| `AASHI_DO_NOT_DISTURB` | Suppress proactive decisions. |
| `AASHI_PROACTIVE_MUTED` | Suppress proactive decisions without disabling the rest of the assistant. |
| `AASHI_SPEECH_LANGUAGE` | Optional recognition language, default `en-IN`; `hi-IN` is also supported by the optional recognizer. |
| `OPENROUTER_API_KEY` | Optional remote text/vision provider credential. |
| `AASHI_DATA_DIR` | Override per-user data/log/database location. |

The settings button in the assistant controls persisted preferences in
`assistant_settings.json` under the Aashi user-data directory, including
monitor interval, excluded applications, authorized roots, quiet hours,
microphone access, proactive speech, and external screen analysis. The Memory
tab lists approved facts and requires an explicit confirmation dialog before
deleting one or clearing all facts.

The desktop shell itself does not silently register Windows startup. A startup
shortcut/task can be added later only with explicit user consent and an
installer-level setting.

## Install and launch

The project declares Python 3.12 or newer:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python run_dev.py
```

Normal launch after installation:

```powershell
python -m aashi
```

Optional talking-mode packages:

```powershell
python -m pip install -e ".[voice]"
```

The optional adapter uses `SpeechRecognition` for one-shot microphone input
and `pyttsx3` for local system TTS. `SpeechRecognition` may use its configured
online recognizer and the host still needs a working microphone backend. No
voice package is required to launch Aashi or use text/file/screen boundaries.
The approved `processed/test_G_shortform.wav` recording is not part of this
repository and is not modified or regenerated.

## Use the desktop surface

- The main window remains the existing chat experience.
- Use the tray `Open`/`Hide` actions when a system tray is available.
- Use `Compact floating mode` from the tray to keep a small assistant window
  above other work; use the same action again to restore the full geometry.
- Closing the shell hides it when the tray lifecycle is active; `Exit` is the
  explicit shutdown action.
- `Ctrl+Shift+A` restores and foregrounds the window. The shell exposes a
  setter for a different application-scoped shortcut.
- The status strip shows `Idle`, `Processing request`, `Executing action`,
  `Verifying result`, `Completed`, or `Failed`, plus talking/monitoring state.

The microphone button performs one non-continuous recognition request and is
blocked until microphone access is enabled in Settings. The screen button
performs one explicit screen inspection. The eye button pauses/resumes the
configured change-aware monitor; no monitoring is enabled by default.

## Tests and known limitations

The automated suite uses fake subprocess, screen, speech, and tray adapters
where a real Windows application or physical device would be unsafe or
unavailable. This proves path boundaries, structured launch arguments,
confirmation gates, multi-display capture plumbing, speech state transitions,
memory validation, proactive cooldown/quiet-hour policy, runtime intent
routing, and the desktop shell without claiming Windows end-to-end behavior.

The current implementation does not yet provide:

- a signed packaged Windows executable or installer;
- a native WinEvent hook; foreground polling is implemented, but event-hook
  delivery is not yet used;
- offline Whisper/Vosk model download and wake-word detection;
- a native Antigravity integration when that product has no supported launcher;
- arbitrary terminal commands, natural-language file-edit dialogs, or
  automatic backups from natural language;
- a built-in local OCR model; automatic error/recommendation analysis requires
  the configured vision provider and the explicit external-analysis setting;
- verified behavior on a physical Windows display, microphone, tray, VS Code,
  or Antigravity installation in this Linux development container.

These are explicit gaps, not simulated successes. The existing chatbot remains
usable when optional speech, vision, applications, or network services are
unavailable.
