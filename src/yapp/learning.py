"""Examples from acting, not asking. Executed + no undo = positive; undo = negative."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from yapp.config import Config
from yapp.types import Decision, Intent

KEEP_POSITIVE = 5
KEEP_NEGATIVE = 3


def option_for(d: Decision) -> str | None:
    if d.intent == Intent.OPEN_APP and d.app is not None:
        return d.app.key
    if d.intent == Intent.PRESS_KEY and d.key_combo:
        return d.key_combo
    return None


@dataclass
class _Pending:
    option: str
    phrase: str
    at: float


class Learning:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pos: dict[str, list[str]] = defaultdict(list)
        self._neg: dict[str, list[str]] = defaultdict(list)
        self._pending: list[_Pending] = []
        self._load()

    def _load(self) -> None:
        p = self.cfg.learned_path
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            row = json.loads(line)
            bucket = self._pos if row["label"] == "positive" else self._neg
            bucket[row["option"]].append(row["phrase"])

    def _append(self, option: str, phrase: str, label: str) -> None:
        p = self.cfg.learned_path
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({"option": option, "phrase": phrase, "label": label}) + "\n")

    def examples(self) -> dict[str, list[str]]:
        return {k: v[-KEEP_POSITIVE:] for k, v in self._pos.items() if v}

    def negatives(self) -> dict[str, list[str]]:
        return {k: v[-KEEP_NEGATIVE:] for k, v in self._neg.items() if v}

    def executed(self, d: Decision, at: float) -> None:
        self.flush(at)
        opt = option_for(d)
        if opt is None:
            return
        phrase = " ".join(d.tail.split()[: d.consumed_words])
        self._pending.append(_Pending(opt, phrase, at))

    def undone(self, at: float) -> None:
        """The most recent pending action was reversed: it becomes a negative example."""
        if not self._pending:
            return
        p = self._pending.pop()
        self._neg[p.option].append(p.phrase)
        self._append(p.option, p.phrase, "negative")

    def flush(self, now: float) -> None:
        due = [p for p in self._pending if now - p.at >= self.cfg.learn_after_seconds]
        for p in due:
            self._pos[p.option].append(p.phrase)
            self._append(p.option, p.phrase, "positive")
        self._pending = [p for p in self._pending if p not in due]
