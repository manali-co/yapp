"""One tick of the pipeline. Shared by --once, eval, and the live loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from yapp import intent as intent_mod
from yapp.approval import Reply, classify_reply
from yapp.catalog import installed_apps, search_files
from yapp.config import Config
from yapp.display import Display
from yapp.executor import Executor
from yapp.guard import Guard, Mode, jev_harm
from yapp.intent import QUESTIONS, Context
from yapp.jev import Jev, JevError, JevLike
from yapp.learning import Learning
from yapp.placement import Placement
from yapp.policy import decide
from yapp.stream import Stream
from yapp.types import App, Decision, Executed, Intent, Outcome, Result, Verdict
from yapp.workspace import Workspace

Classifier = Callable[[str, Context], Decision]


class ExecutorLike(Protocol):
    def open_app(self, app: App, *, activate: bool = True) -> Result: ...
    def type_ax(self, app: str, text: str) -> bool: ...
    def type_text(self, text: str) -> Result: ...
    def press_key(self, combo: str) -> Result: ...
    def open_file(self, path: Path) -> Result: ...
    def frontmost_app(self) -> str: ...
    def undo(self, last: Executed) -> Result: ...
    def screen(self, words: str, *, app: str | None = None, parallel: bool = False) -> Result: ...


class LearningLike(Protocol):
    def examples(self) -> dict[str, list[str]]: ...
    def negatives(self) -> dict[str, list[str]]: ...
    def executed(self, d: Decision, at: float) -> None: ...
    def undone(self, at: float) -> None: ...
    def flush(self, now: float) -> None: ...


class Runner:
    def __init__(
        self,
        cfg: Config,
        jev: JevLike | None,
        executor: ExecutorLike,
        apps: list[App],
        *,
        learning: LearningLike | None = None,
        display: Display | None = None,
        classify: Classifier | None = None,
        guard: Guard | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        self.cfg = cfg
        self.jev = jev
        self.guard = guard
        self.workspace = workspace
        self.executor = executor
        self.apps = apps
        self.learning = learning
        self.display = display
        self.stream = Stream(cfg.dictation_lookahead_words)
        self.last: Executed | None = None
        self.done: list[str] = []
        if classify is not None:
            self._classify: Classifier = classify
        elif jev is not None:
            self._classify = lambda tail, ctx: intent_mod.classify(tail, ctx, jev, cfg)
        else:
            raise ValueError("need jev or classify")

    def _ctx(self) -> Context:
        return Context(
            apps=self.apps,
            frontmost_app=self.executor.frontmost_app(),
            already_done=self.done,
            dictating=self.stream.dictating,
            examples=self.learning.examples() if self.learning else {},
            negatives=self.learning.negatives() if self.learning else {},
        )

    def tick(self, committed: list[str], pending: list[str] | None = None) -> list[Verdict]:
        if self.display:
            self.display.show_transcript(committed, pending or [])
        if self.learning:
            self.learning.flush(time.time())
        if not self.stream.set_committed(committed):
            return []
        verdicts: list[Verdict] = []
        for _ in range(4):  # a tick may complete more than one instruction
            tail = self.stream.tail()
            if not tail:
                break
            v = self._step(tail)
            verdicts.append(v)
            if v.outcome != Outcome.EXECUTE:
                break
        if self.stream.dictating:
            self._type(self.stream.dictation_words())
        return verdicts

    def finish(self) -> list[Verdict]:
        """Key released: last chance for the tail, then flush dictation and reset."""
        out: list[Verdict] = []
        tail = self.stream.tail()
        if tail and not self.stream.dictating:
            out.append(self._step(tail))
        if self.stream.dictating:
            self._type(self.stream.dictation_words(flush=True))
            self.stream.exit_dictation()
        self._flush_held()  # words a field refused: one borrow, at the very end
        self.stream.reset()
        if self.workspace is not None:
            self.workspace.reset()  # after the last words are typed where they belong
        return out

    def _step(self, tail: str) -> Verdict:
        if self.display:
            self.display.thinking()
        try:
            d = self._classify(tail, self._ctx())
        except JevError as e:
            if self.display:
                self.display.show_error(str(e))
            return Verdict(Outcome.IGNORE, f"jev error: {e}")
        if self.display:
            self.display.show_decision(d)
        v = decide(
            d, self.cfg.thresholds, dictating=self.stream.dictating, has_last=self.last is not None
        )
        if v.outcome == Outcome.EXECUTE and self.stream.already_fired(d.consumed_words):
            v = Verdict(Outcome.IGNORE, "already acted on this")
        if self.display:
            self.display.show_verdict(v)
        if v.outcome == Outcome.EXECUTE:
            self._execute(d)
        return v

    def _may(self, action: str) -> bool:
        return self.guard is None or self.guard.check(action, self.executor.frontmost_app()).allowed

    def _execute(self, d: Decision) -> None:
        if self.stream.dictating:
            # The tail is the new instruction; held-back words belong to it, not the document.
            self.stream.exit_dictation()
        self.stream.mark_fired(d.consumed_words)
        r: Result
        denied = Result(False, "not approved")
        match d.intent:
            case Intent.OPEN_APP if d.app is not None:
                r = self._open(d.tail, d.app) if self._may(f"open {d.app.name}") else denied
                if r.ok:
                    self.last = Executed(d, r)
            case Intent.TYPE_TEXT:
                self.stream.consume(d.consumed_words)
                ws = self.workspace
                where = (
                    ws.work_app
                    if ws and ws.parallel and ws.work_app
                    else self.executor.frontmost_app()
                )
                if not self._may(f"dictate into {where}"):
                    self._report(denied)
                    return
                self.stream.enter_dictation()
                r = Result(True, "dictating")
                self.last = Executed(d, r, typed_chars=0)
                self._report(r)
                return
            case Intent.OPEN_FILE if d.file_query:
                hits = search_files(d.file_query)
                if not hits:
                    r = Result(False, "no file found")
                elif self._may(f"open file {hits[0].name}"):
                    r = self.executor.open_file(hits[0])
                else:
                    r = denied
                if r.ok:
                    self.last = Executed(d, r)
            case Intent.PRESS_KEY if d.key_combo:
                where = self.executor.frontmost_app()
                r = (
                    self.executor.press_key(d.key_combo)
                    if self._may(f"press {d.key_combo} in {where}")
                    else denied
                )
                if r.ok:
                    self.last = Executed(d, r)
            case Intent.SCREEN:
                r = self._screen(" ".join(d.tail.split()[: d.consumed_words]))
                if r.ok:
                    ws = self.workspace
                    side = ws.work_app if ws is not None and ws.parallel else ""
                    self.last = Executed(d, r, app=side)
            case Intent.CLEANUP:
                r = self._cleanup()
            case Intent.UNDO if self.last is not None:
                last = self.last
                ws = self.workspace
                if last.app and ws is not None:
                    # The keystrokes of undo must reach the app that was acted on, not the
                    # app the user is working in.
                    out = ws.borrow_focus(last.app, lambda: self.executor.undo(last))
                    r = out if isinstance(out, Result) else Result(False, "undo failed")
                else:
                    r = self.executor.undo(last)
                if self.learning:
                    self.learning.undone(time.time())
                self.last = None
            case _:
                r = Result(False, "nothing to execute")
        self.stream.consume(d.consumed_words)
        self.done.append(" ".join(d.tail.split()[: d.consumed_words]))
        if self.learning and d.intent != Intent.UNDO and r.ok:
            self.learning.executed(d, time.time())
        self._report(r)

    def _open(self, tail: str, app: App) -> Result:
        ws = self.workspace
        if ws is None:
            return self.executor.open_app(app)
        ws.decide(tail, app.name)
        activate = ws.before_open(app.name)
        r = self.executor.open_app(app, activate=activate)
        if r.ok:
            ws.after_open(app.name)
        return r

    def _screen(self, words: str) -> Result:
        ws = self.workspace
        if ws is None:
            return self.executor.screen(words)
        ws.decide(words)
        app = ws.work_app if ws.parallel else ws.frontmost()
        before = ws.snapshot_windows(app)
        r = self.executor.screen(words, app=app if ws.parallel else None, parallel=ws.parallel)
        ws.note_new_windows(app, before)
        return r

    def _cleanup(self) -> Result:
        ws = self.workspace
        if ws is None:
            return Result(False, "nothing to clean up")
        if ws.ledger.empty:
            return Result(True, "nothing to clean up")
        if not self._may("close the windows and apps Yapp opened"):
            return Result(False, "not approved")
        done = ws.cleanup()
        return Result(True, "cleaned up: " + ", ".join(done) if done else "nothing to clean up")

    def _type(self, words: list[str]) -> None:
        if not words:
            return
        text = " ".join(words) + " "
        ws = self.workspace
        app = ""
        if ws is not None and ws.parallel and ws.work_app:
            app = ws.work_app
            if ws.type_on_side(text, self.executor.type_ax):
                r = Result(True, f"typed {len(text)} chars on the side")
            else:
                r = Result(True, f"holding {len(ws.held_text)} chars for one borrow")
        else:
            r = self.executor.type_text(text)
        last = self.last
        if last is not None and last.decision.intent == Intent.TYPE_TEXT:
            self.last = Executed(
                last.decision, r, typed_chars=last.typed_chars + len(text), app=app
            )
        self._report(r)

    def _flush_held(self) -> None:
        ws = self.workspace
        if ws is None or not ws.held_text:
            return
        out = ws.flush_held(self.executor.type_text)
        if isinstance(out, Result):
            self._report(out)

    def _report(self, r: Result) -> None:
        if self.display:
            self.display.show_result(r)


def build_approver(runner: Runner) -> Callable[[str, str], Reply]:
    """Spoken reply -> approve / deny / unrelated, using the runner's Jev client."""
    jev = runner.jev
    assert jev is not None
    criteria = QUESTIONS["reply"]["criteria"]
    return lambda reply, action: classify_reply(reply, action, jev, criteria)


