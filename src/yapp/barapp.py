"""The menu-bar app: pywebview window + global hotkeys + status item + session thread."""

from __future__ import annotations

import time
from importlib import resources
from pathlib import Path

import webview
from pynput import keyboard
from rich.console import Console

from yapp.audio import Recorder
from yapp.bar import Bar
from yapp.bardisplay import BarDisplay
from yapp.config import Config
from yapp.display import Display, Terminal
from yapp.menubar import install_status_item
from yapp.runner import build_runner
from yapp.session import Session
from yapp.stt import StreamingTranscriber
from yapp.types import Decision, Result, Verdict


class Tee:
    """Fan every Display call out to several displays (bar + terminal log)."""

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


def run_app(cfg: Config, log: bool = False) -> int:
    ui = Path(str(resources.files("yapp.ui").joinpath("window.html")))
    window = webview.create_window(
        "Yapp",
        url=f"file://{ui}?embed",
        width=360,
        height=120,
        frameless=True,
        transparent=True,
        on_top=True,
        resizable=False,
        shadow=False,
        easy_drag=False,
        hidden=True,
        focus=False,
    )
    if window is None:
        raise RuntimeError("pywebview could not create the window")
    bar = Bar(window)
    bardisplay = BarDisplay(bar)
    # Always keep a developer log on disk: the bundle has no stdout.
    log_path = Path.home() / ".yapp" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_console = Console(file=log_path.open("a"), width=120, force_terminal=False)
    file_log = Terminal(file_console)
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
        session = Session(cfg, runner, rec, stt, bar, bardisplay, screen=screen_under_mouse)
        hot = keyboard.GlobalHotKeys({cfg.hotkey_combo: session.toggle, "<esc>": session.escape})
        hot.start()

        def pause(paused: bool) -> None:
            nonlocal hot
            if paused:
                hot.stop()
            else:
                hot = keyboard.GlobalHotKeys(
                    {cfg.hotkey_combo: session.toggle, "<esc>": session.escape}
                )
                hot.start()

        def quit_app() -> None:
            session.quit()
            window.destroy()

        install_status_item(
            on_listen=session.toggle,
            on_pause=pause,
            on_quit=quit_app,
            icon_path=str(resources.files("yapp.ui").joinpath("icon-1024.png")),
        )
        display.status(f"ready · press {cfg.hotkey_combo} to talk")
        session.run_forever()
        rec.stop()

    webview.start(session_main)
    return 0
