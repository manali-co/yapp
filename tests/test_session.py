from pathlib import Path

import numpy as np

from tests.test_runner import APPS, FakeExec, canned
from yapp.bar import Bar
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.runner import Runner
from yapp.session import Session
from yapp.stt import Transcript


class FakeWindow:
    def __init__(self) -> None:
        self.js: list[str] = []
        self.shown: list[bool] = []

    def evaluate_js(self, js: str) -> object:
        self.js.append(js)
        return None

    def show(self) -> None:
        self.shown.append(True)

    def hide(self) -> None:
        self.shown.append(False)

    def move(self, x: int, y: int) -> None:
        return None


class FakeRec:
    def __init__(self) -> None:
        self.armed = False

    def arm(self) -> None:
        self.armed = True

    def disarm(self) -> None:
        self.armed = False

    def snapshot(self) -> np.ndarray:
        return np.zeros(16000, dtype=np.float32)

    def level(self) -> float:
        return 0.3


class ScriptedStt:
    def __init__(self, sentence: str) -> None:
        self.words = sentence.split()
        self.i = 0

    def reset(self) -> None:
        self.i = 0

    def update(self, samples: np.ndarray) -> Transcript:
        self.i = min(len(self.words), self.i + 1)
        return Transcript(self.words[: self.i], self.words[self.i : self.i + 1])


def make(sentence: str, cfg: Config | None = None) -> tuple[Session, FakeExec, FakeWindow]:
    cfg = cfg or Config(silence_seconds=2.0, tick_seconds=0.4, hide_after_seconds=0)
    ex = FakeExec()
    runner = Runner(cfg, None, ex, APPS, classify=lambda tail, ctx: canned(tail, ctx.dictating))
    w = FakeWindow()
    bar = Bar(w)
    bd = BarDisplay(bar)
    runner.display = bd
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(s: float) -> None:
        now[0] += s

    session = Session(
        cfg,
        runner,
        FakeRec(),
        ScriptedStt(sentence),
        bar,
        bd,
        screen=lambda: (1440, 900, 0, 0),
        clock=clock,
        sleep=sleep,
    )
    return session, ex, w


def test_session_acts_then_hides_on_silence() -> None:
    s, ex, w = make("open notes and switch to safari")
    acted = s.run_one()
    assert acted and ex.log == ["open:Notes", "open:Safari"]
    assert w.shown == [True, False]
    assert any('setState("done"' in j for j in w.js)


def test_nothing_said_ends_unsure_after_max_session() -> None:
    cfg = Config(
        silence_seconds=2.0, tick_seconds=0.4, hide_after_seconds=0, max_session_seconds=3.0
    )
    s, ex, w = make("", cfg)
    acted = s.run_one()
    assert not acted and ex.log == []
    assert any("Not sure" in j for j in w.js)
    assert w.shown == [True, False]


def test_toggle_stops_running_session() -> None:
    s, ex, w = make("open notes and switch to safari and open slack")
    original = s.runner.tick

    def tick_then_toggle(committed: list[str], pending: list[str] | None = None) -> list:  # type: ignore[type-arg]
        out = original(committed, pending)
        if committed == ["open", "notes"]:
            s.toggle()
        return out

    s.runner.tick = tick_then_toggle  # type: ignore[method-assign]
    s.run_one()
    assert ex.log == ["open:Notes"]


def test_toggle_when_idle_requests_a_session() -> None:
    s, _, _ = make("open notes")
    assert not s.wanted()
    s.toggle()
    assert s.wanted()


def test_escape_only_acts_while_running() -> None:
    s, _, _ = make("open notes")
    s.escape()
    assert not s.wanted() and not s.stop_requested


def test_countdown_is_sent_after_first_word() -> None:
    s, _, w = make("open notes")
    s.run_one()
    args = [j.rsplit("(", 1)[1].rstrip(")") for j in w.js if "setCountdown" in j]
    values = [float(a.split(",")[0]) for a in args if a != "null"]
    assert values and values[0] <= 2.0 and values[-1] <= 0.5  # counts down to the close
    assert values == sorted(values, reverse=True)  # monotonic once the last word landed


def test_session_counts_and_hints_first_runs(tmp_path: Path) -> None:
    from yapp.state import AppState

    s, _, w = make("open notes")
    s.state = AppState(tmp_path / "state.json")
    s.run_one()
    assert s.state.sessions == 1
    assert any(j.endswith("setHint(0)") for j in w.js)
    for _ in range(5):
        s.stt.reset()
        s.run_one()
    assert s.state.sessions == 6
    assert w.js[-1] != "" and not any(j.endswith("setHint(1)") for j in w.js[-40:])