def build_guard(
    jev: JevLike, ask: Callable[[str], bool], mode: Mode, log: Callable[[str], None]
) -> Guard:
    q = QUESTIONS["is_harmful"]
    return Guard(jev_harm(jev, q["criteria"], q["instructions"]), ask, mode=mode, log=log)


def build_workspace(
    jev: JevLike,
    log: Callable[[str], None],
    *,
    force_placement: str | None = None,
    attention: Callable[[str], None] = lambda s: None,
    attention_done: Callable[[], None] = lambda: None,
    may: Callable[[str], bool] = lambda action: False,
) -> Workspace:
    from yapp import windows as win
    from yapp.ax import frontmost_app_name
    from yapp.native import app_is_running, bring_to_front, quit_app
    from yapp.placement import decide_placement, seconds_since_input

    def decide(instruction: str, front: str, target: str) -> Placement:
        return decide_placement(
            jev,
            instruction,
            front_app=front,
            target_app=target,
            idle_seconds=seconds_since_input(),
            display_count=len(win.displays()),
        )

    return Workspace(
        decide,
        win.WindowManager(log=log),
        frontmost=frontmost_app_name,
        raise_app=bring_to_front,
        is_running=app_is_running,
        quit_app=quit_app,
        close_window=win.close_window,
        windows_of=win.app_windows,
        window_title=win.window_title,
        attention=attention,
        attention_done=attention_done,
        force=force_placement,
        log=log,
        may=may,
        sheet_buttons=win.sheet_buttons,
        press=win.press,
    )


