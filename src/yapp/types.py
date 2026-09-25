"""Dataclasses shared across modules. No logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Intent(StrEnum):
    OPEN_APP = "open_app"
    TYPE_TEXT = "type_text"
    OPEN_FILE = "open_file"
    PRESS_KEY = "press_key"
    SCREEN = "screen_action"
    UNDO = "undo"
    CLEANUP = "cleanup"
    NONE = "none"


@dataclass(frozen=True)
class App:
    key: str  # stable slug, e.g. "notes"
    name: str  # display name passed to `open -a`, e.g. "Notes"
    description: str  # one line shown to Jev


@dataclass(frozen=True)
class Decision:
    tail: str
    intent: Intent
    intent_confidence: float
    intent_probabilities: dict[str, float]
    app: App | None = None
    app_confidence: float | None = None
    text: str | None = None
    key_combo: str | None = None
    file_query: str | None = None
    is_complete: float = 0.0
    ends_dictation: float = 0.0
    is_addressed: float = 1.0
    consumed_words: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class Outcome(StrEnum):
    EXECUTE = "execute"
    WAIT = "wait"  # instruction not complete yet: keep the tail, next tick
    IGNORE = "ignore"  # below threshold or intent none: quiet


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str


@dataclass(frozen=True)
class Executed:
    """What the executor last did, so `undo` can reverse it."""

    decision: Decision
    result: Result
    typed_chars: int = 0  # for dictation undo
