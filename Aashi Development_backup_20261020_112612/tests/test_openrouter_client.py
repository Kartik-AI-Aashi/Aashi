"""Verify the OpenRouter chat client.

The client is a thin Qt-free adapter, so ``requests.post`` is mocked and no
network is touched. Covered: the exact request shape (URL, headers, body),
reply extraction, HTTP and malformed-body failures, and API-key precedence.
"""

from __future__ import annotations

import pytest
import requests

from aashi.ui.services import openrouter
from aashi.ui.services.openrouter import (
    API_KEY_ENV,
    build_system_prompt,
    language_instruction,
    MODEL,
    OPENROUTER_URL,
    SYSTEM_PROMPT,
    VISION_MODEL,
    OpenRouterError,
    fetch_response,
    fetch_vision_response,
)


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload


def _patch_post(monkeypatch, response: _FakeResponse | None = None, *, capture: dict) -> None:
    """Replace ``requests.post``, recording the call into ``capture``."""

    def fake_post(url: str, **kwargs) -> _FakeResponse:
        capture["url"] = url
        capture.update(kwargs)
        return response or _FakeResponse(
            {"choices": [{"message": {"content": "hello"}}]}
        )

    monkeypatch.setattr(openrouter.requests, "post", fake_post)


def test_posts_to_openrouter_with_expected_headers_and_body(monkeypatch) -> None:
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture)

    reply = fetch_response("what is aashi?", api_key="test-key")

    assert reply == "hello"
    assert capture["url"] == OPENROUTER_URL
    assert capture["headers"]["Authorization"] == "Bearer test-key"
    assert capture["headers"]["Content-Type"] == "application/json"
    assert capture["json"]["model"] == MODEL
    assert capture["json"]["messages"][1] == {
        "role": "user",
        "content": "what is aashi?",
    }
    assert capture["json"]["messages"][0]["content"].startswith(SYSTEM_PROMPT)
    assert capture["json"]["messages"][0]["content"] != SYSTEM_PROMPT


def test_language_instruction_distinguishes_hindi_and_hinglish() -> None:
    hindi = language_instruction("Hindi mein hi bolo na")
    hinglish = language_instruction("Hinglish matlab tha mera")

    assert "Devanagari" in hindi
    assert "Romanized Hindi" in hinglish
    assert "Devanagari-only" in hinglish
    assert "Romanized Hindi" in build_system_prompt("Hinglish mein baat karo")


def test_system_prompt_keeps_the_identity_rules() -> None:
    assert "My name is Aashi" in build_system_prompt("hi")


def test_api_key_comes_from_the_environment_when_set(monkeypatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "env-key")
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture)

    fetch_response("hi")

    assert capture["headers"]["Authorization"] == "Bearer env-key"


def test_missing_api_key_raises_openrouter_error(monkeypatch) -> None:
    # No credential may be embedded in source, so with neither an explicit key
    # nor the environment variable set the client must refuse to call the API
    # rather than fall back to a hardcoded default.
    monkeypatch.delenv(API_KEY_ENV, raising=False)

    with pytest.raises(OpenRouterError, match="API key") as raised:
        fetch_response("hi")

    assert raised.value.failure_kind == "configuration"
    assert raised.value.retryable is False


def test_http_error_raises_openrouter_error(monkeypatch) -> None:
    _patch_post(monkeypatch, response=_FakeResponse({"choices": []}, status_code=500), capture={})

    with pytest.raises(OpenRouterError) as raised:
        fetch_response("hi", api_key="test-key")

    assert raised.value.status_code == 500
    assert raised.value.failure_kind == "transient_http"
    assert raised.value.retryable is True


def test_authentication_error_is_classified_without_response_body(monkeypatch) -> None:
    _patch_post(monkeypatch, response=_FakeResponse({}, status_code=401), capture={})

    with pytest.raises(OpenRouterError) as raised:
        fetch_response("hi", api_key="invalid-test-key")

    assert raised.value.status_code == 401
    assert raised.value.failure_kind == "authentication"
    assert raised.value.retryable is False
    assert "invalid-test-key" not in str(raised.value)


def test_malformed_body_raises_openrouter_error(monkeypatch) -> None:
    _patch_post(monkeypatch, response=_FakeResponse({"choices": []}), capture={})

    with pytest.raises(OpenRouterError):
        fetch_response("hi", api_key="test-key")


def test_timeout_is_classified_as_recoverable(monkeypatch) -> None:
    monkeypatch.setattr(openrouter.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("slow")))

    with pytest.raises(OpenRouterError) as raised:
        fetch_response("hi", api_key="test-key")

    assert raised.value.failure_kind == "timeout"
    assert raised.value.retryable is True


def test_non_string_reply_raises_openrouter_error(monkeypatch) -> None:
    _patch_post(
        monkeypatch,
        response=_FakeResponse({"choices": [{"message": {"content": 42}}]}),
        capture={},
    )

    with pytest.raises(OpenRouterError):
        fetch_response("hi", api_key="test-key")


# ── Vision requests ──────────────────────────────────────────────────────────


def test_vision_posts_multimodal_payload(monkeypatch) -> None:
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture)

    reply = fetch_vision_response(
        "what is this?", "data:image/png;base64,AAA", api_key="test-key"
    )

    assert reply == "hello"
    assert capture["url"] == OPENROUTER_URL
    assert capture["headers"]["Authorization"] == "Bearer test-key"
    assert capture["json"]["model"] == VISION_MODEL
    assert capture["json"]["messages"][0]["role"] == "system"
    assert capture["json"]["messages"][0]["content"].startswith(SYSTEM_PROMPT)
    assert capture["json"]["messages"][1:] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            ],
        },
    ]


def test_vision_uses_environment_api_key(monkeypatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "env-key")
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture)

    fetch_vision_response("hi", "data:image/png;base64,AAA")

    assert capture["headers"]["Authorization"] == "Bearer env-key"


def test_vision_missing_api_key_raises_openrouter_error(monkeypatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)

    with pytest.raises(OpenRouterError, match="API key"):
        fetch_vision_response("hi", "data:image/png;base64,AAA")


def test_vision_text_route_is_unchanged(monkeypatch) -> None:
    """fetch_response keeps using the text model and a string user message."""
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture)

    fetch_response("plain text", api_key="test-key")

    assert capture["json"]["model"] == MODEL
    assert capture["json"]["messages"][1]["content"] == "plain text"
