"""Native (AppKit) fixes pywebview does not do on current macOS."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
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
        # Private WebKit keys come and go across versions; a missing one is not an error.
        for key, value in (("drawsBackground", False), ("drawsTransparentBackground", True)):
            with contextlib.suppress(Exception):
                wk.setValue_forKey_(value, key)
        with contextlib.suppress(Exception):
            wk.setUnderPageBackgroundColor_(NSColor.clearColor())

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


def accessory_app_now() -> None:
    """Make the process an Accessory app (no Dock icon) BEFORE any window exists.

    A window created while the app is Regular never joins full-screen Spaces, even if the app
    turns Accessory later: it stays on the desktop Space and the pill is invisible over a
    full-screen Chrome. pywebview forces the Regular policy when its Cocoa backend is imported,
    so import that first, then override, then let pywebview create the window.
    """
    import webview.platforms.cocoa  # noqa: F401 - its import sets the Regular policy
    from AppKit import NSApp, NSApplicationActivationPolicyAccessory

    NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def accessory_app() -> None:
    """Same as accessory_app_now, scheduled on the main thread (call from other threads)."""
    from PyObjCTools import AppHelper

    AppHelper.callAfter(accessory_app_now)


def warm_text_services(timeout: float = 5.0) -> bool:
    """Read the keyboard layout on the main thread once and hand pynput's listener a copy.

    pynput's listener thread reads the layout through Text Services (TIS) when it starts.
    Since macOS 26 that library asserts it is on the main queue and aborts the whole process
    otherwise (dispatch_assert_queue in HIToolbox); a Regular app happened to get away with it,
    an Accessory app does not. So compute the context here and make the listener reuse it.
    """
    import contextlib
    import threading
    from collections.abc import Iterator

    from pynput._util import darwin as pynput_darwin
    from pynput.keyboard import _darwin as pynput_keyboard
    from PyObjCTools import AppHelper

    done = threading.Event()
    holder: dict[str, Any] = {}

    def apply() -> None:
        try:
            with pynput_darwin.keycode_context() as ctx:
                holder["ctx"] = ctx
        finally:
            done.set()

    AppHelper.callAfter(apply)
    if not (done.wait(timeout) and "ctx" in holder):
        return False

    @contextlib.contextmanager
    def cached() -> Iterator[Any]:
        yield holder["ctx"]

    pynput_keyboard.keycode_context = cached  # the listener thread never touches TIS now
    return True


def apply_overlay(ns: Any) -> None:
    """Spotlight-style window properties; safe to re-apply on every show."""
    from AppKit import NSColor

    ns.setLevel_(OVERLAY_LEVEL)
    ns.setCollectionBehavior_(
        CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY | STATIONARY | IGNORES_CYCLE
    )
    ns.setHidesOnDeactivate_(False)
    ns.setOpaque_(False)
    ns.setBackgroundColor_(NSColor.clearColor())


class OverlayWindow:
    """WindowLike adapter that shows and hides without activating the app.

    pywebview's own show() calls makeKeyAndOrderFront and activates the application, which
    pulls the user out of a full-screen Space and steals keyboard focus from the app they are
    dictating into. Ordering front "regardless" avoids both.
    """

    def __init__(self, window: Any, log: Callable[[str], None] = lambda s: None) -> None:
        self._w = window
        self._log = log

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
                apply_overlay(ns)
                ns.orderFrontRegardless()
                AppHelper.callLater(0.6, report)

        def report() -> None:
            ns = self._native()
            if ns is not None:
                self._log(
                    f"overlay shown: front={frontmost_full_screen()} "
                    f"level={ns.level()} collection={ns.collectionBehavior()} "
                    f"style={ns.styleMask()} visible={ns.isVisible()} "
                    f"active_space={ns.isOnActiveSpace()} alpha={ns.alphaValue()} "
                    f"occlusion={ns.occlusionState()} frame={tuple(ns.frame().origin)}+"
                    f"{tuple(ns.frame().size)} number={ns.windowNumber()} "
                    f"info={window_info(ns.windowNumber())} stack={window_stack(ns.windowNumber())}"
                )

        AppHelper.callAfter(apply)

    def hide(self) -> None:
        from PyObjCTools import AppHelper

        def apply() -> None:
            ns = self._native()
            if ns is not None:
                ns.orderOut_(None)

        AppHelper.callAfter(apply)


def _frontmost_window() -> tuple[str, Any]:
    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "", None
    el = AXUIElementCreateApplication(app.processIdentifier())
    err, win = AXUIElementCopyAttributeValue(el, "AXFocusedWindow", None)
    return str(app.localizedName()), (win if err == 0 else None)


def frontmost_full_screen() -> tuple[str, bool | None]:
    """(app name, whether its focused window is full screen; None when unknown)."""
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue

        name, win = _frontmost_window()
        if win is None:
            return name, None
        err, full = AXUIElementCopyAttributeValue(win, "AXFullScreen", None)
        return name, (bool(full) if err == 0 else None)
    except Exception:  # noqa: BLE001 - best effort
        return "", None


def leave_full_screen_if_needed() -> bool:
    """If the frontmost window is in full screen, take it out (generic, via AXFullScreen).

    Opening another app from a full-screen Space makes macOS slide to a different Space;
    leaving full screen first keeps everything on the Space the user is looking at.
    """
    try:
        from ApplicationServices import AXUIElementSetAttributeValue

        name, full = frontmost_full_screen()
        if not full:
            return False
        _, win = _frontmost_window()
        return win is not None and AXUIElementSetAttributeValue(win, "AXFullScreen", False) == 0
    except Exception:  # noqa: BLE001 - best effort
        return False


def window_stack(our_number: int, limit: int = 6) -> str:
    """Front-to-back on-screen windows as 'owner@layer', ours marked with '*'.

    Diagnostic for the Spotlight-style overlay: if a full-screen app's window precedes ours,
    the pill is hidden behind it.
    """
    try:
        import Quartz

        infos = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )
        out: list[str] = []
        for w in infos or []:
            if w.get("kCGWindowLayer", 0) < 0 or w.get("kCGWindowOwnerName") == "Window Server":
                continue
            mark = "*" if w.get("kCGWindowNumber") == our_number else ""
            out.append(f"{mark}{w.get('kCGWindowOwnerName', '?')}@{w.get('kCGWindowLayer', 0)}")
            if len(out) >= limit:
                break
        return " > ".join(out)
    except Exception as e:  # noqa: BLE001 - diagnostics only
        return f"unavailable ({e!r})"


def window_report(ns: Any) -> str:
    """Every NSWindow property that can affect Space/full-screen membership (diagnostic)."""
    from AppKit import NSApp

    getters = (
        "styleMask level collectionBehavior isOpaque alphaValue hasShadow ignoresMouseEvents "
        "canHide hidesOnDeactivate isExcludedFromWindowsMenu isMovable isReleasedWhenClosed "
        "animationBehavior sharingType isRestorable tabbingMode isMiniaturized isZoomed "
        "canBecomeKeyWindow canBecomeMainWindow isOnActiveSpace occlusionState isVisible "
        "windowNumber"
    ).split()
    out = []
    for g in getters:
        try:
            out.append(f"{g}={getattr(ns, g)()}")
        except Exception as e:  # noqa: BLE001
            out.append(f"{g}=?{type(e).__name__}")
    out.append(f"parent={ns.parentWindow()} children={len(ns.childWindows() or [])}")
    out.append(f"screen={ns.screen().frame() if ns.screen() else None}")
    out.append(f"delegate={type(ns.delegate()).__name__} class={type(ns).__name__}")
    out.append(
        f"app.policy={NSApp.activationPolicy()} app.hidden={NSApp.isHidden()} "
        f"app.active={NSApp.isActive()}"
    )
    return " ".join(out)


def window_info(number: int) -> str:
    """Window-server view of one window (on-screen flag, alpha, layer, bounds)."""
    try:
        import Quartz

        infos = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID
        )
        for w in infos or []:
            if w.get("kCGWindowNumber") == number:
                b = w.get("kCGWindowBounds", {})
                return (
                    f"onscreen={bool(w.get('kCGWindowIsOnscreen', False))} "
                    f"alpha={w.get('kCGWindowAlpha')} layer={w.get('kCGWindowLayer')} "
                    f"bounds={b.get('X')},{b.get('Y')} {b.get('Width')}x{b.get('Height')}"
                )
        return "not known to the window server"
    except Exception as e:  # noqa: BLE001 - diagnostics only
        return f"unavailable ({e!r})"


CONTROL_NOTE = "co.manali.yapp.control"
_observer_cls: Any = None


def post_control(command: str) -> None:
    """Send 'toggle' / 'escape' to the running Yapp.app (`yapp toggle` from any shell)."""
    from Foundation import NSDistributedNotificationCenter

    NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_userInfo_deliverImmediately_(
        CONTROL_NOTE, command, None, True
    )


def observe_control(handler: Callable[[str], None]) -> Any:
    """Register for `post_control` notifications; keep the returned observer alive."""
    global _observer_cls
    from Foundation import NSDistributedNotificationCenter, NSObject

    if _observer_cls is None:

        class YappControlObserver(NSObject):  # type: ignore[misc]
            handler: Callable[[str], None] | None = None

            def control_(self, note: Any) -> None:
                if self.handler is not None:
                    self.handler(str(note.object()))

        _observer_cls = YappControlObserver
    obs = _observer_cls.alloc().init()
    obs.handler = handler
    NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        obs, "control:", CONTROL_NOTE, None
    )
    return obs


def bring_to_front(app_name: str, timeout: float = 4.0) -> bool:
    """After `open -a`, make sure the app is really in front.

    A background (menu-bar) process asking Launch Services to open an app does not always
    get the activation it asked for on recent macOS; setting the app's AXFrontmost attribute
    through Accessibility does. Polls until the app is running and frontmost.
    """
    import time

    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCreateApplication, AXUIElementSetAttributeValue
    from Foundation import NSDate, NSRunLoop, NSThread

    deadline = time.monotonic() + timeout
    ws = NSWorkspace.sharedWorkspace()
    while time.monotonic() < deadline:
        if NSThread.isMainThread():
            NSRunLoop.mainRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
        front = ws.frontmostApplication()
        if front is not None and (front.localizedName() or "").lower() == app_name.lower():
            return True
        for app in ws.runningApplications():
            if (app.localizedName() or "").lower() == app_name.lower():
                el = AXUIElementCreateApplication(app.processIdentifier())
                AXUIElementSetAttributeValue(el, "AXFrontmost", True)
                app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps
                break
        time.sleep(0.15)
    front = ws.frontmostApplication()
    return front is not None and (front.localizedName() or "").lower() == app_name.lower()


def _running_app(app_name: str) -> Any:
    from AppKit import NSWorkspace

    from yapp.ax import refresh_workspace

    refresh_workspace()  # NSWorkspace only learns about launches and quits from the run loop
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if (app.localizedName() or "").lower() == app_name.lower():
            return app
    return None


def app_is_running(app_name: str) -> bool:
    app = _running_app(app_name)
    return app is not None and not app.isTerminated()


def quit_app(app_name: str, timeout: float = 6.0) -> bool:
    """Ask the app to quit the polite way and wait for it to go. A Save sheet keeps it alive,
    which is the right outcome: pressing Don't Save is the guard's decision, not ours."""
    import time

    app = _running_app(app_name)
    if app is None:
        return True
    if not app.terminate():
        return False
    from yapp.ax import refresh_workspace

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        refresh_workspace()  # isTerminated only updates when the main run loop spins
        if app.isTerminated():
            return True
        time.sleep(0.1)
    refresh_workspace()
    return bool(app.isTerminated())
