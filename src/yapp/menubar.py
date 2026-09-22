"""Menu-bar status item (PyObjC). Must be installed on the main thread; use install_status_item."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_keep: list[Any] = []  # strong refs: the status item and its target must outlive this call


def install_status_item(
    *,
    on_listen: Callable[[], None],
    on_pause: Callable[[bool], None],
    on_quit: Callable[[], None],
    icon_path: str,
) -> None:
    from PyObjCTools import AppHelper

    def build() -> None:
        import objc
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
                on_pause(self.paused)

            def quit_(self, sender: Any) -> None:
                on_quit()

        target = Target.alloc().init()
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        image = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if image is not None:
            image.setSize_(NSSize(18, 18))
            item.button().setImage_(image)
        else:
            item.button().setTitle_("yapp")
        menu = NSMenu.alloc().init()
        for title, sel in [("Listen  (⌥ Space)", "listen:"), ("Pause hotkey", "pause:")]:
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            mi.setTarget_(target)
            menu.addItem_(mi)
        menu.addItem_(NSMenuItem.separatorItem())
        q = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Yapp", "quit:", "q")
        q.setTarget_(target)
        menu.addItem_(q)
        item.setMenu_(menu)
        _keep.extend([target, item, menu, objc])

    AppHelper.callAfter(build)
