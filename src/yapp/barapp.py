"""The menu-bar app: pill + permissions windows, global hotkeys, status item, session thread."""

from __future__ import annotations

import subprocess
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any

import webview
from pynput import keyboard
from rich.console import Console

from yapp import permissions as perms
from yapp.audio import Recorder
from yapp.bar import BRIDGE_JS, Bar, Events, pill_size
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.display import Display, Terminal
from yapp.menubar import install_status_item
from yapp.permwindow import PermWindow, handle_event, poll_loop
from yapp.runner import build_runner
from yapp.session import Session
from yapp.state import AppState
from yapp.stt import StreamingTranscriber
from yapp.types import Decision, Result, Verdict

UI = resources.files("yapp.ui")


class Tee:
    """Fan every Display call out to several displays (bar + log file + terminal)."""

    def __init__(self, *ds: Display) -> None:
        self.ds = ds

    def status(self, msg: str) -> None:
        for d in self.ds:
            d.status(msg)

    def listening(self, level: float) -> None:
        for d in self.ds:
            d.listening(level)

    def thinking(self) -> None:
        for d in self.ds:
            d.thinking()

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        for d in self.ds:
            d.show_transcript(committed, pending)

    def show_decision(self, d_: Decision) -> None:
        for d in self.ds:
            d.show_decision(d_)

    def show_verdict(self, v: Verdict) -> None:
        for d in self.ds:
            d.show_verdict(v)

    def show_result(self, r: Result) -> None:
        for d in self.ds:
            d.show_result(r)

    def show_error(self, msg: str) -> None:
        for d in self.ds:
            d.show_error(msg)


def screen_under_mouse() -> tuple[int, int, int, int]:
    """(width, height, x, y) of the screen holding the cursor, in pywebview's top-left space."""
    from AppKit import NSEvent, NSScreen

    p = NSEvent.mouseLocation()
    screens = NSScreen.screens()
    main_h = screens[0].frame().size.height
    for s in screens:
        f = s.frame()
        inside_x = f.origin.x <= p.x <= f.origin.x + f.size.width
        inside_y = f.origin.y <= p.y <= f.origin.y + f.size.height
        if inside_x and inside_y:
            top = int(main_h - (f.origin.y + f.size.height))
            return int(f.size.width), int(f.size.height), int(f.origin.x), top
    f = screens[0].frame()
    return int(f.size.width), int(f.size.height), 0, 0


def _ui_path(name: str) -> Path:
    return Path(str(UI.joinpath(name)))


def run_app(cfg: Config, log: bool = False) -> int:
    width, height = pill_size(UI.joinpath("tokens.css").read_text())
    pending: list[tuple[str, dict[str, Any]]] = []
    router: dict[str, Any] = {}  # filled once the session thread has built everything

    def on_event(name: str, detail: dict[str, Any]) -> None:
        if "handle" in router:
            router["handle"](name, detail)
        else:
            pending.append((name, detail))

    bar_window = webview.create_window(
        "Yapp",
        url=f"file://{_ui_path('window.html')}?embed",
        width=width,
        height=height,
        frameless=True,
        transparent=True,
        on_top=True,
        resizable=False,
        shadow=False,
        easy_drag=False,
        hidden=True,
        focus=False,
        js_api=Events(on_event),
    )
    perm_window = webview.create_window(
        "Yapp – Permissions",
        url=f"file://{_ui_path('permissions.html')}?embed",
        width=460,
        height=560,
        resizable=False,
        hidden=True,
        js_api=Events(on_event),
    )
    if bar_window is None or perm_window is None:
        raise RuntimeError("pywebview could not create the windows")
    for w in (bar_window, perm_window):
        w.events.loaded += lambda w=w: w.evaluate_js(BRIDGE_JS)

    bar = Bar(bar_window, width, height)
    bardisplay = BarDisplay(bar, silence_total=cfg.silence_seconds)
    permwin = PermWindow(perm_window)

    log_path = Path.home() / ".yapp" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_log = Terminal(Console(file=log_path.open("a"), width=120, force_terminal=False))
    file_log.status(f"--- yapp app started {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    terminal = Terminal() if log else None
    displays: list[Display] = [bardisplay, file_log]
    if terminal is not None:
        displays.append(terminal)
    display: Display = Tee(*displays)

    def session_main() -> None:
        display.status(f"loading whisper {cfg.whisper_model} …")
        stt = StreamingTranscriber(cfg.whisper_model)
        runner = build_runner(cfg, display)
        rec = Recorder(cfg.sample_rate, cfg.max_hold_seconds)
        rec.start()
        state = AppState(Path.home() / ".yapp" / "state.json")
        session = Session(
            cfg, runner, rec, stt, bar, bardisplay, screen=screen_under_mouse, state=state
        )
        hot: list[Any] = [None]

        def start_hotkeys() -> None:
            hot[0] = keyboard.GlobalHotKeys(
                {cfg.hotkey_combo: session.toggle, "<esc>": session.escape}
            )
            hot[0].start()

        def stop_hotkeys() -> None:
            if hot[0] is not None:
                hot[0].stop()
                hot[0] = None

        start_hotkeys()

        def show_log() -> None:
            subprocess.run(["open", str(log_path)], check=False)

        def quit_app() -> None:
            stop.set()
            session.quit()
            perm_window.destroy()
            bar_window.destroy()

        status = install_status_item(
            on_listen=session.toggle,
            on_pause=lambda paused: stop_hotkeys() if paused else start_hotkeys(),
            on_show_log=show_log,
            on_permissions=permwin.show,
            on_quit=quit_app,
            glyphs={
                "default": str(_ui_path("menubar-glyph.svg")),
                "listening": str(_ui_path("menubar-glyph-listening.svg")),
                "paused": str(_ui_path("menubar-glyph-paused.svg")),
                "attention": str(_ui_path("menubar-glyph-attention.svg")),
            },
        )

        def on_grants(p: perms.Permissions) -> None:
            display.status(f"permissions: {p.as_dict()}")
            permwin.set(p)
            bar.permissions(p)
            if p.missing and not session.running:
                status.set_variant("attention")
                if not permwin.visible:
                    permwin.show()
            elif status.variant == "attention":
                status.set_variant("default")

        watcher = perms.Watcher(on_change=on_grants)
        stop = threading.Event()
        threading.Thread(
            target=poll_loop, args=(watcher, stop, 2.0), name="yapp-permissions", daemon=True
        ).start()

        def handle(name: str, detail: dict[str, Any]) -> None:
            what = handle_event(
                name,
                detail,
                show_log=show_log,
                on_later=permwin.hide,
                on_complete=lambda: threading.Timer(1.5, permwin.hide).start(),
                on_escape=session.escape,
            )
            display.status(f"page event {name} {detail} -> {what}")

        router["handle"] = handle
        for item in pending:
            handle(*item)
        pending.clear()

        display.status(f"ready · press {cfg.hotkey_combo} to talk")
        while not stop.is_set():
            session.run_forever_once()
            status.set_variant(
                "default" if not watcher.current or not watcher.current.missing else "attention"
            )
        rec.stop()

    webview.start(session_main)
    return 0
