"""CLI entry: `yapp` (menu-bar app), `dev` (terminal hold loop), --once, eval, keys, install-app."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from yapp.config import Config
from yapp.display import Terminal
from yapp.guard import Mode
from yapp.jev import JevError
from yapp.runner import build_runner


def run_enroll(cfg: Config, display: Terminal) -> int:
    """Terminal enrolment (needs the mic for this terminal; the menu bar item is easier)."""
    from yapp.audio import Recorder
    from yapp.speaker import Verifier

    rec = Recorder(cfg.sample_rate, 15)
    rec.start()
    rec.arm()
    display.status("read anything aloud for ten seconds …")
    for i in range(10, 0, -1):
        display.status(f"{i} …")
        time.sleep(1.0)
    samples = rec.snapshot()
    rec.stop()
    try:
        lo, mean = Verifier(threshold=cfg.voice_match).enroll(samples)
    except ValueError as e:
        display.show_error(str(e))
        return 1
    display.status(f"voice enrolled · self-similarity min {lo:.2f} mean {mean:.2f}")
    return 0


def run_once(
    text: str,
    cfg: Config,
    display: Terminal,
    per_tick: int = 2,
    *,
    mode: Mode = Mode.ASK,
    approve: bool = False,
    placement: str | None = None,
) -> int:
    def ask(action: str) -> bool:
        display.status(f"ASK: may I {action}? → {'yes (--approve)' if approve else 'no'}")
        return approve

    runner = build_runner(cfg, display, ask=ask, mode=mode, force_placement=placement)
    words = text.replace("+", " ").split()
    for i in range(per_tick, len(words) + per_tick, per_tick):
        runner.tick(words[:i], words[i : i + 1])
        time.sleep(cfg.tick_seconds)
    runner.finish()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yapp")
    p.add_argument("--once", metavar="TEXT", help="run the pipeline on typed words, no audio")
    p.add_argument("--per-tick", type=int, default=2, help="words per tick in --once mode")
    p.add_argument("--mode", choices=["ask", "auto"], default="ask", help="permission mode")
    p.add_argument("--approve", action="store_true", help="answer yes to every ask (--once)")
    p.add_argument("--placement", choices=["parallel", "hand_over"], default=None)
    sub = p.add_subparsers(dest="command")
    app = sub.add_parser("app", help="menu-bar app with the ⌥ Space bar (default)")
    app.add_argument("--log", action="store_true", help="also print the developer view")
    sub.add_parser("dev", help="terminal hold-to-talk loop")
    sub.add_parser("eval", help="accuracy per confidence bucket on tests/eval")
    sub.add_parser("keys", help="print what the hotkey listener sees")
    sub.add_parser("install-app", help="write ~/Applications/Yapp.app")
    sub.add_parser("enroll", help="record 10 s of your voice for spoken approvals")
    disc = sub.add_parser("discard", help="test helper: close an app's windows, dropping changes")
    disc.add_argument("app")
    tasks = sub.add_parser("tasks", help="run the task suite in tasks/ on this Mac")
    tasks.add_argument("--only", default="", help="substring of task names to run")
    tasks.add_argument("--dir", default="tasks", help="folder of task YAML files")
    tasks.add_argument("--mode", choices=["ask", "auto"], default=argparse.SUPPRESS)
    tasks.add_argument("--approve", action="store_true", default=argparse.SUPPRESS)
    sub.add_parser("toggle", help="show/hide the bar of the running Yapp.app")
    sub.add_parser("escape", help="dismiss the bar of the running Yapp.app")
    ax = sub.add_parser("ax", help="spike: read an app's UI via Accessibility and let Jev pick")
    ax.add_argument("--app", default=None, help="running app name; default frontmost")
    ax.add_argument("--phrases", default="new tab|find on page|zoom in|search for fable five")
    ax.add_argument("--out", default=str(Path.home() / ".yapp" / "ax.log"))
    ax.add_argument("--dump", action="store_true", help="write the app's on-screen text instead")
    ax.add_argument("--windows", action="store_true", help="write the app's windows and sheets")
    p.set_defaults(command="app", log=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config()
    display = Terminal()
    try:
        if args.once:
            return run_once(
                args.once,
                cfg,
                display,
                per_tick=args.per_tick,
                mode=Mode(args.mode),
                approve=args.approve,
                placement=args.placement,
            )
        if args.command == "enroll":
            return run_enroll(cfg, display)
        if args.command == "discard":
            from yapp.tasks import discard_app

            for note in discard_app(args.app):
                display.status(note)
            return 0
        if args.command == "tasks":
            from yapp.tasks import run_tasks

            return run_tasks(
                cfg,
                display,
                directory=Path(args.dir),
                only=args.only,
                mode=Mode(args.mode),
                approve=args.approve,
            )
        if args.command == "dev":
            from yapp.live import run_live

            return run_live(cfg, display)
        if args.command == "eval":
            from yapp.evaluate import run_eval

            return run_eval(cfg, display)
        if args.command == "keys":
            from yapp.audio import debug_keys

            return debug_keys(display, seconds=10)
        if args.command == "ax" and args.windows:
            from yapp.windows import describe_windows

            Path(args.out).write_text(describe_windows(args.app or ""))
            return 0
        if args.command == "ax" and args.dump:
            from yapp.tasks import screen_text

            Path(args.out).write_text(screen_text(args.app or ""))
            return 0
        if args.command == "ax":
            from yapp.ax import run_ax

            phrases = args.phrases.replace("+", " ").split("|")
            return run_ax(args.app, phrases, cfg.model, args.out)
        if args.command in ("toggle", "escape"):
            from yapp.native import post_control

            post_control(args.command)
            return 0
        if args.command == "install-app":
            from yapp.bundle import install_app

            return install_app(cfg, display)
        from yapp.barapp import run_app

        return run_app(cfg, log=args.log)
    except JevError as e:
        display.show_error(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
