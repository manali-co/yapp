"""Session-level state for how Yapp works next to the user: placement, windows, ledger.

One Workspace lives for one bar session. The runner asks it where to work before the first
action; the executor and the screen loop ask it how to act (activate, or stay on the side).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from yapp.ledger import Ledger
from yapp.placement import HAND_OVER, PARALLEL, Placement
from yapp.windows import WindowManager

Decider = Callable[[str, str, str], Placement]  # (instruction, front app, target app)


class Workspace:
    def __init__(
        self,
        decide: Decider,
        windows: WindowManager,
        *,
        frontmost: Callable[[], str],
        raise_app: Callable[[str], bool],
        is_running: Callable[[str], bool],
        quit_app: Callable[[str], bool],
        close_window: Callable[[Any], bool],
        windows_of: Callable[[str], list[Any]],
        window_title: Callable[[Any], str],
        attention: Callable[[str], None] = lambda s: None,
        attention_done: Callable[[], None] = lambda: None,
        force: str | None = None,
        log: Callable[[str], None] = lambda s: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._decide = decide
        self.windows = windows
        self.frontmost = frontmost
        self.raise_app = raise_app
        self.is_running = is_running
        self.quit_app = quit_app
        self.close_window = close_window
        self.windows_of = windows_of
        self.window_title = window_title
        self.attention = attention
        self.attention_done = attention_done
        self.force = force
        self.log = log
        self.sleep = sleep
        self.ledger = Ledger()
        self.mode: str | None = None
        self.user_app: str = ""
        self.work_app: str = ""

    # ---- placement -------------------------------------------------------------------
    @property
    def parallel(self) -> bool:
        return self.mode == PARALLEL

    def decide(self, instruction: str, target_app: str = "") -> str:
        """Decided once per session, at the first action; reused after that."""
        if self.mode is not None:
            return self.mode
        self.user_app = self.frontmost()
        if self.force in (HAND_OVER, PARALLEL):
            self.mode = self.force
        else:
            p = self._decide(instruction, self.user_app, target_app)
            self.mode = p.mode
            self.log(f"placement: {p.mode} ({p.confidence:.2f}, {p.latency_ms} ms)")
        if self.mode == PARALLEL:
            self.windows.begin_parallel(self.user_app)
        return self.mode

    def reset(self) -> None:
        """Session over: forget the placement; the ledger survives until clean-up."""
        self.mode = None

    # ---- opening apps ----------------------------------------------------------------
    def before_open(self, app: str) -> bool:
        """Returns whether the app should be activated (hand over) or left behind (parallel)."""
        self.ledger.note_launch(app, self.is_running(app))
        return not self.parallel

    def after_open(self, app: str) -> None:
        self.work_app = app
        if self.parallel:
            self.sleep(0.6)  # let the window appear before placing it
            if self.windows.place(app):
                self.log(f"windows: {app} placed in the work area")
            if self.user_app and self.user_app != app:
                self.raise_app(self.user_app)  # the user keeps the keyboard

    # ---- typing while the user works -----------------------------------------------
    def borrow_focus(self, app: str, act: Callable[[], Any]) -> Any:
        """Run `act` (keystrokes) with `app` in front, then give the user's app back."""
        self.attention("Borrowing your keyboard for a moment")
        started = time.perf_counter()
        try:
            self.raise_app(app)
            return act()
        finally:
            if self.user_app and self.user_app != app:
                self.raise_app(self.user_app)
            self.attention_done()
            self.log(f"borrowed focus for {(time.perf_counter() - started) * 1000:.0f} ms")

    # ---- clean-up --------------------------------------------------------------------
    def snapshot_windows(self, app: str) -> list[Any]:
        return self.windows_of(app) if app else []

    def note_new_windows(self, app: str, before: list[Any]) -> None:
        if not app:
            return
        already = len(self.ledger.windows)
        n = self.ledger.note_windows(app, before, self.windows_of(app), self.window_title)
        if n:
            self.log(f"ledger: {n} new {app} window(s)")
            if self.parallel:
                for w in self.ledger.windows[already:]:
                    if self.windows.place_window(w.ref):
                        self.log(f"windows: new {app} window placed in the work area")
                if self.user_app and self.user_app != app:
                    self.raise_app(self.user_app)

    def type_on_side(
        self, text: str, type_ax: Callable[[str, str], bool], keystrokes: Callable[[], Any]
    ) -> Any:
        """Dictation in parallel mode: append through Accessibility, else borrow focus once."""
        if self.work_app and type_ax(self.work_app, text):
            return None
        return self.borrow_focus(self.work_app, keystrokes)

    def cleanup(self) -> list[str]:
        done = self.ledger.cleanup(
            close=self.close_window,
            quit_app=self.quit_app,
            restore=self.windows.restore,
            log=self.log,
        )
        self.mode = None
        self.work_app = ""
        return done
