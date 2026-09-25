"""The glow around windows Yapp is working in, and Yapp's own drawn cursor.

Like the tint a browser agent puts on the tab it drives: a soft rounded frame in the avatar's
acting hue, just outside the window's edge, tracking the window as it moves. Steady while
acting, pulsing while Yapp needs the user (attention), fading when done, gone at clean-up.
Never drawn on the user's own windows.

The colour is read from the design bundle (the avatar's acting state in yapp-avatar.js) so the
frame matches the bar; the timings come from tokens.css.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from yapp.windows import Rect

ACTING_DEFAULT = (0.70, 0.060, 45.0)  # oklch L, C, h of the avatar's acting state
PAD = 10.0  # px between the window edge and the glow's stroke
_ACTING_RE = re.compile(r"acting:\s*\{[^}]*?L:\s*([\d.]+),\s*C:\s*([\d.]+),\s*h:\s*([\d.]+)")
_DUR_RE = re.compile(r"--yapp-dur-(\w+):\s*(\d+)ms")


def acting_hue(avatar_js: str) -> tuple[float, float, float]:
    m = _ACTING_RE.search(avatar_js)
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else ACTING_DEFAULT


def durations(tokens_css: str) -> dict[str, int]:
    return {k: int(v) for k, v in _DUR_RE.findall(tokens_css)}


def oklch_to_srgb(L: float, C: float, h: float) -> tuple[float, float, float]:
    """OKLCH → sRGB (0..1, clipped). The avatar uses OKLCH; AppKit wants RGB."""
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = l_**3, m_**3, s_**3
    r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3
    g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3
    bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3

    def gamma(x: float) -> float:
        x = min(1.0, max(0.0, x))
        return 1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x

    return gamma(r), gamma(g), gamma(bl)


class Drawer(Protocol):
    """What the native layer must do; the state machine never touches AppKit itself."""

    def place(self, frame: Rect) -> None: ...
    def pulse(self, on: bool) -> None: ...
    def fade(self, ms: int) -> None: ...
    def hide(self) -> None: ...
    def cursor(self, point: tuple[float, float] | None) -> None: ...


@dataclass
class Highlight:
    """State machine: hidden → acting → (attention ↔ acting) → done (fading) → hidden."""

    drawer: Drawer
    frame_of: Callable[[Any], Rect | None]
    settle_ms: int = 1400
    state: str = "hidden"
    window: Any = None

    def show(self, window: Any) -> bool:
        """Glow around `window` (an AX window) while Yapp acts in it."""
        frame = self.frame_of(window) if window is not None else None
        if frame is None:
            return False
        self.window = window
        self.drawer.place(frame)
        if self.state != "attention":
            self.state = "acting"
        return True

    def track(self) -> None:
        """Called on a timer while visible: follow the window if it moved or resized."""
        if self.state in ("acting", "attention") and self.window is not None:
            frame = self.frame_of(self.window)
            if frame is None:
                self.hide()
            else:
                self.drawer.place(frame)

    def attention(self, on: bool) -> None:
        if self.state == "hidden":
            return
        self.state = "attention" if on else "acting"
        self.drawer.pulse(on)

    def cursor(self, point: tuple[float, float] | None) -> None:
        if self.state != "hidden":
            self.drawer.cursor(point)

    def done(self) -> None:
        if self.state in ("acting", "attention"):
            self.state = "done"
            self.drawer.pulse(False)
            self.drawer.fade(self.settle_ms)

    def hide(self) -> None:
        self.state = "hidden"
        self.window = None
        self.drawer.hide()


# ---------------------------------------------------------------- AppKit


_classes: dict[str, Any] = {}  # Objective-C classes may be defined only once per process
_drawer: Drawer | None = None


def _objc_classes(colour: Any) -> tuple[Any, Any]:
    """GlowView and the timer target, defined once (PyObjC refuses a second definition)."""
    if "GlowView" in _classes:
        return _classes["GlowView"], _classes["State"]
    from AppKit import NSBezierPath, NSColor, NSMakeRect, NSShadow, NSView
    from Foundation import NSObject

    class GlowView(NSView):  # type: ignore[misc]
        dot: Any = None
        colour: Any = None

        def isFlipped(self) -> bool:
            return True

        def drawRect_(self, rect: Any) -> None:
            bounds = self.bounds()
            inset = PAD - 2
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(
                    inset, inset, bounds.size.width - 2 * inset, bounds.size.height - 2 * inset
                ),
                14.0,
                14.0,
            )
            path.setLineWidth_(3.0)
            shadow = NSShadow.alloc().init()
            shadow.setShadowColor_(self.colour.colorWithAlphaComponent_(0.9))
            shadow.setShadowBlurRadius_(16.0)
            shadow.set()
            self.colour.colorWithAlphaComponent_(0.95).setStroke()
            path.stroke()
            if self.dot is not None:
                x, y = self.dot
                self.colour.setFill()
                NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - 5, y - 5, 10, 10)).fill()
                NSColor.whiteColor().colorWithAlphaComponent_(0.9).setFill()
                NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - 2, y - 2, 4, 4)).fill()

    class State(NSObject):  # type: ignore[misc]
        window: Any = None
        view: Any = None
        timer: Any = None
        up: bool = False
        fading: int = 0  # bumps on every place/fade so a stale fade cannot hide a new glow

        def tick_(self, timer: Any) -> None:
            if self.window is None:
                return
            self.up = not self.up
            self.window.animator().setAlphaValue_(1.0 if self.up else 0.45)

    _classes["GlowView"], _classes["State"] = GlowView, State
    return GlowView, State


def native_drawer(rgb: tuple[float, float, float], pulse_ms: int = 380) -> Drawer:
    """The real overlay: borderless, click-through, on every Space, above normal windows.
    One per process: the same window is reused by every runner built later."""
    global _drawer
    if _drawer is not None:
        return _drawer
    from AppKit import (
        NSAnimationContext,
        NSColor,
        NSFloatingWindowLevel,
        NSMakeRect,
        NSScreen,
        NSWindow,
    )
    from Foundation import NSTimer
    from PyObjCTools import AppHelper

    from yapp.native import CAN_JOIN_ALL_SPACES, FULL_SCREEN_AUXILIARY, IGNORES_CYCLE, STATIONARY

    r, g, b = rgb
    colour = NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)
    GlowView, State = _objc_classes(colour)
    st = State.alloc().init()

    def ensure() -> Any:
        if st.window is None:
            w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 10, 10), 0, 2, False
            )
            w.setOpaque_(False)
            w.setBackgroundColor_(NSColor.clearColor())
            w.setHasShadow_(False)
            w.setIgnoresMouseEvents_(True)
            w.setLevel_(NSFloatingWindowLevel)
            w.setCollectionBehavior_(
                CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY | STATIONARY | IGNORES_CYCLE
            )
            w.setReleasedWhenClosed_(False)
            st.view = GlowView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
            st.view.colour = colour
            w.setContentView_(st.view)
            st.window = w
        return st.window

    def stop_pulse() -> None:
        if st.timer is not None:
            st.timer.invalidate()
            st.timer = None
        if st.window is not None:
            st.window.setAlphaValue_(1.0)

    class Native:
        def place(self, frame: Rect) -> None:
            def apply() -> None:
                w = ensure()
                # A fade may be running from the previous window: stop it, so the frame
                # never lingers at the old size around a smaller window.
                st.fading += 1
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(0.0)
                w.animator().setAlphaValue_(1.0)
                NSAnimationContext.endGrouping()
                main_h = NSScreen.screens()[0].frame().size.height
                x, y = frame.x - PAD, main_h - (frame.y + frame.h) - PAD
                w.setFrame_display_(NSMakeRect(x, y, frame.w + 2 * PAD, frame.h + 2 * PAD), True)
                w.setAlphaValue_(1.0)
                w.orderFrontRegardless()
                st.view.setNeedsDisplay_(True)

            AppHelper.callAfter(apply)

        def pulse(self, on: bool) -> None:
            def apply() -> None:
                if on and st.timer is None and st.window is not None:
                    st.timer = (
                        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                            pulse_ms / 1000.0, st, "tick:", None, True
                        )
                    )
                elif not on:
                    stop_pulse()

            AppHelper.callAfter(apply)

        def fade(self, ms: int) -> None:
            def apply() -> None:
                stop_pulse()
                if st.window is None:
                    return
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(ms / 1000.0)
                st.window.animator().setAlphaValue_(0.0)
                NSAnimationContext.endGrouping()
                AppHelper.callLater(
                    ms / 1000.0 + 0.05, lambda: st.window and st.window.orderOut_(None)
                )

            AppHelper.callAfter(apply)

        def hide(self) -> None:
            def apply() -> None:
                stop_pulse()
                if st.window is not None:
                    st.window.orderOut_(None)

            AppHelper.callAfter(apply)

        def cursor(self, point: tuple[float, float] | None) -> None:
            def apply() -> None:
                if st.view is None or st.window is None:
                    return
                if point is None:
                    st.view.dot = None
                else:
                    origin = st.window.frame().origin
                    main_h = NSScreen.screens()[0].frame().size.height
                    top = main_h - (origin.y + st.window.frame().size.height)
                    st.view.dot = (point[0] - origin.x, point[1] - top)
                st.view.setNeedsDisplay_(True)

            AppHelper.callAfter(apply)

    _drawer = Native()
    return _drawer


def build_highlight(ui_dir: Any, frame_of: Callable[[Any], Rect | None]) -> Highlight:
    """Highlight wired to the design bundle's colour and timings."""
    avatar = ui_dir.joinpath("yapp-avatar.js").read_text()
    tokens = ui_dir.joinpath("tokens.css").read_text()
    L, C, h = acting_hue(avatar)
    d = durations(tokens)
    drawer = native_drawer(oklch_to_srgb(L, C, h), pulse_ms=d.get("pulse", 380))
    return Highlight(drawer, frame_of, settle_ms=d.get("settle", 1400))
