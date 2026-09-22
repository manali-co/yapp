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


def level_gain(rms: float) -> float:
    """Mic RMS of speech at a laptop is ~0.02-0.1; map that onto the avatar's 0-1 ripple."""
    return min(1.0, float(max(0.0, rms * 12) ** 0.7))


class BarDisplay:
    def __init__(self, bar: Bar) -> None:
        self.bar = bar
        self.dictating = False
        self.acted = False
        self._words = 0
        self._state = ""

    def _set(self, name: str, **opts: object) -> None:
        """Only send a state when it changes; re-sending resets the avatar's springs."""
        if name == self._state and not opts:
            return
        self._state = name
        self.bar.set_state(name, **opts)

    def begin(self) -> None:
        self._words = 0
        self.acted = False
        self.dictating = False
        self._state = ""
        self.bar.decision("")
        self.bar.transcript("", "")
        self._set("listening", level=0.0)

    def end(self, acted: bool) -> None:
        if acted:
            self._set("done")
        else:
            self._set("unsure")
            self.bar.decision(UNSURE_COPY, muted=True)

    def status(self, msg: str) -> None:
        return None

    def countdown(self, seconds: float | None) -> None:
        self.bar.countdown(seconds)

    def listening(self, level: float) -> None:
        self.bar.level(level_gain(level))

    def thinking(self) -> None:
        self._set("thinking")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        self.bar.transcript(" ".join(committed), " ".join(pending))
        if len(committed) > self._words:
            self.bar.commit()
        self._words = len(committed)

    def show_decision(self, d: Decision) -> None:
        self.bar.confidence(d.intent_confidence)

    def _resting(self) -> None:
        self._set("dictating" if self.dictating else "listening")

    def show_verdict(self, v: Verdict) -> None:
        match v.outcome:
            case Outcome.EXECUTE:
                verb = v.reason.split()[0]
                self.acted = True
                self._state = "acting"
                self.bar.set_state("acting", direction=DIRECTION.get(verb, 0.0))
            case Outcome.REFUSE:
                self._set("unsure")
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
        self._set("error")
        self.bar.decision(msg, muted=True)
