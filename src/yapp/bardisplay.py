"""Runner display hooks -> avatar states and pill text. The runner never knows about the bar."""

from __future__ import annotations

import math
import re

from yapp.bar import Bar
from yapp.types import Decision, Outcome, Result, Verdict

# radians the avatar stretches toward on execute: right, up-right, down, left
DIRECTION = {"open": 0.0, "press": -1.2, "dictate": 1.4, "undo": math.pi}
ASK_HINT = "say yes or no · ⏎ / esc"
UNSURE_COPY = "Not sure what you meant"


def result_copy(message: str) -> str:
    m = re.match(r"opened (.+)", message)
    if m:
        return f"Opening {m.group(1)}"
    m = re.match(r"typed '(.+)' into (.+)", message)
    if m:
        return f"Typed “{m.group(1)}”"
    if message.startswith(("typed", "dictating", "nothing to type")):
        return "Typing…"
    if message.startswith(("quit ", "erased", "closed", "sent cmd+z", "undone")):
        return "Undone"
    m = re.match(r"pressed (?:menu: )?(.+?)(?: \(.*\))?$", message)
    if m:
        return f"Pressed {m.group(1).split(' › ')[-1]}"
    return message[:1].upper() + message[1:]


def level_gain(rms: float) -> float:
    """Mic RMS of speech at a laptop is ~0.02-0.1; map that onto the avatar's 0-1 ripple."""
    return min(1.0, float(max(0.0, rms * 12) ** 0.7))


def error_kind(msg: str) -> str:
    """Which error frame the page should show for an error message."""
    low = msg.lower()
    if "mic" in low or "audio" in low or "input device" in low:
        return "error-mic"
    return "error-jev"


class BarDisplay:
    def __init__(self, bar: Bar, *, silence_total: float = 4.0) -> None:
        self.bar = bar
        self.silence_total = silence_total
        self.dictating = False
        self.acted = False
        self.hint_index: int | None = None
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
        self.bar.hint(self.hint_index if self.hint_index is not None else False)

    def end(self, acted: bool) -> None:
        if acted:
            self._set("done")
        else:
            self._set("unsure")
            self.bar.decision(UNSURE_COPY, muted=True)

    def status(self, msg: str) -> None:
        return None

    def countdown(self, seconds: float | None) -> None:
        self.bar.countdown(seconds, total=self.silence_total)

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
            case _:
                self._resting()

    def show_result(self, r: Result) -> None:
        if r.ok:
            copy = result_copy(r.message)
            self.bar.decision(copy)
            if copy == "Undone":
                self._set("undone")
            if r.message == "dictating":
                self.dictating = True
        else:
            self.bar.decision(result_copy(r.message), muted=True)

    def asking(self, action: str) -> None:
        """Wait for a spoken yes: the pill shows the action and keeps listening."""
        self._set("listening")
        self.bar.decision(f"May I {action}?")
        self.bar.hint(ASK_HINT)

    def answered(self, approved: bool) -> None:
        self.bar.hint(False)
        self.bar.decision(
            "Okay, going ahead" if approved else "Okay, not doing that", muted=not approved
        )
        if not approved:
            self._set("unsure")

    def show_error(self, msg: str) -> None:
        self._set(error_kind(msg))
        self.bar.decision(msg, muted=True)
