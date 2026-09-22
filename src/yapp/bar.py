"""Python -> JavaScript façade for the pill window. Every call becomes one window.yapp.* call."""

from __future__ import annotations

import json
from typing import Any, Protocol


class WindowLike(Protocol):
    def evaluate_js(self, js: str) -> object: ...
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def move(self, x: int, y: int) -> None: ...


def _j(v: Any) -> str:
    # JSON is valid JS; escape "/" so "</script>" can never terminate an inline block.
    return json.dumps(v).replace("/", "\\/")


class Bar:
    def __init__(self, window: WindowLike, width: int = 360, height: int = 120) -> None:
        self.w = window
        self.width = width
        self.height = height
        self.visible = False

    def show_at_top(
        self, screen_w: int, screen_h: int, screen_x: int = 0, screen_y: int = 0
    ) -> None:
        x = screen_x + (screen_w - self.width) // 2
        y = screen_y + int(screen_h * 0.12)
        self.w.move(x, y)
        self.w.show()
        self.visible = True

    def hide(self) -> None:
        self.w.hide()
        self.visible = False

    def _call(self, fn: str, *args: Any) -> None:
        # Guarded so a page that predates a method treats the call as a no-op.
        call = f"window.yapp.{fn}({', '.join(_j(a) for a in args)})"
        self.w.evaluate_js(f"window.yapp && window.yapp.{fn} && {call}")

    def set_state(self, name: str, **opts: Any) -> None:
        self._call("setState", name, opts)

    def transcript(self, locked: str, pending: str, live: bool = True) -> None:
        self._call("setTranscript", locked, pending, live)

    def decision(self, text: str, muted: bool = False) -> None:
        self._call("setDecision", text, muted)

    def level(self, v: float) -> None:
        self._call("setLevel", round(v, 3))

    def confidence(self, v: float) -> None:
        self._call("setConfidence", round(v, 3))

    def commit(self) -> None:
        self._call("commit")

    def countdown(self, seconds: float | None) -> None:
        """Seconds until the bar closes for silence; None clears it."""
        self._call("setCountdown", round(seconds, 1) if seconds is not None else 0)

    def hint(self, visible: bool) -> None:
        self._call("setHint", visible)

    def permissions(self, grants: dict[str, str]) -> None:
        self._call("setPermissions", grants)
