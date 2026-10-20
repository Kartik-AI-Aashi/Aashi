"""Safe Windows diagnostics for Aashi's configured AI providers.

This script never downloads a model and never prints ``OPENROUTER_API_KEY``.
By default it checks the Ollama executable, the Ollama tags endpoint, the
configured model name, and the source modules loaded by this project. Pass
``--ollama-generate`` or ``--openrouter-generate`` to perform one explicit real
completion request.

Run from the Aashi Development directory with the same Python interpreter used
to launch the app::

    python scripts/diagnose_ai_providers.py
    python scripts/diagnose_ai_providers.py --ollama-generate
    python scripts/diagnose_ai_providers.py --openrouter-generate
    python scripts/diagnose_ai_providers.py --hybrid-generate
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aashi.ui.services.local_ai import (  # noqa: E402
    MODE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
    fetch_response_hybrid,
    fetch_response_local,
)
from aashi.ui.services.openrouter import (  # noqa: E402
    API_KEY_ENV,
    MODEL,
    OPENROUTER_URL,
    fetch_response,
)


def _ollama_tags_url() -> str:
    return OLLAMA_URL.rsplit("/", 1)[0] + "/tags"


def _run_ollama(command: list[str]) -> bool:
    executable = shutil.which("ollama")
    if executable is None:
        print("ollama_executable: NOT FOUND")
        return False
    print(f"ollama_executable: {executable}")
    try:
        result = subprocess.run(
            [executable, *command],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"ollama_cli_error: {type(exc).__name__}")
        return False
    print(f"ollama_cli_exit_code: {result.returncode}")
    output = (result.stdout or result.stderr).strip()
    if output:
        print(output)
    return result.returncode == 0


def check_ollama(*, generate: bool) -> bool:
    print("== Ollama ==")
    print(f"configured_url: {OLLAMA_URL}")
    print(f"configured_model: {OLLAMA_MODEL}")
    print(f"configured_timeout_seconds: {OLLAMA_TIMEOUT}")
    cli_ok = _run_ollama(["--version"])
    cli_ok = _run_ollama(["list"]) and cli_ok

    tags_url = _ollama_tags_url()
    tags_ok = False
    try:
        started = time.monotonic()
        response = requests.get(tags_url, timeout=5)
        elapsed = time.monotonic() - started
        print(f"tags_url: {tags_url}")
        print(f"tags_http_status: {response.status_code}")
        print(f"tags_elapsed_seconds: {elapsed:.3f}")
        response.raise_for_status()
        models = response.json().get("models", [])
        names = [str(item.get("name", "")) for item in models if isinstance(item, dict)]
        print(f"installed_model_count: {len(names)}")
        model_present = any(
            name == OLLAMA_MODEL or name.startswith(OLLAMA_MODEL + ":")
            for name in names
        )
        print(f"configured_model_present: {model_present}")
        tags_ok = model_present
    except requests.RequestException as exc:
        print(f"tags_request_error: {type(exc).__name__}")
    except (TypeError, ValueError, AttributeError) as exc:
        print(f"tags_response_error: {type(exc).__name__}")

    if not generate:
        return cli_ok and tags_ok
    generation_ok = False
    try:
        started = time.monotonic()
        reply = fetch_response_local("Reply with exactly: AASHI_OLLAMA_OK")
        elapsed = time.monotonic() - started
        print(f"application_ollama_elapsed_seconds: {elapsed:.3f}")
        print(f"application_ollama_reply: {reply}")
        generation_ok = bool(reply.strip())
    except Exception as exc:
        print(f"application_ollama_error: {type(exc).__name__}")
        print(f"application_ollama_error_kind: {getattr(exc, 'failure_kind', 'unknown')}")
    return cli_ok and tags_ok and generation_ok


def check_openrouter(*, generate: bool) -> bool:
    print("== OpenRouter ==")
    print(f"configured_url: {OPENROUTER_URL}")
    print(f"configured_model: {MODEL}")
    print(f"api_key_present: {bool(os.environ.get(API_KEY_ENV))}")
    key_present = bool(os.environ.get(API_KEY_ENV))
    if not generate:
        return key_present
    if not key_present:
        return False
    generation_ok = False
    try:
        started = time.monotonic()
        reply = fetch_response("Reply with exactly: AASHI_OPENROUTER_OK")
        elapsed = time.monotonic() - started
        print(f"application_openrouter_elapsed_seconds: {elapsed:.3f}")
        print(f"application_openrouter_reply: {reply}")
        generation_ok = bool(reply.strip())
    except Exception as exc:
        print(f"application_openrouter_error: {type(exc).__name__}")
        print(f"application_openrouter_error_kind: {getattr(exc, 'failure_kind', 'unknown')}")
    return generation_ok


def check_hybrid() -> bool:
    """Send one request through the configured hybrid router."""
    print("== Hybrid ==")
    print(f"configured_mode: {MODE}")
    trace: list[str] = []

    class _TraceHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            trace.append(record.getMessage())

    logger = logging.getLogger("aashi.ui.services.local_ai")
    handler = _TraceHandler()
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        started = time.monotonic()
        reply = fetch_response_hybrid("Reply with exactly: AASHI_HYBRID_OK")
        elapsed = time.monotonic() - started
        print(f"application_hybrid_elapsed_seconds: {elapsed:.3f}")
        print(f"application_hybrid_reply: {reply}")
        for message in trace:
            print(f"hybrid_trace: {message}")
        return bool(reply.strip())
    except Exception as exc:
        print(f"application_hybrid_error: {type(exc).__name__}")
        print(f"application_hybrid_error_kind: {getattr(exc, 'failure_kind', 'unknown')}")
        for message in trace:
            print(f"hybrid_trace: {message}")
        local_error = getattr(exc, "local_error", None)
        online_error = getattr(exc, "online_error", None)
        if local_error is not None:
            print(f"application_hybrid_local_error_kind: {getattr(local_error, 'failure_kind', 'unknown')}")
        if online_error is not None:
            print(f"application_hybrid_online_error_kind: {getattr(online_error, 'failure_kind', 'unknown')}")
        return False
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-generate", action="store_true", help="send one real request through Aashi's Ollama adapter")
    parser.add_argument("--openrouter-generate", action="store_true", help="send one real request through Aashi's OpenRouter adapter")
    parser.add_argument("--hybrid-generate", action="store_true", help="send one real request through Aashi's hybrid router")
    args = parser.parse_args()
    logging.getLogger("aashi.ui.services.local_ai").setLevel(logging.ERROR)

    print(f"project_root: {PROJECT_ROOT}")
    print(f"python_executable: {sys.executable}")
    print(f"local_ai_module: {Path(__import__('aashi.ui.services.local_ai', fromlist=['__file__']).__file__).resolve()}")
    print(f"openrouter_module: {Path(__import__('aashi.ui.services.openrouter', fromlist=['__file__']).__file__).resolve()}")
    run_all = not (
        args.ollama_generate or args.openrouter_generate or args.hybrid_generate
    )
    checks: list[bool] = []
    if run_all or args.ollama_generate:
        checks.append(check_ollama(generate=args.ollama_generate))
    else:
        check_ollama(generate=False)
    if run_all or args.openrouter_generate:
        checks.append(check_openrouter(generate=args.openrouter_generate))
    else:
        check_openrouter(generate=False)
    if args.hybrid_generate:
        checks.append(check_hybrid())
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
