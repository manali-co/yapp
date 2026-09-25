"""Hand over or work in parallel? Jev decides from what the user was doing when they spoke."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typesafe_sdk import Choice

from yapp.jev import JevLike

HAND_OVER = "hand_over"
PARALLEL = "parallel"
THRESHOLD = 0.60

CRITERIA: dict[str, Any] = {
    HAND_OVER: {
        "what": (
            "Bring the work in front of the user: they are waiting for it, the instruction "
            "is about the app already in front, or they have been idle for a while"
        ),
        "examples": [
            "open notes (the user has been idle for 40 seconds)",
            "zoom in (the app in front is the target)",
            "show me the downloads (the user asked to see something)",
            "search for cats (the user just switched to Chrome themselves)",
        ],
    },
    PARALLEL: {
        "what": (
            "Do it on the side without taking the user's window or keyboard: they were "
            "typing or clicking in another app seconds ago, or they said so"
        ),
        "examples": [
            "open text edit and type the shopping list (the user is typing in Slack right now)",
            "in the background open chrome and search for flights",
            "while I finish this, make a new note called ideas",
            "open reminders and add buy stamps (the user is in a video call)",
        ],
    },
}


@dataclass(frozen=True)
class Placement:
    mode: str
    confidence: float
    latency_ms: int = 0


def seconds_since_input() -> float:
    """Seconds since the user's last key or click (Quartz HID idle time)."""
    import Quartz

    return float(
        Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType
        )
    )


def decide_placement(
    jev: JevLike,
    instruction: str,
    *,
    front_app: str,
    target_app: str,
    idle_seconds: float,
    display_count: int,
) -> Placement:
    state = {
        "instruction": instruction,
        "app_in_front_when_spoken": front_app,
        "instruction_target_app": target_app or "unknown",
        "seconds_since_user_typed_or_clicked": round(idle_seconds, 1),
        "displays": display_count,
    }
    q = Choice(
        instructions=(
            "Yapp is about to carry out `instruction`. Should it hand the work over to the "
            "user (bring it in front, use their keyboard) or work in parallel on the side?"
        ),
        criteria=CRITERIA,
    )
    resp = jev.ask(state, {"placement": q})
    r = resp.choice("placement")
    mode = PARALLEL if r.key == PARALLEL and r.confidence >= THRESHOLD else HAND_OVER
    return Placement(mode, r.confidence, resp.latency_ms)
