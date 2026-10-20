"""Small speech ports and adapters that do not import microphone packages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import os

from aashi.constants import ENV_VAR_SPEECH_LANGUAGE
from typing import Protocol

__all__ = [
    "LocalSpeechAdapter",
    "NullSpeechAdapter",
    "SpeechAdapter",
    "SpeechEvent",
    "SpeechOperation",
    "SpeechInput",
    "SpeechOutput",
    "SpeechService",
    "SpeechState",
    "SpeechStatus",
    "create_default_speech_adapter",
]


class SpeechState(str, Enum):
    """Lifecycle state exposed to a UI or other caller."""

    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"
    DISABLED = "disabled"
    ERROR = "error"


class SpeechOperation(str, Enum):
    """Which direction produced a speech event."""

    LISTEN = "listen"
    SPEAK = "speak"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class SpeechEvent:
    """A speech operation's observable result."""

    state: SpeechState
    text: str = ""
    error: str | None = None
    operation: SpeechOperation = SpeechOperation.LISTEN


@dataclass(frozen=True, slots=True)
class SpeechStatus:
    """Current speech state and last transcript/error."""

    state: SpeechState = SpeechState.IDLE
    transcript: str = ""
    error: str | None = None


class SpeechInput(Protocol):
    """Port for a recognizer implementation."""

    def recognize(self) -> str | None:
        """Return one transcript, or ``None`` when no speech is available."""


class SpeechOutput(Protocol):
    """Port for a text-to-speech implementation."""

    def speak(self, text: str) -> None:
        """Speak one text value."""

    def stop(self) -> None:
        """Interrupt speech when the backend supports it."""


class SpeechAdapter(SpeechInput, SpeechOutput, Protocol):
    """Combined optional adapter port."""


class NullSpeechAdapter:
    """Safe no-op adapter for machines without speech hardware or packages."""

    def recognize(self) -> str | None:
        return None

    def speak(self, text: str) -> None:
        del text

    def stop(self) -> None:
        return None


class LocalSpeechAdapter:
    """Adapter around caller-provided local functions.

    The functions can wrap any locally installed recognizer/synthesizer, but
    this class itself never imports or requires microphone packages.
    """

    def __init__(
        self,
        *,
        recognizer: Callable[[], str | None] | None = None,
        synthesizer: Callable[[str], None] | None = None,
        stopper: Callable[[], None] | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._synthesizer = synthesizer
        self._stopper = stopper

    def recognize(self) -> str | None:
        return None if self._recognizer is None else self._recognizer()

    def speak(self, text: str) -> None:
        if self._synthesizer is not None:
            self._synthesizer(text)

    def stop(self) -> None:
        if self._stopper is not None:
            self._stopper()


def create_default_speech_adapter() -> SpeechAdapter:
    """Build optional speech adapters when the user installed them.

    The base application does not require audio packages or a paid service.
    When ``SpeechRecognition`` and ``pyttsx3`` are present, this adapter uses
    the former's configured recognizer and the latter's local system voice.
    Recognition language is selected with ``AASHI_SPEECH_LANGUAGE`` (default
    ``en-IN``; ``hi-IN`` is also suitable for Hindi).  Import failures return a
    safe null adapter rather than preventing text chat from starting.
    """
    try:
        import pyttsx3
        import speech_recognition as sr
    except ImportError:
        return NullSpeechAdapter()

    try:
        recognizer = sr.Recognizer()
        engine = pyttsx3.init()
    except Exception:
        return NullSpeechAdapter()
    language = os.environ.get(ENV_VAR_SPEECH_LANGUAGE, "en-IN")

    def recognize() -> str | None:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.25)
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=30)
        try:
            return recognizer.recognize_google(audio, language=language)
        except (sr.UnknownValueError, sr.RequestError):
            return None

    def speak(text: str) -> None:
        engine.say(text)
        engine.runAndWait()

    def stop() -> None:
        engine.stop()

    return LocalSpeechAdapter(recognizer=recognize, synthesizer=speak, stopper=stop)


class SpeechService:
    """Stateful coordinator for one injected speech adapter."""

    def __init__(self, adapter: SpeechAdapter | None = None) -> None:
        self._adapter = adapter or NullSpeechAdapter()
        self._status = SpeechStatus(
            SpeechState.DISABLED if isinstance(self._adapter, NullSpeechAdapter) else SpeechState.IDLE
        )

    @property
    def status(self) -> SpeechStatus:
        """Current immutable speech status."""
        return self._status

    def listen(self) -> SpeechEvent:
        """Perform one recognition request and update state."""
        if isinstance(self._adapter, NullSpeechAdapter):
            return SpeechEvent(SpeechState.DISABLED, operation=SpeechOperation.LISTEN)
        self._status = SpeechStatus(SpeechState.LISTENING, self._status.transcript)
        try:
            text = self._adapter.recognize() or ""
        except Exception as exc:
            self._status = SpeechStatus(SpeechState.ERROR, self._status.transcript, str(exc))
            return SpeechEvent(SpeechState.ERROR, error=str(exc), operation=SpeechOperation.LISTEN)
        transcript = text or self._status.transcript
        self._status = SpeechStatus(SpeechState.IDLE, transcript)
        return SpeechEvent(SpeechState.IDLE, text or "", operation=SpeechOperation.LISTEN)

    def speak(self, text: str) -> SpeechEvent:
        """Speak one text value and update state."""
        if not isinstance(text, str) or not text.strip():
            return SpeechEvent(
                SpeechState.ERROR,
                error="Speech text must be non-empty",
                operation=SpeechOperation.SPEAK,
            )
        self._status = SpeechStatus(SpeechState.SPEAKING, self._status.transcript)
        try:
            self._adapter.speak(text)
        except Exception as exc:
            self._status = SpeechStatus(SpeechState.ERROR, self._status.transcript, str(exc))
            return SpeechEvent(SpeechState.ERROR, error=str(exc), operation=SpeechOperation.SPEAK)
        self._status = SpeechStatus(SpeechState.IDLE, self._status.transcript)
        return SpeechEvent(SpeechState.IDLE, text, operation=SpeechOperation.SPEAK)

    def stop(self) -> SpeechEvent:
        """Interrupt the current synthesizer when its adapter supports it."""
        self._status = SpeechStatus(SpeechState.IDLE, self._status.transcript)
        try:
            stopper = getattr(self._adapter, "stop", None)
            if callable(stopper):
                stopper()
        except Exception as exc:
            self._status = SpeechStatus(SpeechState.ERROR, self._status.transcript, str(exc))
            return SpeechEvent(SpeechState.ERROR, error=str(exc), operation=SpeechOperation.STOP)
        return SpeechEvent(SpeechState.IDLE, operation=SpeechOperation.STOP)

    def reset(self) -> SpeechStatus:
        """Return to idle (or disabled when using the null adapter)."""
        state = SpeechState.DISABLED if isinstance(self._adapter, NullSpeechAdapter) else SpeechState.IDLE
        self._status = SpeechStatus(state, self._status.transcript)
        return self._status
