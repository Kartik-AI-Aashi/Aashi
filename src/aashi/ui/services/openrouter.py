"""OpenRouter chat-completions client for the Aashi chat window.

A tiny, Qt-free adapter that turns one user message into an assistant reply by
calling OpenRouter's ``chat/completions`` endpoint. It lives in
:mod:`aashi.ui.services` so the UI depends on :func:`fetch_response` rather
than on the network details. The call blocks while waiting for the API — the
chat window invokes it from a worker thread — and any failure is reported as
:class:`OpenRouterError` so callers can degrade gracefully.
"""

from __future__ import annotations

import os
from typing import Final

import requests

__all__ = [
    "OPENROUTER_URL",
    "MODEL",
    "VISION_MODEL",
    "SYSTEM_PROMPT",
    "FORMATTING_PROMPT",
    "OpenRouterError",
    "fetch_response",
    "fetch_vision_response",
]

OPENROUTER_URL: Final[str] = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter's chat completions endpoint."""

MODEL: Final[str] = "deepseek/deepseek-chat"
"""Model identifier sent to OpenRouter for plain text replies."""

VISION_MODEL: Final[str] = "openai/gpt-4o-mini"
"""Vision-capable model used when the user attaches an image.

``MODEL`` (deepseek-chat) cannot see images, so image messages route here
instead. gpt-4o-mini accepts the standard ``image_url`` content part through
OpenRouter's chat-completions API, so the request shape is the same one
:func:`fetch_response` already uses — only the model and the user message's
content structure differ.
"""

_IDENTITY_PROMPT: Final[str] = (
    "You are Aashi, a smart, helpful assistant.\n"
    "STRICT IDENTITY RULES:\n"
    "- Your name is ALWAYS \"Aashi\".\n"
    "- NEVER say you are GPT, Phi, Llama, or any other model.\n"
    "- NEVER reveal your underlying model, provider, or architecture.\n"
    "- When asked about your name, ALWAYS reply \"My name is Aashi.\"\n"
    "- Always respond as Aashi, regardless of the question."
)
"""Identity rules that keep every reply framed as Aashi."""

FORMATTING_PROMPT: Final[str] = (
    "RESPONSE FORMATTING RULES:\n"
    "- Structure every answer clearly with Markdown: use headings (##) for "
    "sections, bullet or numbered lists for enumerations, **bold** for key "
    "terms, `inline code` for code, and fenced code blocks for multi-line code.\n"
    "- When the user asks for a visual or structured representation — a "
    "flowchart, workflow, process, diagram, architecture, pipeline, decision "
    "tree, hierarchy, \"show the steps\", \"visualize this\", or \"show me how "
    "this works\" — detect the requested FORMAT and reply with a text diagram "
    "built from your own knowledge of the topic:\n"
    "  * FLOWCHART / PROCESS: a vertical monospace flowchart that connects "
    "boxes with │ and ▼ and branches with ├── / └──:\n"
    "        Start\n"
    "          │\n"
    "          ▼\n"
    "      Get Input\n"
    "  * WORKFLOW / STEPS: labelled vertical steps (Step 1 → Step 2 → "
    "Result) joined by │ and ▼; when a step forks, split with ├── / └── and "
    "rejoin.\n"
    "  * DECISION TREE: a root question, a │ below it, then a ┌───┴───┐ pair "
    "of branches labelled with the decision outcomes (YES / NO, Valid / "
    "Invalid), each leading to its result.\n"
    "  * ARCHITECTURE / PIPELINE: a vertical chain of component blocks "
    "(User → Frontend → API → Backend → Database) joined by │ and ▼; when the "
    "system splits, branch the chain and merge with └───┬───┘ before "
    "continuing to the final response.\n"
    "- Use a diagram ONLY when the user asks for one or the format clearly "
    "requires it. A normal question gets a normal answer; a detailed-"
    "explanation request gets structured Markdown with headings and lists — "
    "never a forced flowchart.\n"
    "- Align diagram connectors with monospace spacing so │ ▼ ├── └── line up "
    "vertically, and keep box labels short enough to sit on a single line."
)
"""Response-formatting rules shipped with every system prompt.

Tells the model when to produce a text diagram (flowchart / workflow /
decision tree / architecture), how to draw each kind with Unicode box-drawing
characters, and — just as importantly — when NOT to: ordinary questions stay
ordinary.
"""

