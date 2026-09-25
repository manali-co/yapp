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
