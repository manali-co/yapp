"""Native (AppKit) fixes pywebview does not do on current macOS."""

from __future__ import annotations

from typing import Any

# AppKit constants (kept literal so this module imports without PyObjC in tests).
OVERLAY_LEVEL = 1000  # kCGScreenSaverWindowLevel: above full-screen apps and the Dock
CAN_JOIN_ALL_SPACES = 1 << 0  # NSWindowCollectionBehaviorCanJoinAllSpaces
STATIONARY = 1 << 4  # NSWindowCollectionBehaviorStationary
IGNORES_CYCLE = 1 << 6  # NSWindowCollectionBehaviorIgnoresCycle
FULL_SCREEN_AUXILIARY = 1 << 8  # NSWindowCollectionBehaviorFullScreenAuxiliary


def make_transparent(window: Any) -> None:
    """Make a pywebview window a Spotlight-style overlay.

    Borderless, clear, web view without background (pywebview's `transparent=True` leaves a
    titled window and uses a deprecated WebKit key, so a rectangle stays visible), floating above
    every app including full-screen ones, on every Space, and never taking keyboard focus so
    typing keeps landing in the user's app. Call after the page has loaded; safe off the main
    thread (the work is scheduled with callAfter).
    """
    from PyObjCTools import AppHelper

    def apply() -> None:
        from AppKit import NSColor, NSWindowStyleMaskBorderless
        from webview.platforms import cocoa

        bv = cocoa.BrowserView.instances.get(window.uid)
        if bv is None:
            return
        ns, wk = bv.window, bv.webview
        ns.setStyleMask_(NSWindowStyleMaskBorderless)
        ns.setOpaque_(False)
        ns.setHasShadow_(False)
        ns.setBackgroundColor_(NSColor.clearColor())
        # Above full-screen apps and on every Space, like Spotlight; never becomes key.
        ns.setLevel_(OVERLAY_LEVEL)
        ns.setCollectionBehavior_(
            CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY | STATIONARY | IGNORES_CYCLE
        )
        ns.setHidesOnDeactivate_(False)
        for key, value in (("drawsBackground", False), ("drawsTransparentBackground", True)):
            try:
                wk.setValue_forKey_(value, key)
            except Exception:  # noqa: BLE001 - private keys come and go across WebKit versions
                pass
        try:
            wk.setUnderPageBackgroundColor_(NSColor.clearColor())
        except Exception:  # noqa: BLE001
            pass

    AppHelper.callAfter(apply)


# Room around the pill so its drop shadow is not clipped by the window edge.
MARGIN = 24
EMBED_CSS = (
    "body.embed{width:100vw;height:100vh;margin:0;display:grid;place-items:center;"
    "overflow:visible;background:transparent}"
)
INJECT_CSS_JS = (
    "(function(){var s=document.createElement('style');s.textContent="
    + repr(EMBED_CSS)
    + ";document.head.appendChild(s);})();"
)


def accessory_app() -> None:
    """No Dock icon, and showing our windows never activates the app (no Space switching)."""
    from PyObjCTools import AppHelper

    def apply() -> None:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory

        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    AppHelper.callAfter(apply)


class OverlayWindow:
    """WindowLike adapter that shows and hides without activating the app.

    pywebview's own show() calls makeKeyAndOrderFront and activates the application, which
    pulls the user out of a full-screen Space and steals keyboard focus from the app they are
    dictating into. Ordering front "regardless" avoids both.
    """

    def __init__(self, window: Any) -> None:
        self._w = window

    def _native(self) -> Any:
        from webview.platforms import cocoa

        bv = cocoa.BrowserView.instances.get(self._w.uid)
        return bv.window if bv is not None else None

    def evaluate_js(self, js: str) -> object:
        return self._w.evaluate_js(js)

    def move(self, x: int, y: int) -> None:
        self._w.move(x, y)

    def show(self) -> None:
        from PyObjCTools import AppHelper

        def apply() -> None:
            ns = self._native()
            if ns is not None:
                ns.orderFrontRegardless()

        AppHelper.callAfter(apply)

    def hide(self) -> None:
        from PyObjCTools import AppHelper

        def apply() -> None:
            ns = self._native()
            if ns is not None:
                ns.orderOut_(None)

        AppHelper.callAfter(apply)