SYSTEM_PROMPT: Final[str] = _IDENTITY_PROMPT + "\n\n" + FORMATTING_PROMPT
"""System message that frames every assistant reply."""

API_KEY_ENV: Final[str] = "OPENROUTER_API_KEY"
"""Environment variable holding the OpenRouter API key."""

# (connect, read) timeout in seconds; connect fails fast, read allows for a
# slow model to finish answering.
_TIMEOUT_SECONDS: Final[tuple[float, float]] = (10.0, 30.0)


class OpenRouterError(Exception):
    """The API was reached but no usable assistant reply came back."""


def fetch_response(
    user_message: str,
    *,
    api_key: str | None = None,
    timeout: tuple[float, float] | None = None,
) -> str:
    """Return OpenRouter's assistant reply to ``user_message``.

    Args:
        user_message: The message to answer.
        api_key: OpenRouter API key. When omitted the
            ``OPENROUTER_API_KEY`` environment variable is used.
        timeout: ``(connect, read)`` timeout in seconds. Defaults to
            :data:`_TIMEOUT_SECONDS`.

    Returns:
        The assistant's reply text.

    Raises:
        OpenRouterError: The request failed at the HTTP or JSON level, or the
            response body did not contain a usable assistant message.
    """
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise OpenRouterError("Missing API key. Set OPENROUTER_API_KEY environment variable.")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }
    return _request_chat(payload, api_key=key, timeout=timeout)


def fetch_vision_response(
    user_message: str,
    image_data_uri: str,
    *,
    api_key: str | None = None,
    timeout: tuple[float, float] | None = None,
) -> str:
    """Return the vision model's reply to ``user_message`` plus an image.

    The user message is sent as a multimodal turn: the text plus the image as
    an ``image_url`` content part carrying a ``data:`` URI — never a local
    path. ``image_data_uri`` must be produced by
    :func:`aashi.ui.services.image_input.encode_image_data_uri`.

    Args:
        user_message: The text part of the message.
        image_data_uri: The ``data:`` URI of the attached image.
        api_key: OpenRouter API key. When omitted the
            ``OPENROUTER_API_KEY`` environment variable is used.
        timeout: ``(connect, read)`` timeout in seconds. Defaults to
            :data:`_TIMEOUT_SECONDS`.

    Returns:
        The assistant's reply text.

    Raises:
        OpenRouterError: The request failed at the HTTP or JSON level, or the
            response body did not contain a usable assistant message.
    """
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise OpenRouterError("Missing API key. Set OPENROUTER_API_KEY environment variable.")

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            },
        ],
    }
    return _request_chat(payload, api_key=key, timeout=timeout)


def _request_chat(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout: tuple[float, float] | None,
) -> str:
    """POST ``payload`` to OpenRouter and return the extracted assistant reply.

    Shared by :func:`fetch_response` and :func:`fetch_vision_response` so the
    HTTP handling and reply extraction live in exactly one place. ``api_key``
    has already been resolved by the caller.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=timeout or _TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        data = response.json()

        if "choices" not in data or not data["choices"]:
            raise OpenRouterError("No response from AI")

        msg = data["choices"][0].get("message", {})
        reply = msg.get("content")
        if isinstance(reply, str):
            reply = reply.encode("utf-8", "ignore").decode("utf-8")

        if not isinstance(reply, str) or not reply.strip():
            raise OpenRouterError("Empty or invalid AI response")
    except Exception as exc:
        raise OpenRouterError(str(exc)) from exc

    return reply.strip()
