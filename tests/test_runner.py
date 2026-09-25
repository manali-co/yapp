from collections.abc import Callable
from pathlib import Path

from yapp.config import Config
from yapp.guard import Guard
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
        return mk(tail, Intent.TYPE_TEXT, 0.9, 0.9, ends, consumed=tail.split().index("type") + 1)
    if words[:1] == ["undo"]:
        return mk(tail, Intent.UNDO, 0.9, 0.9, ends, consumed=1)
    if words[:2] == ["clean", "up"]:
        return mk(tail, Intent.CLEANUP, 0.9, 0.9, ends, consumed=len(tail.split()))
    if words[:2] == ["zoom", "in"]:
        return mk(tail, Intent.SCREEN, 0.9, 0.9, ends, consumed=len(tail.split()))
    intent = Intent.OPEN_APP if words[:1] == ["open"] else Intent.NONE
    return mk(tail, intent, 0.5, 0.2, ends)


class FakeExec:
    def __init__(self) -> None:
        self.log: list[str] = []

    def open_app(self, app: App, *, activate: bool = True) -> Result:
        self.log.append(f"open:{app.name}" + ("" if activate else ":side"))
        return Result(True, "ok")

    def type_text(self, text: str) -> Result:
        self.log.append(f"type:{text}")
        return Result(True, "ok")

    def type_ax(self, app: str, text: str) -> bool:
        self.log.append(f"ax:{app}:{text}")
        return getattr(self, "ax_ok", True)

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

    def screen(self, words: str, *, app: str | None = None, parallel: bool = False) -> Result:
        self.log.append(
            f"screen:{words}" + (f"@{app}" if app else "") + (":parallel" if parallel else "")
        )
        return Result(True, f"pressed menu: View › {words}")


def make(
    classify: Callable[[str, bool], Decision], guard: Guard | None = None
) -> tuple[Runner, FakeExec]:
    ex = FakeExec()
    r = Runner(
        Config(),
        None,
        ex,
        APPS,
        classify=lambda tail, ctx: classify(tail, ctx.dictating),
        guard=guard,
    )
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


class SpyDisplay:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def status(self, msg: str) -> None:
        self.calls.append("status")

    def listening(self, level: float) -> None:
        self.calls.append("listening")

    def thinking(self) -> None:
        self.calls.append("thinking")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        self.calls.append("transcript")

    def show_decision(self, d: Decision) -> None:
        self.calls.append("decision")

    def show_verdict(self, v: object) -> None:
        self.calls.append("verdict")

    def show_result(self, r: Result) -> None:
        self.calls.append("result")

    def show_error(self, msg: str) -> None:
        self.calls.append("error")


def test_runner_calls_thinking_before_decision() -> None:
    ex = FakeExec()
    spy = SpyDisplay()
    r = Runner(
        Config(),
        None,
        ex,
        APPS,
        display=spy,
        classify=lambda tail, ctx: canned(tail, ctx.dictating),
    )
    r.tick(["open", "notes"])
    assert spy.calls[:4] == ["transcript", "thinking", "decision", "verdict"]


def test_failed_open_is_not_remembered_for_undo() -> None:
    class Failing(FakeExec):
        def open_app(self, app: App, *, activate: bool = True) -> Result:
            return Result(False, "no such app")

    ex = Failing()
    r = Runner(Config(), None, ex, APPS, classify=lambda tail, ctx: canned(tail, ctx.dictating))
    feed(r, "open notes")
    assert r.last is None


def test_screen_action_is_delegated_and_undoable() -> None:
    r, ex = make(canned)
    feed(r, "zoom in")
    assert ex.log == ["screen:zoom in"]
    assert r.last is not None and r.last.decision.intent == Intent.SCREEN
    feed(r, "undo")
    assert ex.log[-1] == "undo"


def test_guard_asks_before_direct_actions_and_denial_blocks_them() -> None:
    asked: list[str] = []

    def harm(action: str, context: str) -> tuple[float, int]:
        return (0.9 if "safari" in action.lower() else 0.0), 1

    def ask(action: str) -> bool:
        asked.append(action)
        return False

    r, ex = make(canned, Guard(harm, ask))
    feed(r, "open notes and open safari")
    assert ex.log == ["open:Notes"]  # Safari was judged harmful, asked, denied
    assert asked == ["open Safari"] and r.last is not None and r.last.decision.app is NOTES


def test_guard_gates_dictation_entry_with_the_frontmost_app() -> None:
    seen: list[str] = []

    def harm(action: str, context: str) -> tuple[float, int]:
        seen.append(f"{action} @ {context}")
        return 0.5, 1

    r, ex = make(canned, Guard(harm, lambda a: True))
    feed(r, "type hello there")
    assert seen == ["dictate into Finder @ Finder"]
    assert ex.log == ["type:hello there "]


def test_parallel_workspace_opens_on_the_side_and_targets_the_work_app() -> None:
    from tests.test_workspace import World
    from tests.test_workspace import make as make_ws

    world = World()
    ws = make_ws(world)  # Jev says parallel; Slack is in front
    ex = FakeExec()
    r = Runner(
        Config(),
        None,
        ex,
        APPS,
        classify=lambda tail, ctx: canned(tail, ctx.dictating),
        workspace=ws,
    )
    feed(r, "open notes and zoom in")
    assert ex.log == ["open:Notes:side", "screen:and zoom in@Notes:parallel"]
    assert world.front == "Slack" and ws.ledger.launched_apps == []  # Notes was already running
    r.finish()
    assert ws.mode is None  # decided again next session


def test_cleanup_intent_unwinds_the_ledger_through_the_guard() -> None:
    from tests.test_workspace import World
    from tests.test_workspace import make as make_ws

    world = World()
    ws = make_ws(world)
    seen: list[str] = []

    def harm(action: str, context: str) -> tuple[float, int]:
        seen.append(action)
        return 0.1, 1

    r, ex = make(canned, Guard(harm, lambda a: False))
    r.workspace = ws
    feed(r, "open safari")  # Safari is not running in the World: it gets launched
    assert ws.ledger.launched_apps == ["Safari"] and ex.log == ["open:Safari:side"]
    feed(r, "clean up")
    assert seen[-1] == "close the windows and apps Yapp opened"
    assert world.quit == ["Safari"] and ws.ledger.empty
    feed(r, "clean up")  # nothing left: no ask, no error
    assert len(seen) == 2  # an empty ledger never reaches the guard


def test_parallel_dictation_goes_through_accessibility_then_borrows_focus() -> None:
    from tests.test_workspace import World
    from tests.test_workspace import make as make_ws

    world = World()
    ws = make_ws(world)
    ex = FakeExec()
    r = Runner(
        Config(),
        None,
        ex,
        APPS,
        classify=lambda tail, ctx: canned(tail, ctx.dictating),
        workspace=ws,
    )
    feed(r, "open notes and type hello there")
    assert ex.log == ["open:Notes:side", "ax:Notes:hello there "] and world.front == "Slack"
    ex2 = FakeExec()
    ex2.ax_ok = False  # type: ignore[attr-defined]
    world2 = World()
    ws2 = make_ws(world2)
    r2 = Runner(
        Config(),
        None,
        ex2,
        APPS,
        classify=lambda tail, ctx: canned(tail, ctx.dictating),
        workspace=ws2,
    )
    feed(r2, "open notes and type hello there")
    assert ex2.log == ["open:Notes:side", "ax:Notes:hello there ", "type:hello there "]
    assert world2.raised[-2:] == ["Notes", "Slack"] and any(
        "attention" in line for line in world2.log
    )