def build_runner(
    cfg: Config,
    display: Display | None,
    *,
    ask: Callable[[str], bool] = lambda action: False,
    mode: Mode = Mode.ASK,
    jev: JevLike | None = None,
    force_placement: str | None = None,
    attention: Callable[[str], None] = lambda s: None,
    attention_done: Callable[[], None] = lambda: None,
) -> Runner:
    """The live pipeline. `ask` is how a harmful action gets its yes (voice in the bar)."""
    from yapp.ax import Screen, ax_type

    jev = jev or Jev(model=cfg.model)
    apps = installed_apps()
    log = display.status if display else (lambda s: None)
    if display:
        display.status(f"{len(apps)} apps in catalog · model {cfg.model} · mode {mode}")
    from yapp.native import bring_to_front, leave_full_screen_if_needed

    executor = Executor(leave_full_screen=leave_full_screen_if_needed, raise_app=bring_to_front)
    guard = build_guard(jev, ask, mode, log)
    workspace = build_workspace(
        jev,
        log,
        force_placement=force_placement,
        attention=attention,
        attention_done=attention_done,
        may=lambda action: guard.check(action, "").allowed,
    )
    screen = Screen(
        jev,
        type_text=executor.type_text,
        press_key=executor.press_key,
        threshold=cfg.thresholds.screen,
        log=log,
        guard=lambda action, ctx: guard.check(action, ctx).allowed,
        ax_type=lambda t, text: ax_type(t, text, append=t.role == "AXTextArea"),
        borrow=workspace.borrow_focus,
    )
    executor.screen_fn = screen.run
    return Runner(
        cfg,
        jev,
        executor,
        apps,
        learning=Learning(cfg),
        display=display,
        guard=guard,
        workspace=workspace,
    )
