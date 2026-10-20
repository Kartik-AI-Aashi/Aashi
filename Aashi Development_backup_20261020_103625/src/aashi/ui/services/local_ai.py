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
    "HybridProviderError",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "MODE",
    "has_internet",
    "is_complex",
    "format_provider_error",
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


class HybridProviderError(OpenRouterError):
    """Both configured providers failed for one request.

    The original exceptions are retained for local diagnostics, while the UI
    can use :func:`format_provider_error` to show a short, safe explanation.
    In particular, this prevents the final fallback exception from hiding the
    fact that the local provider was tried first.
    """

    def __init__(self, local_error: Exception, online_error: Exception) -> None:
        self.local_error = local_error
        self.online_error = online_error
        super().__init__(
            "Local and OpenRouter providers failed: "
            f"local={local_error}; online={online_error}"
        )


def _provider_reason(error: Exception) -> str:
    """Return a bounded, non-secret description suitable for the chat bubble."""
    provider = getattr(error, "provider", "")
    failure_kind = getattr(error, "failure_kind", "")
    status_code = getattr(error, "status_code", None)
    if provider == "ollama" and failure_kind == "unavailable":
        return "the local Ollama service is unavailable at http://localhost:11434."
    if provider == "ollama" and failure_kind == "invalid_model":
        return f"the configured Ollama model is unavailable (HTTP {status_code or 404})."
    if provider == "ollama" and failure_kind == "timeout":
        return "the local Ollama request timed out."
    if provider == "openrouter" and failure_kind == "configuration":
        return "OpenRouter is not configured (OPENROUTER_API_KEY is missing)."
    if provider == "openrouter" and failure_kind == "authentication":
        return "OpenRouter rejected the configured credentials."
    if provider == "openrouter" and failure_kind == "invalid_model":
        return f"the configured OpenRouter model is unavailable (HTTP {status_code or 404})."
    if failure_kind == "rate_limit":
        return "the provider rate-limited the request."
    if failure_kind in {"timeout", "transient_http"}:
        return "the provider request timed out or had a temporary server failure."
    if failure_kind == "invalid_response":
        return "the provider returned an invalid response."
    message = str(error).casefold()
    if "missing api key" in message or "openrouter_api_key" in message:
        return "OpenRouter is not configured (OPENROUTER_API_KEY is missing)."
    if (
        "localhost:11434" in message
        or ("localhost" in message and "11434" in message)
        or ("ollama" in message and "connection" in message)
    ):
        return "the local Ollama service is unavailable at http://localhost:11434."
    if "timed out" in message or "timeout" in message:
        return "a provider request timed out."
    if "401" in message or "403" in message or "unauthorized" in message:
        return "the configured provider rejected authentication."
    if "429" in message or "rate limit" in message:
        return "the configured provider rate-limited the request."
    return "the configured AI provider returned an error."


def format_provider_error(error: Exception) -> str:
    """Return an actionable provider error without exposing response payloads."""
    if isinstance(error, HybridProviderError):
        local_reason = _provider_reason(error.local_error)
        online_reason = _provider_reason(error.online_error)
        return (
            "AI is unavailable right now: "
            f"{local_reason} {online_reason} "
            "Start Ollama with the configured model or set OPENROUTER_API_KEY, "
            "then try again."
        )
    return f"AI provider unavailable: {_provider_reason(error)}"


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
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status_code = getattr(resp, "status_code", None)
            failure_kind, retryable = _classify_ollama_status(status_code)
            raise OpenRouterError(
                f"Ollama returned HTTP {status_code or 'error'}.",
                provider="ollama",
                status_code=status_code,
                failure_kind=failure_kind,
                retryable=retryable,
            ) from exc

        data = resp.json()
        reply = data.get("response")

        if not isinstance(reply, str) or not reply.strip():
            raise OpenRouterError(
                "Empty or invalid Ollama response",
                provider="ollama",
                failure_kind="invalid_response",
                retryable=False,
            )
    except OpenRouterError:
        raise
    except requests.Timeout as exc:
        raise OpenRouterError(
            "Ollama request timed out.",
            provider="ollama",
            failure_kind="timeout",
            retryable=True,
        ) from exc
    except requests.ConnectionError as exc:
        raise OpenRouterError(
            "Ollama is unavailable at http://localhost:11434.",
            provider="ollama",
            failure_kind="unavailable",
            retryable=True,
        ) from exc
    except requests.RequestException as exc:
        raise OpenRouterError(
            "Ollama request failed.",
            provider="ollama",
            failure_kind="provider_error",
            retryable=True,
        ) from exc
    except Exception as exc:
        raise OpenRouterError(
            "Ollama returned an invalid response.",
            provider="ollama",
            failure_kind="invalid_response",
            retryable=False,
        ) from exc

    return _enforce_identity(reply.strip())


def _classify_ollama_status(status_code: int | None) -> tuple[str, bool]:
    """Classify an Ollama HTTP failure without exposing its response body."""
    if status_code == 404:
        return "invalid_model", False
    if status_code in {408, 409, 425, 429} or (status_code is not None and status_code >= 500):
        return "transient_http", True
    return "provider_http", False


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

    Attempts the other provider at most once when the selected provider fails.
    The same provider is never retried in a loop. If both providers fail, a
    :class:`HybridProviderError` is raised so the UI can report both causes
    instead of fabricating a response.

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
    """Try Ollama once, then make one independent OpenRouter attempt."""
    try:
        return _enforce_identity(fetch_response_local(message))
    except Exception as local_exc:
        _logger.warning(
            "Local model failed (kind=%s retryable=%s); falling back to OpenRouter.",
            getattr(local_exc, "failure_kind", "unknown"),
            getattr(local_exc, "retryable", False),
            exc_info=True,
        )
        try:
            return _try_online(message)
        except Exception as online_exc:
            raise HybridProviderError(local_exc, online_exc) from online_exc


def _try_online(message: str) -> str:
    """Attempt an OpenRouter call, returning the reply or raising on failure.

    Does NOT return a fallback string — instead raises so the caller can
    decide whether to fall back to another provider or show an error.
    """
    return _enforce_identity(fetch_response(message))


def _try_online_with_fallback(message: str) -> str:
    """Try OpenRouter once, then make one independent Ollama attempt."""
    try:
        return _enforce_identity(fetch_response(message))
    except Exception as online_exc:
        _logger.warning(
            "OpenRouter failed (kind=%s retryable=%s); falling back to local model.",
            getattr(online_exc, "failure_kind", "unknown"),
            getattr(online_exc, "retryable", False),
            exc_info=True,
        )
        try:
            return _try_local(message)
        except Exception as local_exc:
            raise HybridProviderError(local_exc, online_exc) from local_exc
