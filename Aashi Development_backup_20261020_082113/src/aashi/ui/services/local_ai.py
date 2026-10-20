"""Local AI and hybrid routing for the Aashi chat window.

Provides :func:`fetch_response_local` (Ollama / phi3) and
:func:`fetch_response_hybrid` which chooses between the local model and the
remote OpenRouter API based on connectivity and message complexity.

All functions are Qt-free and blocking — the chat window's worker thread is
responsible for calling them off the UI thread.
"""

from __future__ import annotations

import logging
from typing import Final

import requests

from aashi.ui.services.openrouter import SYSTEM_PROMPT, OpenRouterError, fetch_response

__all__ = [
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "MODE",
    "has_internet",
    "is_complex",
    "fetch_response_local",
    "fetch_response_hybrid",
]

_logger = logging.getLogger(__name__)

OLLAMA_URL: Final[str] = "http://localhost:11434/api/generate"
"""Ollama's local generate endpoint."""

OLLAMA_MODEL: Final[str] = "phi3"
"""Default model pulled into Ollama."""

OLLAMA_TIMEOUT: Final[float] = 30.0
"""Read timeout for Ollama in seconds."""

_INTERNET_CHECK_URL: Final[str] = "https://dns.google/resolve?name=openrouter.ai"
"""Lightweight connectivity probe — DNS-over-HTTPS avoids DNS-level blocks."""

_COMPLEX_KEYWORDS: frozenset[str] = frozenset({
    "explain",
    "code",
    "project",
    "implement",
    "refactor",
    "debug",
    "architect",
    "design",
    "review",
    "optimise",
    "optimize",
    "compare",
    "analyse",
    "analyze",
})
"""Keywords that raise a message's perceived complexity."""

_COMPLEX_LENGTH_THRESHOLD: Final[int] = 120
"""Character count above which a message is considered complex."""

# ---------------------------------------------------------------------------
# Identity safety — catches responses that leak the underlying model name
# when the system prompt was not strong enough.
# ---------------------------------------------------------------------------

_IDENTITY_LEAK_PATTERNS: tuple[str, ...] = (
    "i am an ai",
    "i am gpt",
    "i am a language model",
    "i am phi",
    "i am llama",
    "i am deepseek",
    "i am a large language model",
    "i'm gpt",
    "i'm phi",
    "i'm llama",
    "i'm deepseek",
    "i'm a large language model",
)
"""Lowercased phrases that indicate a model-identity leak."""


def _enforce_identity(reply: str) -> str:
    """Replace a reply that leaks the underlying model name.

    This is a lightweight safety net — it only fires on exact phrase matches.
    Normal replies pass through unchanged.
    """
    lower = reply.lower()
    if any(phrase in lower for phrase in _IDENTITY_LEAK_PATTERNS):
        return "My name is Aashi."
    return reply

# ---------------------------------------------------------------------------
# Global routing mode — set at module level.  The chat window imports and
# reads this value; no other mutation path exists.
# ---------------------------------------------------------------------------

MODE: str = "hybrid"
"""Active routing mode.

Accepted values:
* ``"local"``  — always use the local Ollama model.
* ``"online"`` — always use OpenRouter (same as the original ``fetch_response``).
* ``"hybrid"`` — automatically choose based on connectivity and complexity.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_internet(timeout: float = 3.0) -> bool:
    """Return ``True`` if an outbound HTTP request succeeds.

    Uses a lightweight DNS-over-HTTPS probe to ``dns.google`` — no DNS-level
    blocking can mask a working connection.  The call itself is blocking so
    this must run off the UI thread.
    """
    try:
        resp = requests.get(_INTERNET_CHECK_URL, timeout=timeout)
        return resp.ok
    except Exception:
        return False


def is_complex(message: str) -> bool:
    """Return ``True`` when the message looks complex enough for the full API.

    Heuristic:
    * Message longer than :data:`_COMPLEX_LENGTH_THRESHOLD` characters, **or**
    * Message contains any keyword in :data:`_COMPLEX_KEYWORDS`.
    """
    if len(message) > _COMPLEX_LENGTH_THRESHOLD:
        return True
    lower = message.lower()
    return any(kw in lower for kw in _COMPLEX_KEYWORDS)


# ---------------------------------------------------------------------------
# Local model
# ---------------------------------------------------------------------------

def fetch_response_local(message: str) -> str:
    """Return Ollama's reply to ``message`` via the local HTTP API.

    The call is blocking — the chat window invokes it from a worker thread.

    Args:
        message: The user message to answer.

    Returns:
        The assistant's reply text.

    Raises:
        OpenRouterError: The request failed or the response was unusable.
            The same error type is reused so the caller's ``except`` block
            does not need to change.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{SYSTEM_PROMPT}\n\nUser: {message}\nAssistant:",
        "stream": False,
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()

        data = resp.json()
        reply = data.get("response")

        if not isinstance(reply, str) or not reply.strip():
            raise OpenRouterError("Empty or invalid local model response")
    except Exception as exc:
        raise OpenRouterError(str(exc)) from exc

    return _enforce_identity(reply.strip())


# ---------------------------------------------------------------------------
# Hybrid router
# ---------------------------------------------------------------------------

def fetch_response_hybrid(message: str) -> str:
    """Route ``message`` to the best available backend.

    Routing rules (in priority order):

    1. ``MODE == "local"``  → always local.
    2. ``MODE == "online"`` → always OpenRouter.
    3. ``MODE == "hybrid"`` →
       a. No internet → local.
       b. Message is simple → local (fast).
       c. Message is complex → OpenRouter (more capable).

    Falls back to local if OpenRouter fails, and vice-versa, so the user
    always receives *something*.

    Args:
        message: The user message to answer.

    Returns:
        The assistant's reply text.
    """
    if MODE == "local":
        return _try_local(message)

    if MODE == "online":
        return _try_online(message)

    # hybrid
    if not has_internet():
        _logger.info("No internet — falling back to local model.")
        return _try_local_with_fallback(message)

    if not is_complex(message):
        _logger.info("Simple message — routing to local model.")
        return _try_local_with_fallback(message)

    _logger.info("Complex message — routing to OpenRouter.")
    return _try_online_with_fallback(message)


def _try_local(message: str) -> str:
    """Attempt a local call, returning the reply or raising on failure.

    Does NOT return a fallback string — instead raises so the caller can
    decide whether to fall back to another provider or show an error.
    """
    return fetch_response_local(message)


def _try_local_with_fallback(message: str) -> str:
    """Try the local model first; on failure fall back to OpenRouter."""
    try:
        return _enforce_identity(fetch_response_local(message))
    except Exception as exc:
        _logger.warning(
            "Local model failed (%s); falling back to OpenRouter.", exc
        )
        return _try_online(message)


def _try_online(message: str) -> str:
    """Attempt an OpenRouter call, returning the reply or raising on failure.

    Does NOT return a fallback string — instead raises so the caller can
    decide whether to fall back to another provider or show an error.
    """
    return _enforce_identity(fetch_response(message))


def _try_online_with_fallback(message: str) -> str:
    """Try OpenRouter first; on failure fall back to local."""
    try:
        return _enforce_identity(fetch_response(message))
    except Exception as exc:
        _logger.warning(
            "OpenRouter failed (%s); falling back to local model.", exc
        )
        return _try_local(message)
