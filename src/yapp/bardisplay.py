"""Runner display hooks -> avatar states and pill text. The runner never knows about the bar."""

from __future__ import annotations

import math
import re

from yapp.bar import Bar
from yapp.types import Decision, Outcome, Result, Verdict

# radians the avatar stretches toward on execute: right, up-right, down, left
DIRECTION = {"open": 0.0, "press": -1.2, "dictate": 1.4, "undo": math.pi}
REFUSE_COPY = "Won't do that: could delete something"
UNSURE_COPY = "Not sure what you meant"


def result_copy(message: str) -> str:
    m = re.match(r"opened (.+)", message)
    if m:
        return f"Opening {m.group(1)}"
    if message.startswith(("typed", "dictating", "nothing to type")):
        return "Typing…"
    if message.startswith(("quit ", "erased", "closed", "sent cmd+z", "undone")):
        return "Undone"
    return message[:1].upper() + message[1:]


class BarDisplay:
    def __init__(self, bar: Bar) -> None:
        self.bar = bar
        self.dictating = False
        self.acted = False
        self._words = 0

    def begin(self) -> None:
        self._words = 0
        self.acted = False
        self.dictating = False
        self.bar.decision("")
        self.bar.transcript("", "")
        self.bar.set_state("listening", level=0.0)

    def end(self, acted: bool) -> None:
        if acted:
            self.bar.set_state("done")
        else:
            self.bar.set_state("unsure")
            self.bar.decision(UNSURE_COPY, muted=True)

    def status(self, msg: str) -> None:
        return None

    def listening(self, level: float) -> None:
        self.bar.level(level)

    def thinking(self) -> None:
        self.bar.set_state("thinking")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        self.bar.transcript(" ".join(committed), " ".join(pending))
        if len(committed) > self._words:
            self.bar.commit()
        self._words = len(committed)

    def show_decision(self, d: Decision) -> None:
        self.bar.confidence(d.intent_confidence)

    def _resting(self) -> None:
        self.bar.set_state("dictating" if self.dictating else "listening")

    def show_verdict(self, v: Verdict) -> None:
        match v.outcome:
            case Outcome.EXECUTE:
                verb = v.reason.split()[0]
                self.acted = True
                self.bar.set_state("acting", direction=DIRECTION.get(verb, 0.0))
            case Outcome.REFUSE:
                self.bar.set_state("unsure")
                self.bar.decision(REFUSE_COPY)
            case _:
                self._resting()

    def show_result(self, r: Result) -> None:
        if r.ok:
            self.bar.decision(result_copy(r.message))
            if r.message == "dictating":
                self.dictating = True
        else:
            self.bar.decision(result_copy(r.message), muted=True)

    def show_error(self, msg: str) -> None:
        self.bar.set_state("error")
        self.bar.decision(msg, muted=True)
