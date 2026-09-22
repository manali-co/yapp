"""Python -> JavaScript façade for the pill window, and the JS -> Python event bridge."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from yapp.permissions import Grant, Permissions

EVENTS = ("action", "escape", "open-settings", "later", "permissions-complete")

# Injected after each page loads: forwards the page's yapp:* CustomEvents to Python.
BRIDGE_JS = (
    "(function(){var names=" + json.dumps(list(EVENTS)) + ";"
    "names.forEach(function(n){window.addEventListener('yapp:'+n,function(e){"
    "if(window.pywebview&&window.pywebview.api){window.pywebview.api.event(n,e.detail||{});}"
    "});});})();"
)


class WindowLike(Protocol):
    def evaluate_js(self, js: str) -> object: ...
    def show(self) -> None: ...
    def hide(self) -> None: ...
    def move(self, x: int, y: int) -> None: ...


def _j(v: Any) -> str:
    # JSON is valid JS; escape "/" so "</script>" can never terminate an inline block.
    return json.dumps(v).replace("/", "\\/")


def grants_for_page(p: Permissions) -> dict[str, bool | None]:
    """The pages want true / false / null, never strings."""
    to_bool = {Grant.GRANTED: True, Grant.MISSING: False, Grant.UNKNOWN: None}
    return {
        "mic": to_bool[p.mic],
        "input": to_bool[p.input],
        "accessibility": to_bool[p.accessibility],
    }


class Events:
    """Exposed to the page as window.pywebview.api; BRIDGE_JS calls event(name, detail)."""

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        self._on_event = on_event

    def event(self, name: str, detail: dict[str, Any] | None = None) -> None:
        self._on_event(str(name), dict(detail or {}))


class Bar:
    def __init__(self, window: WindowLike, width: int = 400, height: int = 96) -> None:
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

    def countdown(self, seconds: float | None, total: float = 4.0) -> None:
        """Seconds until the bar closes for silence; None clears the ring."""
        if seconds is None:
            self._call("setCountdown", None)
        else:
            self._call("setCountdown", round(max(0.0, seconds), 1), total)

    def hint(self, value: bool | int | str) -> None:
        self._call("setHint", value)

    def permissions(self, p: Permissions) -> None:
        self._call("setPermissions", grants_for_page(p))

    def appearance(self, mode: str | None) -> None:
        self._call("setAppearance", mode)
