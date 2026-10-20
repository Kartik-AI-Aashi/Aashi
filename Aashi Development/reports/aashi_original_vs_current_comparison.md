# AASHI original-versus-current comparison

Date: 2026-10-20

## Scope and protected copies

- Active project: `/mnt/c/Users/Kartik Shau/OneDrive/Desktop/Aashi_emotion_update_v3/Aashi Development`
- Original extracted reference: `/tmp/agent-tmp/Aashi_original_backup_20261020_142947/Aashi Development`
- Original archive: `/mnt/c/Users/Kartik Shau/OneDrive/Desktop/Aashi_emotion_update_v3/Backup.zip`
- Pre-change recovery snapshot: `/tmp/agent-tmp/Aashi_recovery_20261020_175236`
- Existing database/user-data recovery copy: `/tmp/agent-tmp/Aashi_user_data_recovery_20261020_174618`
- Selected timestamped comparison snapshot: `Aashi Development_backup_20261020_143027`

The active project was copied and verified before this report or source change.
The original ZIP and all existing backup directories were left untouched. No
SQLite database, conversation, memory file, voice profile, model file, or
credential was changed.

## Comparison summary

| Component | Original reference | Current project | Behavioural significance | Decision |
|---|---|---|---|---|
| `src/aashi/ui/services/openrouter.py` | Static `SYSTEM_PROMPT`; user text is a separate user message | Dynamic prompt appends language rules based on the complete supplied text | Strong regression candidate: prior turns, style notes, and attached text can override the latest language request | Restore original static prompt delivery; retain safe error metadata and compatible identity cleanup |
| `src/aashi/ui/services/local_ai.py` | `SYSTEM_PROMPT` + `User: ...` + `Assistant:` generation boundary | Dynamic prompt + raw transcript + trailing newline | Strong regression candidate for weak Ollama continuation and echoed/missing role boundaries | Restore original Ollama prompt boundary; retain diagnostics/fallback safety |
| `src/aashi/ui/windows/chat_window.py` | Recent transcript history already existed | Same history path plus desktop/voice/monitoring features | History itself is not a new regression; explicit desktop intents intentionally bypass the model | Leave desktop features and normal history intact |
| `src/aashi/emotion/layer.py` | Emotion cleanup and tone layer | Adds leading transport-label cleanup and centralized names | Compatible safety improvement; prevents visible `Assistant:`/`User:` prefixes | Retain |
| `src/aashi/emotion/style.py` | Hard-coded Aashi/Kartik names | Uses centralized identity constants | Behaviourally equivalent | Retain |
| `src/aashi/identity.py` | Not present | Centralized assistant/user names | Supports consistent identity handling | Retain |
| Provider settings | Ollama `phi3`; OpenRouter text `deepseek/deepseek-chat`; vision `openai/gpt-4o-mini`; same endpoints and timeouts | Same values | No configuration drift found | Do not change |
| Error handling | Mostly generic exceptions/fallback | Classified provider errors and bounded diagnostics | Compatible and necessary for honest failure reporting | Retain |
| Dependencies/launch | Python `>=3.12`; `run_dev.py` adds adjacent `src` | Same requirements plus Windows desktop launch guard | No provider regression found | Leave untouched |

## Exact provider regression

The original Ollama client built this prompt:

```text
SYSTEM_PROMPT

User: <supplied message>
Assistant:
```

The current client builds this instead:

```text
build_system_prompt(<supplied message>)

<supplied message>
```

The supplied message is normally a flattened recent transcript. The current
`build_system_prompt()` scans that entire transcript and any appended emotion
style note for the words `hinglish` and `hindi`. Its `hinglish` branch is tested
before its `hindi` branch. Therefore an older Hinglish turn, or a style note
that says Hinglish is acceptable, can override a newer Hindi request.

The same dynamic prompt is sent as the OpenRouter system message. This differs
from the original static system message and makes conversational transcript
content part of the system-prompt language decision.

A focused reproduction produced:

```text
history: older "Hinglish matlab tha mera" + latest "Hindi mein hi bolo na"
result: CURRENT LANGUAGE PREFERENCE: Use Hinglish ...
```

The current mocked Ollama payload also did not end with the original
`Assistant:` continuation boundary. This is the strongest evidence-based cause
found for the provider/conversational regression. It explains inconsistent
language, weak local-model continuation, and model-generated transport labels;
it does not require changing the configured model or endpoint.

## Conversation/history findings

`chat_window.py` already had bounded recent history in the original reference:

```text
User: ...

Assistant: ...
```

The current project preserves that mechanism and does not append ordinary
provider error bubbles to `_chat_history` or SQLite. The current project does
append successful assistant replies, preserving context as intended.

The current desktop assistant adds explicit local handling for recognized
screen/file/folder/application requests. That is intentionally retained; it is
not part of the ordinary model-backed conversation path. No evidence was found
that the original flowchart fixture was generated by the current provider.

## Parsing, errors, and threading

- OpenRouter reply extraction is unchanged in substance: `choices[0].message.content`.
- Ollama reply extraction is unchanged in substance: the JSON `response` field.
- Current provider error classification distinguishes unavailable service,
  missing model, authentication, timeout, malformed response, and HTTP errors.
