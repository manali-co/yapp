"""Native (AppKit) fixes pywebview does not do on current macOS."""

from __future__ import annotations

from typing import Any


def make_transparent(window: Any) -> None:
    """Make a pywebview window truly see-through: borderless, clear, web view without background.

    pywebview's `transparent=True` leaves a titled window and uses a deprecated WebKit key, so
    on macOS 14+ a rectangle stays visible around the page. Call after the page has loaded.
    Safe to call off the main thread: the work is scheduled with callAfter.
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
