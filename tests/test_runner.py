from collections.abc import Callable
from pathlib import Path

from yapp.config import Config
from yapp.runner import Runner
from yapp.types import App, Decision, Executed, Intent, Outcome, Result

NOTES = App("notes", "Notes", "Launch Notes")
SAFARI = App("safari", "Safari", "Launch Safari")
APPS = [NOTES, SAFARI]
COMMANDS = {"switch", "open", "stop"}


def mk(
    tail: str,
    intent: Intent,
    conf: float,
    complete: float,
    ends: float,
    app: App | None = None,
    consumed: int = 0,
) -> Decision:
    return Decision(
        tail=tail,
        intent=intent,
        intent_confidence=conf,
        intent_probabilities={},
        app=app,
        app_confidence=0.9 if app else None,
        is_complete=complete,
        ends_dictation=ends,
        consumed_words=consumed,
    )


def canned(tail: str, dictating: bool) -> Decision:
    words = tail.split()
    if words and words[0] in {"and", "then"}:
        words = words[1:]
    ends = 0.95 if dictating and words and words[0] in COMMANDS else 0.05
    if dictating and words[:1] == ["stop"]:
        return mk(tail, Intent.NONE, 0.9, 0.9, ends)
    if words[:1] == ["open"] and len(words) >= 2:
        app = NOTES if words[1] == "notes" else SAFARI
        all_words = tail.split()
        consumed = all_words.index("and", 1) if "and" in all_words[1:] else len(all_words)
        return mk(tail, Intent.OPEN_APP, 0.9, 0.95, ends, app, consumed)
    if words[:2] == ["switch", "to"] and len(words) >= 3:
        return mk(tail, Intent.OPEN_APP, 0.9, 0.95, ends, SAFARI, len(tail.split()))
    if words[:1] == ["type"]:
        return mk(tail, Intent.TYPE_TEXT, 0.9, 0.9, ends, consumed=1)
    if words[:1] == ["undo"]:
        return mk(tail, Intent.UNDO, 0.9, 0.9, ends, consumed=1)
    intent = Intent.OPEN_APP if words[:1] == ["open"] else Intent.NONE
    return mk(tail, intent, 0.5, 0.2, ends)


class FakeExec:
    def __init__(self) -> None:
        self.log: list[str] = []

    def open_app(self, app: App) -> Result:
        self.log.append(f"open:{app.name}")
        return Result(True, "ok")

    def type_text(self, text: str) -> Result:
        self.log.append(f"type:{text}")
        return Result(True, "ok")

    def press_key(self, combo: str) -> Result:
        self.log.append(f"key:{combo}")
        return Result(True, "ok")

    def open_file(self, path: Path) -> Result:
        self.log.append(f"file:{path}")
        return Result(True, "ok")

    def frontmost_app(self) -> str:
        return "Finder"

    def undo(self, last: Executed) -> Result:
        self.log.append("undo")
        return Result(True, "ok")


def make(classify: Callable[[str, bool], Decision]) -> tuple[Runner, FakeExec]:
    ex = FakeExec()
    r = Runner(Config(), None, ex, APPS, classify=lambda tail, ctx: classify(tail, ctx.dictating))
    return r, ex


def feed(r: Runner, sentence: str, per_tick: int = 1) -> None:
    words = sentence.split()
    for i in range(per_tick, len(words) + per_tick, per_tick):
        r.tick(words[:i])
    r.finish()


def test_two_actions_from_one_sentence() -> None:
    r, ex = make(canned)
    feed(r, "open notes and switch to safari")
    assert ex.log == ["open:Notes", "open:Safari"]


def test_fragment_waits_then_fires_once() -> None:
    r, ex = make(canned)
    r.tick(["open"])
    r.tick(["open", "notes"])
    r.tick(["open", "notes"])
    r.finish()
    assert ex.log == ["open:Notes"]


def test_dictation_types_then_switches() -> None:
    r, ex = make(canned)
    feed(r, "type hello there my friend switch to safari")
    typed = " ".join(t[5:] for t in ex.log if t.startswith("type:")).split()
    assert typed == ["hello", "there", "my", "friend"]
    assert ex.log[-1] == "open:Safari"


def test_dictation_flushes_on_release() -> None:
    r, ex = make(canned)
    feed(r, "type hello there")
    typed = " ".join(t[5:] for t in ex.log if t.startswith("type:")).split()
    assert typed == ["hello", "there"]


def test_undo_reverses_last() -> None:
    r, ex = make(canned)
    feed(r, "open notes")
    feed(r, "undo")
    assert ex.log == ["open:Notes", "undo"]


def test_verdict_outcomes_reported() -> None:
    r, _ = make(canned)
    outs = [v.outcome for v in r.tick(["open"])]
    assert outs == [Outcome.WAIT]
