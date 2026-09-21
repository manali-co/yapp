"""Stub until Task 11: learned examples from act/undo."""

from __future__ import annotations

from yapp.config import Config
from yapp.types import Decision


class Learning:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def examples(self) -> dict[str, list[str]]:
        return {}

    def negatives(self) -> dict[str, list[str]]:
        return {}

    def executed(self, d: Decision, at: float) -> None:
        return None

    def undone(self, at: float) -> None:
        return None

    def flush(self, now: float) -> None:
        return None