- Current text-generation failures are shown as bounded diagnostics and are not
  saved as valid assistant turns.
- The AI thread pool remains single-threaded, so the application does not start
  concurrent generations for normal submissions.
- A stale-result hazard remains possible if a user changes conversations while a
  request is running; this was identified in code but was not changed because it
  was not needed to restore the original provider prompt and has no direct
  reproduction in the supplied evidence.

## Provider and launch verification

Current source confirms:

```text
Ollama:     http://localhost:11434/api/generate, model phi3, timeout 30s
OpenRouter: https://openrouter.ai/api/v1/chat/completions
Text model: deepseek/deepseek-chat
Vision:     openai/gpt-4o-mini
Timeout:    10s connect / 30s read
```

The parent VS Code settings file targets the active project directory:

```text
C:\Users\Kartik Shau\OneDrive\Desktop\Aashi_emotion_update_v3\Aashi Development
```

It does not target a backup directory and does not set a Python interpreter.
The project declares Python `>=3.12`; the Windows `.venv` is the expected
runtime. The Linux container only has Python 3.11.2.

Live checks available in the container:

- `ollama` executable: not found.
- `http://127.0.0.1:11434/api/tags`: connection refused.
- `OPENROUTER_API_KEY`: not present in the container process.
- No real Ollama or OpenRouter completion was claimed.

Mocked checks are clearly separate from live checks. A mocked call through the
current Ollama adapter returned `AASHI_OLLAMA_OK`, confirmed the configured URL
and model, but did not prove service or model availability.

## Checks run before repair

```text
108 focused provider/chat tests: passed
```

Those tests passed against the current project, but they encoded the newer
dynamic-prompt/no-trailing-marker behavior. They therefore did not prove
compatibility with the original provider contract. The repair updates those
expectations to the original request shape and adds regression coverage for
language preference isolation and provider-error history isolation.

## Repair boundary

The repair is deliberately limited to provider prompt construction and its
regression tests. It does not replace the whole project with the ZIP, does not
revert the database, and does not remove desktop-assistant functionality.

The safe restoration keeps current error classification, bounded diagnostics,
one-attempt cross-provider fallback, model-identity cleanup, and transport-label
cleanup. It restores the original static personality/formatting prompt and the
original Ollama generation boundary, which are the specific changed behaviors
with direct reproduction evidence.

## Post-repair state

The active provider clients now send:

- OpenRouter text and vision: the original static `SYSTEM_PROMPT` as the
  system message, plus a bounded explicit-language suffix only when the latest
  user turn requests Hindi, Hinglish, or English.
- Ollama: the same prompt construction, then `User: <transcript>`, then the
  original `Assistant:` continuation boundary.

The language helper is now used only through `extract_latest_user_message()`.
It derives an explicit Hindi, Hinglish, or English instruction from the latest
user turn and ignores older turns, emotion style notes, and attached content.
Without an explicit preference, the provider still receives the original static
system prompt unchanged.

Added regression coverage checks:

- one coherent assistant bubble for a simple greeting;
- no provider diagnostic text entering the next conversation prompt;
- the original static OpenRouter system message;
- the original Ollama generation boundary;
- project context across three messages;
- language-clarification context across five messages;
- local/online fallback and both-provider failure behavior.
- latest-turn-only language preference and current-turn complexity routing;
- stale provider callback rejection after a conversation switch;
- one in-flight provider submission at a time;
- identity cleanup after emotion processing, including legacy `Ansh` and model
  identity leaks.

The source repair does not prove live model quality. Windows Ollama service,
installed `phi3`, and OpenRouter authentication still require the diagnostic
script and the real launch environment.

The diagnostic script now also supports `--hybrid-generate` and returns a
nonzero exit status when a requested provider check fails. It prints safe hybrid
routing trace messages without printing credentials or raw provider payloads.

## Final integration hardening

Additional evidence-based fixes were applied after the initial provider repair:

- Provider language instructions now use only the latest parsed `User:` turn.
  Older Hinglish turns, style notes, and attachment text cannot override a
  newer Hindi, Hinglish, or English request.
- Hybrid complexity routing evaluates the latest user turn while the emotion
  layer retains its original whole-prompt routing-size behavior.
- Provider callback generations are invalidated when the conversation changes.
  A late response cannot be displayed or saved in the wrong conversation.
- A second provider submission is held while one request is in flight, which
  prevents duplicate assistant responses from rapid submissions.
- Identity enforcement now runs after emotion cleanup and covers legacy `Ansh`
  and model-name self-identification leaks.
- Provider error callbacks clear pending emotion state so a failed text request
  cannot affect a later attachment response.

## Test baseline comparison

Using a separate temporary working copy of the extracted original reference:

```text
Original reference: 752 passed, 3 warnings
Active repaired project: 829 passed, 3 warnings
```

The active project has additional desktop-assistant, provider-diagnostic, and
conversation-regression tests. Both runs used the same offscreen Qt mode,
disabled bytecode/cache writes, and mocked/no-real-provider test boundaries.
