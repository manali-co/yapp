import threading

from yapp.permissions import Grant, Permissions, Watcher
from yapp.permwindow import PermWindow, handle_event, poll_loop


class FakeWindow:
    def __init__(self) -> None:
        self.js: list[str] = []
        self.shown = False

    def evaluate_js(self, js: str) -> object:
        self.js.append(js)
        return None

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.shown = False

    def move(self, x: int, y: int) -> None:
        return None


def test_set_sends_booleans() -> None:
    w = FakeWindow()
    pw = PermWindow(w)
    pw.set(Permissions(Grant.GRANTED, Grant.MISSING, Grant.UNKNOWN))
    assert w.js[0].endswith('set({"mic": true, "input": false, "accessibility": null})')
    pw.show()
    assert w.shown and pw.visible


def test_handle_event_routes() -> None:
    opened: list[str] = []
    calls: list[str] = []

    def route(name: str, detail: dict[str, object]) -> str:
        return handle_event(
            name,
            detail,
            open_settings_fn=opened.append,
            show_log=lambda: calls.append("log"),
            on_later=lambda: calls.append("later"),
            on_complete=lambda: calls.append("complete"),
            on_escape=lambda: calls.append("escape"),
        )

    assert route("open-settings", {"permission": "accessibility"}) == "settings:accessibility"
    assert route("action", {"id": "fix", "permission": "mic"}) == "settings:mic"
    assert route("action", {"id": "show_log"}) == "show_log"
    assert route("later", {}) == "later"
    assert route("permissions-complete", {}) == "complete"
    assert route("escape", {}) == "escape"
    assert route("action", {"id": "evil", "permission": "../x"}) == "ignored"
    assert route("open-settings", {"permission": "root"}) == "ignored"
    assert opened == ["accessibility", "mic"]
    assert calls == ["log", "later", "complete", "escape"]


def test_poll_loop_polls_until_stopped() -> None:
    seen: list[Permissions] = []
    watcher = Watcher(
        probe=lambda: Permissions(Grant.GRANTED, Grant.GRANTED, Grant.GRANTED),
        on_change=seen.append,
    )
    stop = threading.Event()
    calls = {"n": 0}

    def fake_sleep(s: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()

    assert poll_loop(watcher, stop, interval=2.0, sleep=fake_sleep) == 3
    assert len(seen) == 1  # unchanged grants report once
