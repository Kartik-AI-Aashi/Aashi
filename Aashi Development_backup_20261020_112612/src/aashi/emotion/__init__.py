"""Aashi's emotion / feelings / expression layer.

A small, independent, removable component that gives replies a natural,
context-appropriate personality *around* the existing pipeline. See
:mod:`aashi.emotion.layer` for the architecture and guarantees.

The package depends on nothing else in Aashi at import time (it only reads the
routing predicate lazily) and never touches storage or the network.
"""

from aashi.emotion.detector import STRESS_MEMORY_TURNS, Session, detect
from aashi.emotion.emotions import ContextKind, Emotion, EmotionContext
from aashi.emotion.layer import (
    ASSISTANT_NAME,
    EMOTION_LAYER_ENABLED,
    USER_NAME,
    EmotionLayer,
    Prepared,
)

__all__ = [
    "ASSISTANT_NAME",
    "EMOTION_LAYER_ENABLED",
    "STRESS_MEMORY_TURNS",
    "USER_NAME",
    "ContextKind",
    "Emotion",
    "EmotionContext",
    "EmotionLayer",
    "Prepared",
    "Session",
    "detect",
]
