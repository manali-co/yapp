"""Was the spoken reply a yes, a no, or something else? One Jev choice, tiny state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typesafe_sdk import Choice

from yapp.jev import JevLike


@dataclass(frozen=True)
class Reply:
    kind: str  # approve | deny | unrelated
    confidence: float
    latency_ms: int = 0


def classify_reply(reply: str, action: str, jev: JevLike, criteria: dict[str, Any]) -> Reply:
    q = Choice(
        instructions=(
            "Yapp asked the user whether it may carry out `action`. `reply` is what was heard "
            "next. Is it permission, a refusal, or unrelated speech?"
        ),
        criteria=criteria,
    )
    resp = jev.ask({"action": action, "reply": reply}, {"reply": q})
    r = resp.choice("reply")
    return Reply(r.key, r.confidence, resp.latency_ms)
