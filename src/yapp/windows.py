"""Displays and window frames through Accessibility, plus the layout rules for parallel mode.

All geometry here is in top-left screen coordinates (what AX reports and accepts). NSScreen
speaks bottom-left Cocoa coordinates; `displays()` converts once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    def overlap(self, other: Rect) -> float:
        w = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        h = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        return max(w, 0.0) * max(h, 0.0)

    def left_half(self) -> Rect:
        return Rect(self.x, self.y, self.w / 2, self.h)

    def right_half(self) -> Rect:
        return Rect(self.x + self.w / 2, self.y, self.w / 2, self.h)

    def contains_centre(self, other: Rect) -> bool:
        cx, cy = other.x + other.w / 2, other.y + other.h / 2
        return self.x <= cx <= self.x + self.w and self.y <= cy <= self.y + self.h


@dataclass(frozen=True)
class Display:
    name: str
    frame: Rect  # usable area: no menu bar, no Dock


# ---------------------------------------------------------------- pure layout


@dataclass(frozen=True)
class Layout:
    """Where the user's window goes (None = leave it) and where Yapp works."""

    work: Rect
    user: Rect | None
    kind: str  # "display" | "split"


def display_of(frame: Rect, displays: list[Display]) -> Display:
    return max(displays, key=lambda d: d.frame.overlap(frame))


def plan_layout(user_window: Rect | None, displays: list[Display]) -> Layout:
    """Parallel mode: another display when there is one, else split the user's display."""
    if not displays:
        raise ValueError("no displays")
    home = display_of(user_window, displays) if user_window else displays[0]
    others = [d for d in displays if d is not home]
    if others:
        best = max(others, key=lambda d: d.frame.area)
        return Layout(work=best.frame, user=None, kind="display")
    return Layout(work=home.frame.right_half(), user=home.frame.left_half(), kind="split")


def tile(work: Rect, n_existing: int, step: float = 28.0) -> Rect:
    """The n-th window Yapp opens in the work area: a gentle cascade so all stay reachable."""
    inset = min(step * n_existing, work.w * 0.3)
    return Rect(work.x + inset, work.y + inset, work.w - inset, work.h - inset)


# ---------------------------------------------------------------- macOS


def displays() -> list[Display]:
    from AppKit import NSScreen

    screens = list(NSScreen.screens())
    if not screens:
        return []
    main_h = screens[0].frame().size.height
    out = []
    for s in screens:
        v = s.visibleFrame()
        top_left_y = main_h - (v.origin.y + v.size.height)
        out.append(
            Display(
                str(s.localizedName()), Rect(v.origin.x, top_left_y, v.size.width, v.size.height)
            )
        )
    return out


def _attr(el: Any, name: str) -> Any:
    from ApplicationServices import AXUIElementCopyAttributeValue

    err, value = AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def _ax_value(el: Any, name: str) -> tuple[float, float] | None:
    from ApplicationServices import AXValueGetValue

    v = _attr(el, name)
    if v is None:
        return None
    kind = 1 if name == "AXPosition" else 2  # kAXValueCGPointType / kAXValueCGSizeType
    ok, out = AXValueGetValue(v, kind, None)
    if not ok or out is None:
        return None
    return (float(out.x), float(out.y)) if kind == 1 else (float(out.width), float(out.height))


def window_frame(win: Any) -> Rect | None:
    pos, size = _ax_value(win, "AXPosition"), _ax_value(win, "AXSize")
    if pos is None or size is None:
        return None
    return Rect(pos[0], pos[1], size[0], size[1])


def set_window_frame(win: Any, rect: Rect) -> bool:
    from ApplicationServices import AXUIElementSetAttributeValue, AXValueCreate
    from Foundation import NSPoint, NSSize

    if _attr(win, "AXFullScreen"):
        AXUIElementSetAttributeValue(win, "AXFullScreen", False)
    ok_size = (
        AXUIElementSetAttributeValue(win, "AXSize", AXValueCreate(2, NSSize(rect.w, rect.h))) == 0
    )
    ok_pos = (
        AXUIElementSetAttributeValue(win, "AXPosition", AXValueCreate(1, NSPoint(rect.x, rect.y)))
        == 0
    )
    # Some apps clamp the size until the position is in; set the size once more.
    AXUIElementSetAttributeValue(win, "AXSize", AXValueCreate(2, NSSize(rect.w, rect.h)))
    return bool(ok_size and ok_pos)


def app_windows(app_name: str) -> list[Any]:
    from yapp.ax import app_element

    el, _ = app_element(app_name)
    return list(_attr(el, "AXWindows") or [])


def focused_window(app_name: str) -> Any:
    from yapp.ax import app_element

    el, _ = app_element(app_name)
    return _attr(el, "AXFocusedWindow")


def window_title(win: Any) -> str:
    return str(_attr(win, "AXTitle") or "")


def close_window(win: Any) -> bool:
    from ApplicationServices import AXUIElementPerformAction

    button = _attr(win, "AXCloseButton")
    if button is None:
        return False
    return bool(AXUIElementPerformAction(button, "AXPress") == 0)


