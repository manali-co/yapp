"""Yapp's pointer, in three tiers. macOS has one cursor; these keep it the user's.

1. No pointer: Accessibility actions (elsewhere; ax.py).
2. A virtual pointer: a click posted straight to the target process with its own
   coordinates. The real cursor does not move. Most AppKit and Chromium apps take it.
3. Borrow the real pointer: warp, click, warp back within milliseconds. Only when the user
   is not holding a button, and only under the bar's attention state (workspace.py).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

LEFT, RIGHT = 0, 1


def pointer_position() -> tuple[float, float] | None:
    """Where the pointer is, in the same top-left coordinates the Accessibility API uses."""
    try:
        import Quartz

        here = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        return float(here.x), float(here.y)
    except Exception:  # noqa: BLE001 - no pointer to read (headless): unknown
        return None


class ClickLog:
    """Where the user's last mouse-down landed, recorded as it happens (a listen-only event
    tap on its own thread). The pointer may have moved on by the time anyone asks, so the
    position at the click is the only honest answer to "where did they click?"."""

    def __init__(self) -> None:
        self._last: tuple[float, float] | None = None
        self._listener: Any = None

    def start(self) -> bool:
        try:
            from pynput import mouse

            def on_click(x: float, y: float, button: Any, pressed: bool) -> None:
                if pressed:
                    self._last = (float(x), float(y))

            self._listener = mouse.Listener(on_click=on_click)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception:  # noqa: BLE001 - no event tap (permissions, headless): fall back
            return False

    def where(self) -> tuple[float, float] | None:
        """The last mouse-down, or the pointer now when no click was recorded."""
        return self._last if self._last is not None else pointer_position()


def buttons_down() -> bool:
    """Is the user holding a mouse button (mid-drag, mid-click)?"""
    import Quartz

    src = Quartz.kCGEventSourceStateCombinedSessionState
    return bool(
        Quartz.CGEventSourceButtonState(src, LEFT) or Quartz.CGEventSourceButtonState(src, RIGHT)
    )


def pid_of(element: Any) -> int | None:
    from ApplicationServices import AXUIElementGetPid

    err, pid = AXUIElementGetPid(element, None)
    return int(pid) if err == 0 else None


def _click_events(x: float, y: float) -> tuple[Any, Any]:
    import Quartz

    down = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (x, y), Quartz.kCGMouseButtonLeft
    )
    up = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventSetIntegerValueField(down, Quartz.kCGMouseEventClickState, 1)
    Quartz.CGEventSetIntegerValueField(up, Quartz.kCGMouseEventClickState, 1)
    return down, up


def click_in_app(pid: int, x: float, y: float) -> bool:
    """Tier 2: deliver a click at (x, y) to one process; the system cursor stays put."""
    import Quartz

    down, up = _click_events(x, y)
    Quartz.CGEventPostToPid(pid, down)
    Quartz.CGEventPostToPid(pid, up)
    return True


def borrow_pointer(
    x: float,
    y: float,
    *,
    is_busy: Callable[[], bool] = buttons_down,
    settle: Callable[[float], None] | None = None,
) -> bool:
    """Tier 3: move the real cursor, click, put it back. Refuses while a button is held."""
    import time

    import Quartz

    if is_busy():
        return False
    wait = settle or time.sleep
    here = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    Quartz.CGWarpMouseCursorPosition((x, y))
    wait(0.02)
    down, up = _click_events(x, y)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
    wait(0.02)
    Quartz.CGWarpMouseCursorPosition((here.x, here.y))
    return True
