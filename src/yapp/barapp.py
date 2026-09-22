"""The menu-bar app: pill + permissions windows, global hotkeys, status item, session thread."""

from __future__ import annotations

import subprocess
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any

import webview
from rich.console import Console

from yapp import permissions as perms
from yapp.audio import Hotkeys, Recorder
from yapp.bar import BRIDGE_JS, Bar, Events, pill_size
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.display import Display, Terminal
from yapp.menubar import install_status_item
from yapp.native import INJECT_CSS_JS, MARGIN, OverlayWindow, accessory_app, make_transparent
from yapp.permwindow import handle_event, poll_loop
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
    pill_w, pill_h = pill_size(UI.joinpath("tokens.css").read_text())
    width, height = pill_w + 2 * MARGIN, pill_h + 2 * MARGIN
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
    if bar_window is None:
        raise RuntimeError("pywebview could not create the window")
    bar_window.events.loaded += lambda: bar_window.evaluate_js(BRIDGE_JS)
    bar_window.events.loaded += lambda: bar_window.evaluate_js(INJECT_CSS_JS)
    bar_window.events.loaded += lambda: make_transparent(bar_window)

    bar = Bar(OverlayWindow(bar_window), width, height)
    bardisplay = BarDisplay(bar, silence_total=cfg.silence_seconds)

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
        accessory_app()
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
        showing_for_perms = [False]

        def toggle() -> None:
            display.status("hotkey: toggle")
            if showing_for_perms[0] and not session.running:
                showing_for_perms[0] = False
            session.toggle()

        def escape() -> None:
            display.status("hotkey: escape")
            session.escape()
            hide_permission_row()

        def start_hotkeys() -> None:
            try:
                hot[0] = Hotkeys(on_toggle=toggle, on_escape=escape)
                hot[0].start()
                time.sleep(0.5)
                display.status(f"hotkey listener alive: {hot[0].is_alive()} ({cfg.hotkey_combo})")
            except Exception as e:  # noqa: BLE001 - surface listener failures in the log
                display.show_error(f"hotkey listener failed: {e!r}")

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
            bar_window.destroy()

        def show_permission_row() -> None:
            """Bring the bar up in its blocked state so the Fix link is reachable."""
            if session.running:
                return
            p = watcher.current
            if p is None:
                return
            bar.show_at_top(*screen_under_mouse())
            bar.set_state("listening" if "accessibility" in p.missing else "idle")
            bar.permissions(p)
            showing_for_perms[0] = True

        def hide_permission_row() -> None:
            if showing_for_perms[0] and not session.running:
                bar.hide()
                showing_for_perms[0] = False

        status = install_status_item(
            on_listen=toggle,
            on_pause=lambda paused: stop_hotkeys() if paused else start_hotkeys(),
            on_show_log=show_log,
            on_permissions=lambda: show_permission_row(),
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
            bar.permissions(p)
            if p.missing:
                status.set_variant("attention")
                # Without the mic or Input Monitoring the user can't even summon the bar,
                # so bring it up with the Fix link; Accessibility shows inside a session.
                if ("mic" in p.missing or "input" in p.missing) and not session.running:
                    show_permission_row()
            else:
                if status.variant == "attention":
                    status.set_variant("default")
                threading.Timer(1.5, hide_permission_row).start()

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
                on_later=hide_permission_row,
                on_complete=hide_permission_row,
                on_escape=escape,
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
