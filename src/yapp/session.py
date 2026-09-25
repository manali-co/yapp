"""One Spotlight-style session.

Show the bar, listen hands-free, act, hide on hotkey, Escape, or silence.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from yapp.approval import Reply
from yapp.bar import Bar
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.runner import Runner
from yapp.state import AppState
from yapp.stt import Transcript

Approver = Callable[[str, str], Reply]  # (reply words, action) -> approve/deny/unrelated
ENROLL_SECONDS = 10.0


class VerifierLike(Protocol):
    @property
    def enrolled(self) -> bool: ...
    def matches(self, samples: np.ndarray) -> tuple[bool, float]: ...
    def enroll(self, samples: np.ndarray) -> tuple[float, float]: ...


class RecorderLike(Protocol):
    def arm(self) -> None: ...
    def disarm(self) -> None: ...
    def snapshot(self) -> np.ndarray: ...
    def level(self) -> float: ...


class TranscriberLike(Protocol):
    def reset(self) -> None: ...
    def update(self, samples: np.ndarray) -> Transcript: ...


Screen = Callable[[], tuple[int, int, int, int]]  # width, height, x, y of the target screen


class Session:
    def __init__(
        self,
        cfg: Config,
        runner: Runner,
        rec: RecorderLike,
        stt: TranscriberLike,
        bar: Bar,
        bardisplay: BarDisplay,
        *,
        screen: Screen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        state: AppState | None = None,
        approver: Approver | None = None,
        verifier: VerifierLike | None = None,
    ) -> None:
        self.state = state
        self.approver = approver
        self.verifier = verifier
        self.cfg = cfg
        self.runner = runner
        self.rec = rec
        self.stt = stt
        self.bar = bar
        self.bardisplay = bardisplay
        self.screen = screen
        self.clock = clock
        self.sleep = sleep
        self.running = False
        self.stop_requested = False
        self._lock = threading.Lock()
        self._wanted = threading.Event()
        self._quit = threading.Event()
        self._approved = threading.Event()
        self._enroll = threading.Event()
        self.asking = False
        self._after_ask = False

    # ---- signals from other threads (hotkeys, menu) ----
    def toggle(self) -> None:
        with self._lock:
            if self.running:
                self.stop_requested = True
            else:
                self._wanted.set()

    def escape(self) -> None:
        with self._lock:
            if self.running:
                self.stop_requested = True

    def approve(self) -> None:
        """⏎ while the bar is asking."""
        if self.asking:
            self._approved.set()

    def request_enroll(self) -> None:
        self._enroll.set()
        self._wanted.set()

    def quit(self) -> None:
        self._quit.set()
        with self._lock:
            self.stop_requested = True
        self._wanted.set()

    def wanted(self) -> bool:
        return self._wanted.is_set()

    # ---- the loop ----
    def run_forever(self) -> None:
        while not self._quit.is_set():
            self.run_forever_once()

    def run_forever_once(self) -> bool:
        """Wait for one toggle and run one session. Returns False when quitting."""
        self._wanted.wait()
        self._wanted.clear()
        if self._quit.is_set():
            return False
        if self._enroll.is_set():
            self._enroll.clear()
            self.enroll()
            return True
        self.run_one()
        return True

    def _log(self, msg: str) -> None:
        if self.runner.display:
            self.runner.display.status(msg)

    # ---- voice approval, called from inside runner.tick while the session listens ----
    def ask(self, action: str) -> bool:
        if not self.running:
            self._log(f"approval for '{action}': no live session, denied")
            return False
        cfg = self.cfg
        self.asking = True
        self._approved.clear()
        self.bardisplay.asking(action)
        self.rec.arm()  # the reply starts now; what came before stays out of it
        self.stt.reset()
        start = self.clock()
        seen = 0
        result, reason = False, "no answer"
        try:
            while self.clock() - start < cfg.approval_seconds:
                if self.stop_requested:
                    with self._lock:
                        self.stop_requested = False  # Escape cancels the ask, not the session
                    reason = "escape"
                    break
                if self._approved.is_set():
                    result, reason = True, "return key"
                    break
                t = self.stt.update(self.rec.snapshot())
                self.bardisplay.listening(self.rec.level())
                self.bardisplay.show_transcript(t.committed, t.pending)
                if len(t.committed) > seen:
                    seen = len(t.committed)
                    reply = " ".join(t.committed)
                    r = self.approver(reply, action) if self.approver else Reply("unrelated", 0.0)
                    self._log(f"approval reply '{reply}': {r.kind} {r.confidence:.2f}")
                    if r.kind == "deny" and r.confidence >= cfg.thresholds.reply:
                        reason = f"'{reply}' = no"
                        break
                    if r.kind == "approve" and r.confidence >= cfg.thresholds.reply:
                        ok, sim = (
                            self.verifier.matches(self.rec.snapshot())
                            if self.verifier is not None
                            else (True, 1.0)
                        )
                        if ok:
                            result, reason = True, f"'{reply}' = yes (voice {sim:.2f})"
                            break
                        self._log(f"approval: '{reply}' did not sound like you ({sim:.2f})")
                self.sleep(cfg.tick_seconds)
        finally:
            self.asking = False
            self._log(f"approval for '{action}': {'yes' if result else 'no'} ({reason})")
            self.bardisplay.answered(result)
            self.rec.arm()
            self.stt.reset()
            self.runner.stream.reset()
            self._after_ask = True
        return result

    def enroll(self) -> bool:
        """Record the user for ENROLL_SECONDS and save the voiceprint."""
        if self.verifier is None:
            return False
        with self._lock:
            self.running = True
            self.stop_requested = False
        try:
            self.bar.show_at_top(*self.screen())
            self.bardisplay.begin()
            self.bar.decision("Read anything aloud for ten seconds")
            self.rec.arm()
            start = self.clock()
            while self.clock() - start < ENROLL_SECONDS and not self.stop_requested:
                self.bardisplay.listening(self.rec.level())
                self.bardisplay.countdown(ENROLL_SECONDS - (self.clock() - start))
                self.sleep(self.cfg.tick_seconds)
            samples = self.rec.snapshot()
            self.rec.disarm()
            try:
                lo, mean = self.verifier.enroll(samples)
            except ValueError as e:
                self.bardisplay.show_error(str(e))
                self.sleep(2.0)
                self.bar.hide()
                return False
            self._log(f"voice enrolled: self-similarity min {lo:.2f} mean {mean:.2f}")
            self.bar.decision("Voice enrolled")
            self.bardisplay.end(True)
            self.sleep(self.cfg.hide_after_seconds)
            self.bar.hide()
            return True
        finally:
            with self._lock:
                self.running = False

    def run_one(self) -> bool:
        cfg = self.cfg
        with self._lock:
            self.running = True
            self.stop_requested = False
        try:
            if self.state is not None:
                n = self.state.bump_sessions()
                self.bardisplay.hint_index = (n - 1) % 4 if self.state.show_hint else None
            self.bar.show_at_top(*self.screen())
            self.bardisplay.begin()
            self.rec.arm()
            self.stt.reset()
            start = self.clock()
            last_growth = start
            words = 0
            spoke = False
            self._after_ask = False
            while not self.stop_requested:
                t = self.stt.update(self.rec.snapshot())
                self.bardisplay.listening(self.rec.level())
                self.bardisplay.dictating = self.runner.stream.dictating
                self.runner.tick(t.committed, t.pending)
                if self._after_ask:
                    # The reply was consumed; the transcript starts over from here.
                    self._after_ask = False
                    words = 0
                    spoke = True
                    last_growth = self.clock()
                elif len(t.committed) > words:
                    words = len(t.committed)
                    spoke = True
                    last_growth = self.clock()
                now = self.clock()
                remaining = cfg.silence_seconds - (now - last_growth)
                self.bardisplay.countdown(remaining if spoke else None)
                if self.runner.display:
                    self.runner.display.status(
                        f"tick words={words} remaining={remaining:.1f}s t={now - start:.1f}s"
                    )
                if spoke and remaining <= 0:
                    break
                if now - start >= cfg.max_session_seconds:
                    break
                self.sleep(cfg.tick_seconds)
            self.runner.finish()
            self.rec.disarm()
            if self.runner.display:
                self.runner.display.status(
                    f"session end: words={words} stop={self.stop_requested} "
                    f"elapsed={self.clock() - start:.1f}s"
                )
            acted = self.bardisplay.acted
            self.bardisplay.end(acted)
            self.sleep(cfg.hide_after_seconds)
            self.bar.hide()
            return acted
        finally:
            with self._lock:
                self.running = False
