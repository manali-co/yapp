"""Permission flow: page event routing and the 2 s poll loop (the row lives in the bar)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from yapp.permissions import Watcher, open_settings

PERMS = ("mic", "input", "accessibility")


def handle_event(
    name: str,
    detail: dict[str, Any],
    *,
    open_settings_fn: Callable[[str], None] = open_settings,
    show_log: Callable[[], None] = lambda: None,
    on_later: Callable[[], None] = lambda: None,
    on_complete: Callable[[], None] = lambda: None,
    on_escape: Callable[[], None] = lambda: None,
) -> str:
    """Route one page event. Returns what was done, for logs and tests."""
    if name == "open-settings" and detail.get("permission") in PERMS:
        open_settings_fn(str(detail["permission"]))
        return f"settings:{detail['permission']}"
    if name == "action":
        if detail.get("id") in ("permissions", "fix") and detail.get("permission") in PERMS:
            open_settings_fn(str(detail["permission"]))
            return f"settings:{detail['permission']}"
        if detail.get("id") in ("log", "show_log"):
            show_log()
            return "show_log"
        return "ignored"
    if name == "later":
        on_later()
        return "later"
    if name == "permissions-complete":
        on_complete()
        return "complete"
    if name == "escape":
        on_escape()
        return "escape"
    return "ignored"


def poll_loop(
    watcher: Watcher,
    stop: threading.Event,
    interval: float = 2.0,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Poll the grants until `stop` is set. Returns the number of polls made."""
    import time

    do_sleep = sleep or time.sleep
    n = 0
    while not stop.is_set():
        watcher.poll()
        n += 1
        do_sleep(interval)
    return n
