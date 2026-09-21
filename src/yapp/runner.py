"""One tick of the pipeline. Shared by --once, eval, and the live loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from yapp import intent as intent_mod
from yapp.catalog import installed_apps, search_files
from yapp.config import Config
from yapp.display import Display
from yapp.executor import Executor
from yapp.intent import Context
from yapp.jev import Jev, JevError
from yapp.learning import Learning
from yapp.policy import decide
from yapp.stream import Stream
from yapp.types import App, Decision, Executed, Intent, Outcome, Result, Verdict

Classifier = Callable[[str, Context], Decision]


class ExecutorLike(Protocol):
    def open_app(self, app: App) -> Result: ...
    def type_text(self, text: str) -> Result: ...
    def press_key(self, combo: str) -> Result: ...
    def open_file(self, path: Path) -> Result: ...
    def frontmost_app(self) -> str: ...
    def undo(self, last: Executed) -> Result: ...


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
        jev: Jev | None,
        executor: ExecutorLike,
        apps: list[App],
        *,
        learning: LearningLike | None = None,
        display: Display | None = None,
        classify: Classifier | None = None,
    ) -> None:
        self.cfg = cfg
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
        self.stream.reset()
        return out

    def _step(self, tail: str) -> Verdict:
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

    def _execute(self, d: Decision) -> None:
        if self.stream.dictating:
            # The tail is the new instruction; held-back words belong to it, not the document.
            self.stream.exit_dictation()
        self.stream.mark_fired(d.consumed_words)
        r: Result
        match d.intent:
            case Intent.OPEN_APP if d.app is not None:
                r = self.executor.open_app(d.app)
                self.last = Executed(d, r)
            case Intent.TYPE_TEXT:
                self.stream.consume(d.consumed_words)
                self.stream.enter_dictation()
                r = Result(True, "dictating")
                self.last = Executed(d, r, typed_chars=0)
                self._report(r)
                return
            case Intent.OPEN_FILE if d.file_query:
                hits = search_files(d.file_query)
                r = self.executor.open_file(hits[0]) if hits else Result(False, "no file found")
                if r.ok:
                    self.last = Executed(d, r)
            case Intent.PRESS_KEY if d.key_combo:
                r = self.executor.press_key(d.key_combo)
                self.last = Executed(d, r)
            case Intent.UNDO if self.last is not None:
                r = self.executor.undo(self.last)
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

    def _type(self, words: list[str]) -> None:
        if not words:
            return
        text = " ".join(words) + " "
        r = self.executor.type_text(text)
        last = self.last
        if last is not None and last.decision.intent == Intent.TYPE_TEXT:
            self.last = Executed(last.decision, r, typed_chars=last.typed_chars + len(text))
        self._report(r)

    def _report(self, r: Result) -> None:
        if self.display:
            self.display.show_result(r)


def build_runner(cfg: Config, display: Display | None) -> Runner:
    jev = Jev(model=cfg.model)
    apps = installed_apps()
    if display:
        display.status(f"{len(apps)} apps in catalog · model {cfg.model}")
    return Runner(cfg, jev, Executor(), apps, learning=Learning(cfg), display=display)
