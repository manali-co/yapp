"""Permission modes: Jev scores how harmful the concrete action is; above the line, ask.

The action is described the way it will be carried out ("press Empty Trash in Finder",
"open Terminal", "dictate into Mail"), so the score reflects what the model decided, not
just the sentence the user said.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from typesafe_sdk import Noul

from yapp.jev import JevError, JevLike

Asker = Callable[[str], bool]
Harm = Callable[[str, str], tuple[float, int]]  # (action, context) -> (harm, latency_ms)


class Mode(StrEnum):
    ASK = "ask"  # default: anything at or above 0.30 harm waits for a yes
    AUTO = "auto"  # opt-in: only near-certain harm (≥ 0.85) waits


THRESHOLD = {Mode.ASK: 0.30, Mode.AUTO: 0.85}


@dataclass(frozen=True)
class GuardVerdict:
    action: str
    harm: float
    threshold: float
    asked: bool
    approved: bool
    latency_ms: int = 0

    @property
    def allowed(self) -> bool:
        return (not self.asked) or self.approved

    def describe(self) -> str:
        if not self.asked:
            return f"harm {self.harm:.2f} < {self.threshold:.2f}: go"
        return f"harm {self.harm:.2f} ≥ {self.threshold:.2f}: " + (
            "approved" if self.approved else "not approved"
        )


def jev_harm(jev: JevLike, criteria: Any, instructions: str) -> Harm:
    question = Noul(instructions=instructions, criteria=criteria)

    def score(action: str, context: str) -> tuple[float, int]:
        resp = jev.ask({"action": action, "screen": context}, {"is_harmful": question})
        return resp.noul("is_harmful"), resp.latency_ms

    return score


class Guard:
    def __init__(
        self,
        harm: Harm,
        ask: Asker,
        *,
        mode: Mode = Mode.ASK,
        log: Callable[[str], None] = lambda s: None,
    ) -> None:
        self.harm = harm
        self.ask = ask
        self.mode = mode
        self.log = log
        self.history: list[GuardVerdict] = []

    @property
    def threshold(self) -> float:
        return THRESHOLD[self.mode]

    def check(self, action: str, context: str = "") -> GuardVerdict:
        try:
            harm, ms = self.harm(action, context)
        except JevError as e:
            # No score, no action: a failed call never executes anything.
            self.log(f"guard: jev error ({e}); treating '{action}' as harmful")
            harm, ms = 1.0, 0
        asked = harm >= self.threshold
        approved = self.ask(action) if asked else False
        v = GuardVerdict(action, harm, self.threshold, asked, approved, ms)
        self.history.append(v)
        self.log(f"guard mode={self.mode}: {action} → {v.describe()} ({ms} ms)")
        return v
