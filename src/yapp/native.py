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
