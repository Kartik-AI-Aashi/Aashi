"""Speech pipeline contract tests that do not require physical audio devices."""

from __future__ import annotations

from aashi.automation import LocalSpeechAdapter, NullSpeechAdapter, SpeechOperation, SpeechService, SpeechState


def test_injected_speech_adapter_preserves_transcript_and_interrupts_output() -> None:
    spoken: list[str] = []
    stopped: list[bool] = []
    adapter = LocalSpeechAdapter(
        recognizer=lambda: "open HIH in VS Code",
        synthesizer=spoken.append,
        stopper=lambda: stopped.append(True),
    )
    service = SpeechService(adapter)

    listened = service.listen()
    spoken_event = service.speak("Done")
    stopped_event = service.stop()

    assert listened.state is SpeechState.IDLE
    assert listened.text == "open HIH in VS Code"
    assert spoken_event.text == "Done"
    assert spoken == ["Done"]
    assert stopped == [True]
    assert stopped_event.state is SpeechState.IDLE


def test_speech_events_distinguish_tts_completion_from_microphone_transcript() -> None:
    service = SpeechService(LocalSpeechAdapter(recognizer=lambda: "hello", synthesizer=lambda _: None))

    listened = service.listen()
    spoken = service.speak("assistant answer")

    assert listened.operation is SpeechOperation.LISTEN
    assert listened.text == "hello"
    assert spoken.operation is SpeechOperation.SPEAK
    assert spoken.text == "assistant answer"


def test_null_speech_adapter_is_explicitly_disabled_and_does_not_fake_input() -> None:
    service = SpeechService(NullSpeechAdapter())

    event = service.listen()

    assert event.state is SpeechState.DISABLED
    assert event.text == ""
    assert service.status.transcript == ""
