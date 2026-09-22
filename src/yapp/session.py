"""One Spotlight-style session.

Show the bar, listen hands-free, act, hide on hotkey, Escape, or silence.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from yapp.bar import Bar
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.runner import Runner
from yapp.stt import Transcript


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
    ) -> None:
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
            self._wanted.wait()
            self._wanted.clear()
            if self._quit.is_set():
                break
            self.run_one()

    def run_one(self) -> bool:
        cfg = self.cfg
        with self._lock:
            self.running = True
            self.stop_requested = False
        try:
            self.bar.show_at_top(*self.screen())
            self.bardisplay.begin()
            self.rec.arm()
            self.stt.reset()
            start = self.clock()
            last_growth = start
            words = 0
            while not self.stop_requested:
                t = self.stt.update(self.rec.snapshot())
                self.bardisplay.listening(self.rec.level())
                self.bardisplay.dictating = self.runner.stream.dictating
                self.runner.tick(t.committed, t.pending)
                if len(t.committed) > words:
                    words = len(t.committed)
                    last_growth = self.clock()
                now = self.clock()
                if words > 0 and now - last_growth >= cfg.silence_seconds:
                    break
                if now - start >= cfg.max_session_seconds:
                    break
                self.sleep(cfg.tick_seconds)
            self.runner.finish()
            self.rec.disarm()
            acted = self.bardisplay.acted
            self.bardisplay.end(acted)
            self.sleep(cfg.hide_after_seconds)
            self.bar.hide()
            return acted
        finally:
            with self._lock:
                self.running = False
