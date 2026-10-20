"""Verify the local-ai and hybrid-routing layer.

Tests cover the pure helpers (``is_complex``), the routing logic in
``fetch_response_hybrid`` via a mocked ``requests.post``, and the global
``MODE`` toggle.  No real network calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

# Ensure the src package is on the path so imports resolve.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aashi.ui.services.local_ai import (  # noqa: E402
    HybridProviderError,
    OLLAMA_MODEL,
    OLLAMA_URL,
    MODE,
    _enforce_identity,
    fetch_response_hybrid,
    fetch_response_local,
    format_provider_error,
    has_internet,
    is_complex,
)
from aashi.ui.services.openrouter import (  # noqa: E402
    OpenRouterError,
    SYSTEM_PROMPT,
    build_system_prompt,
)


# ── is_complex ───────────────────────────────────────────────────────────────


class TestIsComplex:
    def test_short_message_is_simple(self) -> None:
        assert is_complex("hello") is False

    def test_long_message_is_complex(self) -> None:
        assert is_complex("a" * 121) is True

    def test_keyword_triggers_complexity(self) -> None:
        assert is_complex("please explain this code") is True

    def test_case_insensitive_keyword(self) -> None:
        assert is_complex("Can you EXPLAIN something?") is True

    def test_exact_threshold_is_simple(self) -> None:
        assert is_complex("a" * 120) is False

# ── has_internet ─────────────────────────────────────────────────────────────


class TestHasInternet:
    @patch("aashi.ui.services.local_ai.requests.get")
    def test_returns_true_on_success(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True)
        assert has_internet() is True

    @patch("aashi.ui.services.local_ai.requests.get")
    def test_returns_false_on_failure(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception("network down")
        assert has_internet() is False


# ── fetch_response_local ─────────────────────────────────────────────────────


class TestFetchResponseLocal:
    @patch("aashi.ui.services.local_ai.requests.post")
    def test_returns_response_text(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"response": "  Hello from local  "},
        )
        assert fetch_response_local("hi") == "Hello from local"

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_empty_response_raises(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"response": ""},
        )
        with pytest.raises(OpenRouterError):
            fetch_response_local("hi")

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_network_error_raises(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = Exception("connection refused")
        with pytest.raises(OpenRouterError):
            fetch_response_local("hi")

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_connection_error_is_classified_as_ollama_unavailable(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = requests.ConnectionError("connection refused")

        with pytest.raises(OpenRouterError) as raised:
            fetch_response_local("hi")

        assert raised.value.provider == "ollama"
        assert raised.value.failure_kind == "unavailable"
        assert raised.value.retryable is True

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_missing_ollama_model_is_not_classified_as_a_transient_failure(
        self, mock_post: MagicMock
    ) -> None:
        response = MagicMock(status_code=404)
        response.raise_for_status.side_effect = requests.HTTPError("HTTP 404")
        mock_post.return_value = response

        with pytest.raises(OpenRouterError) as raised:
            fetch_response_local("hi")

        assert raised.value.provider == "ollama"
        assert raised.value.failure_kind == "invalid_model"
        assert raised.value.retryable is False

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_payload_includes_original_system_prompt(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"response": "Hello!"},
        )
        fetch_response_local("hi")
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        assert payload["prompt"].startswith(f"{SYSTEM_PROMPT}\n\nUser: hi\nAssistant:")

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_local_prompt_keeps_the_latest_transcript_as_user_content(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"response": "theek hai"},
        )

        message = "User: Hinglish matlab tha mera\n\nAssistant: Theek hai.\n\nUser: Hindi mein hi bolo na."
        fetch_response_local(message)

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        assert payload["prompt"] == f"{build_system_prompt(message)}\n\nUser: {message}\nAssistant:"

    @patch("aashi.ui.services.local_ai.requests.post")
    def test_local_prompt_appends_the_original_generation_boundary(
        self, mock_post: MagicMock
    ) -> None:
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"response": "Hello!"},
        )

        fetch_response_local("hi")

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        assert payload["prompt"].endswith("\n\nUser: hi\nAssistant:")


# ── fetch_response_hybrid routing ───────────────────────────────────────────


class TestFetchResponseHybrid:
    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    def test_history_routing_uses_the_latest_user_turn(
        self, mock_local: MagicMock, _mock_internet: MagicMock
    ) -> None:
        mock_local.return_value = "local reply"
        history = "User: explain decorators\n\nAssistant: okay\n\nUser: hi"

        assert fetch_response_hybrid(history) == "local reply"
        mock_local.assert_called_once_with(history)

    @patch("aashi.ui.services.local_ai.MODE", "local")
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    def test_local_mode_always_calls_local(
        self, mock_local: MagicMock
    ) -> None:
        mock_local.return_value = "local reply"
        result = fetch_response_hybrid("anything")
        assert result == "local reply"
        mock_local.assert_called_once_with("anything")

    @patch("aashi.ui.services.local_ai.MODE", "online")
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_online_mode_always_calls_openrouter(
        self, mock_online: MagicMock
    ) -> None:
        mock_online.return_value = "remote reply"
        result = fetch_response_hybrid("anything")
        assert result == "remote reply"
        mock_online.assert_called_once_with("anything")

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=False)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    def test_hybrid_falls_back_to_local_when_offline(
        self, mock_local: MagicMock, _mock_internet: MagicMock
    ) -> None:
        mock_local.return_value = "offline reply"
        result = fetch_response_hybrid("anything")
        assert result == "offline reply"

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.is_complex", return_value=False)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    def test_hybrid_uses_local_for_simple_message(
        self, mock_local: MagicMock, *_: MagicMock
    ) -> None:
        mock_local.return_value = "simple local"
        result = fetch_response_hybrid("hi")
        assert result == "simple local"

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.is_complex", return_value=True)
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_hybrid_uses_online_for_complex_message(
        self, mock_online: MagicMock, *_: MagicMock
    ) -> None:
        mock_online.return_value = "complex online"
        result = fetch_response_hybrid("explain this complex project in detail")
        assert result == "complex online"

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.is_complex", return_value=True)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_hybrid_falls_back_to_local_when_online_fails(
        self, mock_online: MagicMock, mock_local: MagicMock, *_: MagicMock
    ) -> None:
        mock_online.side_effect = OpenRouterError("API down")
        mock_local.return_value = "fallback local"
        result = fetch_response_hybrid("explain this in detail")
        assert result == "fallback local"

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.is_complex", return_value=False)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_hybrid_preserves_both_provider_failures_for_diagnostics(
        self, mock_online: MagicMock, mock_local: MagicMock, *_: MagicMock
    ) -> None:
        mock_local.side_effect = OpenRouterError("Ollama connection refused")
        mock_online.side_effect = OpenRouterError(
            "Missing API key. Set OPENROUTER_API_KEY environment variable."
        )

        with pytest.raises(HybridProviderError) as raised:
            fetch_response_hybrid("hi")

        assert "Ollama connection refused" in str(raised.value.local_error)
        assert "Missing API key" in str(raised.value.online_error)
        message = format_provider_error(raised.value)
        assert "Ollama" in message
        assert "OPENROUTER_API_KEY" in message
        assert "Ollama connection refused" not in message

    @patch("aashi.ui.services.local_ai.MODE", "hybrid")
    @patch("aashi.ui.services.local_ai.has_internet", return_value=True)
    @patch("aashi.ui.services.local_ai.is_complex", return_value=False)
    @patch("aashi.ui.services.local_ai.fetch_response_local")
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_ollama_timeout_attempts_openrouter_once_and_preserves_both_causes(
        self, mock_online: MagicMock, mock_local: MagicMock, *_: MagicMock
    ) -> None:
        mock_local.side_effect = OpenRouterError(
            "Ollama read timeout",
            provider="ollama",
            failure_kind="timeout",
            retryable=True,
        )
        mock_online.side_effect = OpenRouterError("OpenRouter HTTP failure")

        with pytest.raises(HybridProviderError) as raised:
            fetch_response_hybrid("hinglish mtlb tha mera")

        mock_local.assert_called_once()
        mock_online.assert_called_once()
        assert getattr(raised.value.local_error, "failure_kind", None) == "timeout"
        message = format_provider_error(raised.value)
        assert "local Ollama request timed out" in message
        assert "OpenRouter request failed after the fallback attempt" in message


# ── _enforce_identity ────────────────────────────────────────────────────────


class TestEnforceIdentity:
    def test_normal_reply_passes_through(self) -> None:
        assert _enforce_identity("Sure, here is the answer.") == "Sure, here is the answer."

    def test_gpt_leak_replaced(self) -> None:
        assert _enforce_identity("I am GPT and I can help.") == "My name is Aashi."

    def test_phi_leak_replaced(self) -> None:
        assert _enforce_identity("I am Phi3, a model from Microsoft.") == "My name is Aashi."

    def test_llama_leak_replaced(self) -> None:
        assert _enforce_identity("I am Llama, an open-source model.") == "My name is Aashi."

    def test_deepseek_leak_replaced(self) -> None:
        assert _enforce_identity("I am DeepSeek, a language model.") == "My name is Aashi."

    def test_ai_model_leak_replaced(self) -> None:
        assert _enforce_identity("I am an AI model built by OpenAI.") == "My name is Aashi."

    def test_language_model_leak_replaced(self) -> None:
        assert _enforce_identity("I am a language model.") == "My name is Aashi."

    def test_case_insensitive(self) -> None:
        assert _enforce_identity("I AM GPT.") == "My name is Aashi."

    def test_partial_match_not_triggered(self) -> None:
        assert _enforce_identity("I am good at coding.") == "I am good at coding."

    @pytest.mark.parametrize(
        ("reply", "expected"),
        (
            ("Hey, I'm Kartik. How are you?", "Hey, I'm Aashi. How are you?"),
            ("My name is Kartik.", "My name is Aashi."),
            ("I AM KARTIK", "I AM Aashi"),
        ),
    )
    def test_wrong_user_name_is_not_allowed_as_the_assistant_name(
        self, reply: str, expected: str
    ) -> None:
        assert _enforce_identity(reply) == expected

    def test_user_name_in_a_third_person_fact_is_preserved(self) -> None:
        reply = "Kartik is the user, and I can help with that."
        assert _enforce_identity(reply) == reply

    @pytest.mark.parametrize(
        "reply",
        ("I am Ansh.", "My name is GPT.", "I'm a language model."),
    )
    def test_legacy_or_model_identity_leaks_are_replaced(self, reply: str) -> None:
        assert _enforce_identity(reply).endswith("Aashi.")

    @patch("aashi.ui.services.local_ai.MODE", "online")
    @patch("aashi.ui.services.local_ai.fetch_response")
    def test_online_provider_reply_cannot_claim_the_user_identity(
        self, mock_online: MagicMock
    ) -> None:
        mock_online.return_value = "I am Kartik."

        assert fetch_response_hybrid("What's your name?") == "I am Aashi."
