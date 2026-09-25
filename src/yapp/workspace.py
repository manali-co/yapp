"""Session-level state for how Yapp works next to the user: placement, windows, ledger.

One Workspace lives for one bar session. The runner asks it where to work before the first
action; the executor and the screen loop ask it how to act (activate, or stay on the side).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yapp.ledger import Ledger
from yapp.placement import HAND_OVER, PARALLEL, Placement
from yapp.windows import WindowManager

Decider = Callable[[str, str, str], Placement]  # (instruction, front app, target app)


@dataclass(frozen=True)
class Held:
    app: str
    text: str
    action: int  # the dictation action these words belong to (for undo)


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
        may: Callable[[str], bool] = lambda action: False,
        sheet_buttons: Callable[[Any], list[tuple[str, Any]]] = lambda win: [],
        press: Callable[[Any], bool] = lambda el: False,
        highlight: Any = None,
        focused: Callable[[str], Any] = lambda app: None,
        real_click: Callable[[float, float], bool] = lambda x, y: False,
        typing_now: Callable[[], bool] = lambda: False,
    ) -> None:
        self.typing_now = typing_now  # a hard rule above Jev: never raise while keys are down
        self.may = may  # the guard: (action) -> allowed?
        self.sheet_buttons = sheet_buttons
        self.press = press
        self.highlight = highlight  # the glow around the window Yapp works in (highlight.py)
        self.focused = focused
        self.real_click = real_click
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
        self.user_window: Any = None  # the window the user had when they spoke: never glowed
        self.work_app: str = ""
        # Dictation a field refused, in order, tagged with its app and dictation action.
        self.held: list[Held] = []

    # ---- placement -------------------------------------------------------------------
    @property
    def parallel(self) -> bool:
        return self.mode == PARALLEL

    def decide(self, instruction: str, target_app: str = "") -> str:
        """Decided once per session, at the first action; reused after that."""
        if self.mode is not None:
            return self.mode
        self.user_app = self.frontmost()
        self.user_window = self.focused(self.user_app) if self.user_app else None
        if self.force in (HAND_OVER, PARALLEL):
            self.mode = self.force
        elif self.typing_now():
            self.mode = PARALLEL
            self.log("placement: parallel (the user is typing right now)")
        else:
            p = self._decide(instruction, self.user_app, target_app)
            self.mode = p.mode
            self.log(f"placement: {p.mode} ({p.confidence:.2f}, {p.latency_ms} ms)")
        if self.mode == PARALLEL:
            self.windows.begin_parallel(self.user_app)
        return self.mode

    def reset(self) -> None:
        """Session over: forget the placement; the ledger survives until clean-up. Windows
        Yapp opened keep their glow until clean-up (they are still Yapp's); a glow on a
        window that was already the user's fades now."""
        self.mode = None
        if self.ledger.empty:
            self.glow_done()

    # ---- opening apps ----------------------------------------------------------------
    def before_open(self, app: str) -> bool:
        """Returns whether the app should be activated (hand over) or left behind (parallel).
        Even in hand-over mode a window is never raised while the user is typing."""
        self.ledger.note_launch(app, self.is_running(app))
        if not self.parallel and self.typing_now():
            self.log(f"windows: not raising {app}; the user is typing")
            return False
        return not self.parallel

    def after_open(self, app: str) -> None:
        self.work_app = app
        self.glow(app)
        if self.parallel:
            self.sleep(0.6)  # let the window appear before placing it
            if app in self.ledger.launched_apps:
                # A fresh launch: its first window is Yapp's. An app that was already running
                # shows the user's own document; only windows Yapp creates get placed (see
                # note_new_windows), so nothing of the user's is moved without a record.
                if self.windows.place(app):
                    self.log(f"windows: {app} placed in the work area")
            if self.user_app and self.user_app != app:
                self.raise_app(self.user_app)  # the user keeps the keyboard

    # ---- the glow ----------------------------------------------------------------------
    def glow(self, app: str, window: Any = None) -> None:
        """Show the acting glow, but only on a window Yapp itself opened (an app it launched,
        or a window it created). A window that was already the user's is never marked, even
        while Yapp acts in it: the glow answers "which windows are Yapp's?", nothing else."""
        if self.highlight is None:
            return
        win = window if window is not None else self.focused(app)
        if win is None:  # a background app may report no focused window: take its first
            wins = self.windows_of(app)
            win = wins[0] if wins else None
        if win is None:
            return
        launched = app in self.ledger.launched_apps
        created = any(w.ref == win for w in self.ledger.windows)
        if not (launched or created):
            return
        if not self.highlight.show(win):
            self.log(f"glow: no frame for the {app} window")

    def track_glow(self) -> None:
        """Re-read the glowed window's frame now (the app's timer does this too; a process
        without a run loop, like the benchmark, relies on this call)."""
        if self.highlight is not None:
            self.highlight.track()

    def glow_done(self) -> None:
        if self.highlight is not None:
            self.highlight.done()

    # ---- typing while the user works -----------------------------------------------
    def borrow_pointer(self, x: float, y: float) -> bool:
        """Tier 3 pointer: the real cursor, for a moment, under the attention state."""
        self.attention("Borrowing your mouse for a moment")
        try:
            ok = self.real_click(x, y)
            if not ok:
                self.log("pointer: the user is holding a button; not touching the cursor")
            return ok
        finally:
            self.attention_done()

    def borrow_focus(self, app: str, act: Callable[[], Any]) -> Any:
        """Run `act` (keystrokes) with `app` in front, then give the user's app back.
        If the app cannot be brought to the front, nothing is typed: keystrokes would land
        in whatever the user is looking at."""
        from yapp.types import Result

        self.attention("Borrowing your keyboard for a moment")
        started = time.perf_counter()
        back = self.frontmost() or self.user_app  # whatever the user is in right now
        try:
            for _ in range(20):  # wait for a pause in the user's typing, up to ~3 s
                if not self.typing_now():
                    break
                self.sleep(0.15)
            else:
                self.log("borrow: the user kept typing; not taking the keyboard")
                return Result(False, "you were typing; nothing sent")
            if not self.raise_app(app):
                self.log(f"borrow: could not bring {app} to the front; nothing typed")
                return Result(False, f"couldn't bring {app} to the front")
            return act()
        finally:
            if back and back != app:
                self.raise_app(back)
            self.attention_done()
            self.log(f"borrowed focus for {(time.perf_counter() - started) * 1000:.0f} ms")

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
            self.glow(app, self.ledger.windows[-1].ref)

    def type_on_side(self, text: str, type_ax: Callable[[str, str], bool], action: int = 0) -> bool:
        """Dictation in parallel mode: append through Accessibility. When the field refuses,
        the words are held (per dictation action, in order) and typed later with one borrow
        per app. Once anything is held for an app, later words for that app queue behind it
        so nothing arrives out of order."""
        app = self.work_app
        if not app:
            return False
        if not any(h.app == app for h in self.held) and type_ax(app, text):
            return True
        if self.held and self.held[-1].app == app and self.held[-1].action == action:
            self.held[-1] = Held(app, self.held[-1].text + text, action)
        else:
            self.held.append(Held(app, text, action))
        return False

    @property
    def held_text(self) -> str:
        return "".join(h.text for h in self.held)

    def flush_held(self, keystrokes: Callable[[str], Any]) -> tuple[list[Held], Any]:
        """Type held words oldest first, one borrow per entry. Returns what landed and the
        last result; a failed borrow keeps its entry (and everything after it) held."""
        from yapp.types import Result

        flushed: list[Held] = []
        last: Any = None
        while self.held:
            entry = self.held[0]

            def type_it(text: str = entry.text) -> Any:
                return keystrokes(text)

            out = self.borrow_focus(entry.app, type_it)
            if isinstance(out, Result) and not out.ok:
                return flushed, out
            flushed.append(self.held.pop(0))
            last = out
        return flushed, last

    def drop_held(self, action: int) -> int:
        """Forget one dictation action's held words — its undo, before they ever landed."""
        n = sum(len(h.text) for h in self.held if h.action == action)
        self.held = [h for h in self.held if h.action != action]
        return n

    # ---- clean-up --------------------------------------------------------------------
    def _discard(self, w: Any) -> str | None:
        """A closed window may ask 'save?'. Discarding is the guard's call, never ours."""
        from yapp.windows import discard_button

        self.sleep(0.5)
        found = discard_button(self.sheet_buttons(w.ref))
        if found is None:
            return None
        title, el = found
        if not self.may(f"press {title} in {w.app} for the untitled document Yapp created"):
            return f"left {w.app} asking about '{w.title}'"
        return f"pressed {title} in {w.app}" if self.press(el) else None

    def cleanup(self) -> list[str]:
        done = self.ledger.cleanup(
            close=self.close_window,
            quit_app=self.quit_app,
            restore=self.windows.restore,
            discard=self._discard,
            log=self.log,
        )
        self.mode = None
        self.work_app = ""
        if self.highlight is not None:
            self.highlight.hide()
        return done
