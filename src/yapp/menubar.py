"""Menu-bar status item (PyObjC): a template glyph with four variants and the app menu."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_keep: list[Any] = []  # strong refs: the status item and its target must outlive this call

VARIANTS = ("default", "listening", "paused", "attention")


class StatusHandle:
    """Thread-safe handle: set_variant() may be called from any thread."""

    def __init__(self) -> None:
        self._item: Any = None
        self._images: dict[str, Any] = {}
        self.variant = "default"

    def set_variant(self, name: str) -> None:
        if name not in VARIANTS:
            return
        self.variant = name
        from PyObjCTools import AppHelper

        def apply() -> None:
            if self._item is not None and name in self._images:
                self._item.button().setImage_(self._images[name])

        AppHelper.callAfter(apply)


def install_status_item(
    *,
    on_listen: Callable[[], None],
    on_pause: Callable[[bool], None],
    on_show_log: Callable[[], None],
    on_permissions: Callable[[], None],
    on_quit: Callable[[], None],
    glyphs: dict[str, str],
) -> StatusHandle:
    """glyphs maps a variant name to an SVG path. Builds on the main thread via callAfter."""
    from PyObjCTools import AppHelper

    handle = StatusHandle()

    def build() -> None:
        from AppKit import (
            NSImage,
            NSMenu,
            NSMenuItem,
            NSSize,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
        from Foundation import NSObject

        class Target(NSObject):  # type: ignore[misc]
            paused = False

            def listen_(self, sender: Any) -> None:
                on_listen()

            def pause_(self, sender: Any) -> None:
                self.paused = not self.paused
                sender.setState_(1 if self.paused else 0)
                handle.set_variant("paused" if self.paused else "default")
                on_pause(self.paused)

            def showLog_(self, sender: Any) -> None:
                on_show_log()

            def permissions_(self, sender: Any) -> None:
                on_permissions()

            def quit_(self, sender: Any) -> None:
                on_quit()

        target = Target.alloc().init()
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        for name, path in glyphs.items():
            image = NSImage.alloc().initWithContentsOfFile_(path)
            if image is not None:
                image.setSize_(NSSize(18, 18))
                image.setTemplate_(True)
                handle._images[name] = image
        if "default" in handle._images:
            item.button().setImage_(handle._images["default"])
        else:
            item.button().setTitle_("yapp")
        menu = NSMenu.alloc().init()
        entries = [
            ("Listen  (⌥ Space)", "listen:", ""),
            ("Pause hotkey", "pause:", ""),
            (None, None, None),
            ("Show log", "showLog:", ""),
            ("Permissions…", "permissions:", ""),
            (None, None, None),
            ("Quit Yapp", "quit:", "q"),
        ]
        for title, sel, key in entries:
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
            mi.setTarget_(target)
            menu.addItem_(mi)
        item.setMenu_(menu)
        handle._item = item
        _keep.extend([target, item, menu])

    AppHelper.callAfter(build)
    return handle
