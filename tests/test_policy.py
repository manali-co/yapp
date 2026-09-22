import pytest

from yapp.config import Thresholds
from yapp.policy import decide
from yapp.types import App, Decision, Intent, Outcome

T = Thresholds()
NOTES = App("notes", "Notes", "Launch Notes")


def d(**kw: object) -> Decision:
    base: dict[str, object] = dict(
        tail="x",
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={},
        app=NOTES,
        app_confidence=0.9,
        is_complete=0.9,
    )
    base.update(kw)
    return Decision(**base)  # type: ignore[arg-type]


def test_incomplete_waits() -> None:
    assert decide(d(is_complete=0.3), T).outcome == Outcome.WAIT


def test_open_app_executes_at_threshold() -> None:
    assert decide(d(intent_confidence=T.open_app), T).outcome == Outcome.EXECUTE


def test_open_app_below_threshold_ignores() -> None:
    assert decide(d(intent_confidence=0.59), T).outcome == Outcome.IGNORE


def test_open_app_unsure_ignores() -> None:
    assert decide(d(app=None), T).outcome == Outcome.IGNORE


def test_destructive_refuses_even_when_confident() -> None:
    v = decide(d(is_destructive=0.6), T)
    assert v.outcome == Outcome.REFUSE and "delete" in v.reason


def test_type_text_enters_dictation() -> None:
    v = decide(d(intent=Intent.TYPE_TEXT, app=None, text="", intent_confidence=0.75), T)
    assert v.outcome == Outcome.EXECUTE


def test_dictating_keeps_typing_unless_ends() -> None:
    v = decide(d(intent=Intent.OPEN_APP, ends_dictation=0.2), T, dictating=True)
    assert v.outcome == Outcome.IGNORE and v.reason == "dictating"
    v2 = decide(d(intent=Intent.OPEN_APP, ends_dictation=0.9), T, dictating=True)
    assert v2.outcome == Outcome.EXECUTE


def test_undo_needs_last_action() -> None:
    u = d(intent=Intent.UNDO, app=None)
    assert decide(u, T, has_last=False).outcome == Outcome.IGNORE
    assert decide(u, T, has_last=True).outcome == Outcome.EXECUTE


def test_none_ignores() -> None:
    assert decide(d(intent=Intent.NONE, app=None), T).outcome == Outcome.IGNORE


@pytest.mark.parametrize(
    ("combo", "expected"), [("cmd+s", Outcome.EXECUTE), (None, Outcome.IGNORE)]
)
def test_press_key(combo: str | None, expected: Outcome) -> None:
    assert decide(d(intent=Intent.PRESS_KEY, app=None, key_combo=combo), T).outcome == expected


def test_screen_action_gate() -> None:
    d_ok = d(intent=Intent.SCREEN, app=None, intent_confidence=0.7)
    assert decide(d_ok, T).outcome == Outcome.EXECUTE
    d_low = d(intent=Intent.SCREEN, app=None, intent_confidence=0.5)
    assert decide(d_low, T).outcome == Outcome.IGNORE
