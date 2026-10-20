"""The vocabulary of the emotion layer: moods, context kinds and the result type.

Moods are *not* models. They are presentation styles that colour how a reply is
worded; the facts of a reply always come from the existing Aashi pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["ContextKind", "Emotion", "EmotionContext"]


class Emotion(str, Enum):
    """The twenty moods Aashi can express."""

    CARING = "caring"
    FRIENDLY = "friendly"
    PLAYFUL = "playful"  # playful / teasing
    CHILL = "chill"
    TEACHER = "teacher"  # teacher / encouraging
    MILD_GUSSA = "mild_gussa"  # playful anger, never genuine hostility
    MOTIVATIONAL = "motivational"
    EMOTIONAL = "emotional"
    COMFORTING = "comforting"
    SARCASTIC = "sarcastic"
    CUTE = "cute"
    EXCITED = "excited"
    CURIOUS = "curious"
    PROUD = "proud"
    CONCERNED = "concerned"
    APOLOGETIC = "apologetic"
    CELEBRATORY = "celebratory"
    CALM = "calm"
    FOCUSED = "focused"  # focused / serious: the default for technical work
    EMPATHETIC = "empathetic"


class ContextKind(str, Enum):
    """The broad kind of conversation the detector recognised."""

    TECHNICAL = "technical"
    CASUAL = "casual"
    CARING = "caring"
    PLAYFUL = "playful"
    MOTIVATIONAL = "motivational"
    COMFORTING = "comforting"
    STUDY = "study"
    ACHIEVEMENT = "achievement"
    CORRECTION = "correction"  # the user says Aashi got something wrong
    CRISIS = "crisis"
    OTHER = "other"


@dataclass(frozen=True)
class EmotionContext:
    """What the detector concluded about one user message.

    Attributes:
        emotion: The primary mood to express.
        kind: The broad conversation kind.
        secondary: Supporting moods, strongest first.
        expressive: ``True`` when personality should show. When ``False`` (the
            technical / neutral default) the prompt and reply are left exactly
            as the existing pipeline produced them.
        greeting: A bare greeting or small talk ("hi", "kaise ho"): a short,
            natural reply with no thinking-style preamble.
        carried: The mood came from earlier in this conversation (for example
            the user said they were stressed a moment ago), not from this
            message itself.
        serious: A situation that calls for care and no jokes at all.
        plain: Casual conversation: the reply should read like a person texting,
            with no headings, bullets, bold or "Response / Takeaway" labels.
            Explanations, study help and technical answers keep their structure.
    """

    emotion: Emotion
    kind: ContextKind
    secondary: tuple[Emotion, ...] = ()
    expressive: bool = False
    greeting: bool = False
    carried: bool = False
    serious: bool = False
    plain: bool = False

    @property
    def moods(self) -> tuple[Emotion, ...]:
        """Primary mood followed by the secondary ones."""
        return (self.emotion, *self.secondary)


NEUTRAL = EmotionContext(Emotion.FOCUSED, ContextKind.OTHER)
"""No emotion: the prompt and reply pass through untouched."""
