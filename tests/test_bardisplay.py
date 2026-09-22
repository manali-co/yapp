from yapp.bar import Bar
from yapp.bardisplay import BarDisplay
from yapp.types import Outcome, Result, Verdict


class FakeWindow:
    def __init__(self) -> None:
        self.js: list[str] = []

    def evaluate_js(self, js: str) -> object:
        self.js.append(js)
        return None

    def show(self) -> None:
        return None

    def hide(self) -> None:
        return None

    def move(self, x: int, y: int) -> None:
        return None


def make() -> tuple[BarDisplay, FakeWindow]:
    w = FakeWindow()
    return BarDisplay(Bar(w)), w


def test_transcript_growth_ticks_commit() -> None:
    bd, w = make()
    bd.show_transcript(["open"], ["notes"])
    bd.show_transcript(["open", "notes"], [])
    bd.show_transcript(["open", "notes"], [])
    assert sum("commit()" in j for j in w.js) == 2


def test_execute_pulses_toward_action_then_result_text() -> None:
    bd, w = make()
    bd.show_verdict(Verdict(Outcome.EXECUTE, "open Notes (0.99 ≥ 0.6)"))
    bd.show_result(Result(True, "opened Notes"))
    assert 'setState("acting"' in w.js[0] and '"direction": 0.0' in w.js[0]
    assert w.js[1] == 'window.yapp.setDecision("Opening Notes", false)'
    assert bd.acted


def test_refuse_is_unsure_with_copy() -> None:
    bd, w = make()
    bd.show_verdict(Verdict(Outcome.REFUSE, "won't do that: could delete, send, or spend"))
    assert 'setState("unsure"' in w.js[0]
    assert "Won" in w.js[1] and "delete" in w.js[1]


def test_wait_returns_to_listening_or_dictating() -> None:
    bd, w = make()
    bd.show_verdict(Verdict(Outcome.WAIT, "x"))
    assert 'setState("listening"' in w.js[-1]
    bd.dictating = True
    bd.show_verdict(Verdict(Outcome.IGNORE, "dictating"))
    assert 'setState("dictating"' in w.js[-1]


def test_same_state_is_not_resent_every_tick() -> None:
    bd, w = make()
    bd.begin()
    n = len(w.js)
    bd.show_verdict(Verdict(Outcome.WAIT, "x"))
    bd.show_verdict(Verdict(Outcome.WAIT, "x"))
    assert len(w.js) == n  # still listening; nothing sent
    bd.thinking()
    assert 'setState("thinking"' in w.js[-1]
    bd.show_verdict(Verdict(Outcome.WAIT, "x"))
    assert 'setState("listening"' in w.js[-1]


def test_level_has_gain() -> None:
    bd, w = make()
    bd.listening(0.02)
    assert "setLevel(0.3" in w.js[-1] or "setLevel(0.4" in w.js[-1]
    bd.listening(0.5)
    assert w.js[-1] == "window.yapp.setLevel(1.0)"


def test_dictation_result_enters_dictating() -> None:
    bd, w = make()
    bd.show_result(Result(True, "dictating"))
    assert bd.dictating and "Typing" in w.js[-1]


def test_end_states() -> None:
    bd, w = make()
    bd.end(acted=True)
    assert 'setState("done"' in w.js[-1]
    bd.end(acted=False)
    assert 'setState("unsure"' in w.js[-2] and "Not sure" in w.js[-1]


def test_error_state() -> None:
    bd, w = make()
    bd.show_error("boom")
    assert 'setState("error"' in w.js[0] and "boom" in w.js[1]