def sheet_buttons(win: Any) -> list[tuple[str, Any]]:
    """Buttons of the sheet attached to a window (the 'Do you want to save?' kind)."""
    out: list[tuple[str, Any]] = []
    for sheet in list(_attr(win, "AXSheets") or []):
        stack = list(_attr(sheet, "AXChildren") or [])
        while stack:
            el = stack.pop()
            if _attr(el, "AXRole") == "AXButton":
                out.append((str(_attr(el, "AXTitle") or _attr(el, "AXDescription") or ""), el))
            stack.extend(list(_attr(el, "AXChildren") or []))
    return out


def press(el: Any) -> bool:
    from ApplicationServices import AXUIElementPerformAction

    return bool(AXUIElementPerformAction(el, "AXPress") == 0)


DISCARD_TITLES = ("don't save", "don’t save", "delete", "discard", "discard changes")


def discard_button(buttons: list[tuple[str, Any]]) -> tuple[str, Any] | None:
    for title, el in buttons:
        if title.strip().lower() in DISCARD_TITLES:
            return title, el
    return None


def window_buttons(win: Any, max_nodes: int = 400) -> list[tuple[str, Any]]:
    """Buttons anywhere in a window (alerts are windows without a close button)."""
    out: list[tuple[str, Any]] = []
    stack = list(_attr(win, "AXChildren") or [])
    seen = 0
    while stack and seen < max_nodes:
        el = stack.pop()
        seen += 1
        if _attr(el, "AXRole") == "AXButton":
            out.append((str(_attr(el, "AXTitle") or _attr(el, "AXDescription") or ""), el))
        stack.extend(list(_attr(el, "AXChildren") or []))
    return out


def dismiss_alert(win: Any) -> bool:
    """An app-modal alert ('You have 3 documents with unconfirmed changes…'): press Cancel."""
    if _attr(win, "AXCloseButton") is not None:
        return False
    for title, el in window_buttons(win):
        if title.strip().lower() == "cancel":
            return press(el)
    return False


def close_and_discard(win: Any, settle: float = 0.5) -> str:
    """Harness helper: close a window and throw away unsaved changes. Never used on the user's
    own documents by the product; the product asks the guard first (see workspace.py)."""
    import time

    if not close_window(win):
        return "could not close"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        time.sleep(settle)
        found = discard_button(sheet_buttons(win))
        if found is not None:
            title, el = found
            return f"closed, pressed {title}" if press(el) else f"closed, could not press {title}"
        if _attr(win, "AXRole") is None:  # the window is gone: nothing asked
            return "closed"
    return "closed (no sheet answered)"


def discard_open_sheets(app_name: str) -> int:
    """Answer every 'save?' sheet still open in the app with its throw-away button."""
    n = 0
    for w in app_windows(app_name):
        found = discard_button(sheet_buttons(w))
        if found is not None and press(found[1]):
            n += 1
    return n


class WindowManager:
    """Applies a Layout to real windows and remembers what it moved so clean-up can undo it."""

    def __init__(
        self,
        displays_fn: Callable[[], list[Display]] = displays,
        focused: Callable[[str], Any] = focused_window,
        frame_of: Callable[[Any], Rect | None] = window_frame,
        set_frame: Callable[[Any, Rect], bool] = set_window_frame,
        windows_of: Callable[[str], list[Any]] = app_windows,
        log: Callable[[str], None] = lambda s: None,
    ) -> None:
        self._displays = displays_fn
        self._focused = focused
        self._frame_of = frame_of
        self._set_frame = set_frame
        self._windows_of = windows_of
        self.log = log
        self.layout: Layout | None = None
        self.user_window: Any = None
        self.user_frame: Rect | None = None
        self.placed = 0

    def begin_parallel(self, user_app: str) -> Layout:
        """Decide the work area from the user's focused window and, when splitting, move it."""
        win = self._focused(user_app)
        frame = self._frame_of(win) if win is not None else None
        layout = plan_layout(frame, self._displays())
        self.layout = layout
        if layout.user is not None and win is not None and frame is not None:
            self.user_window, self.user_frame = win, frame
            if self._set_frame(win, layout.user):
                self.log(f"windows: {user_app} moved to the left half; Yapp works on the right")
            else:
                self.log(f"windows: could not move {user_app}; working on the right anyway")
        else:
            self.log(f"windows: working on another display ({layout.work})")
        return layout

    def place(self, app_name: str) -> bool:
        """Put the app's focused window into the work area (parallel mode only)."""
        if self.layout is None:
            return False
        win = self._focused(app_name)
        if win is None:
            wins = self._windows_of(app_name)
            win = wins[0] if wins else None
        if win is None:
            return False
        ok = self._set_frame(win, tile(self.layout.work, self.placed))
        if ok:
            self.placed += 1
        return ok

    def place_window(self, win: Any) -> bool:
        """Put one specific window (a document Yapp just created) into the work area."""
        if self.layout is None or win is None:
            return False
        ok = self._set_frame(win, tile(self.layout.work, self.placed))
        if ok:
            self.placed += 1
        return ok

    def restore(self) -> bool:
        if self.user_window is None or self.user_frame is None:
            return False
        ok = self._set_frame(self.user_window, self.user_frame)
        self.user_window = self.user_frame = None
        self.layout = None
        self.placed = 0
        return ok
