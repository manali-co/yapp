"""CLI entry: `yapp` (menu-bar app), `dev` (terminal hold loop), --once, eval, keys, install-app."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from yapp.config import Config
from yapp.display import Terminal
from yapp.jev import JevError
from yapp.runner import build_runner


def run_once(text: str, cfg: Config, display: Terminal, per_tick: int = 2) -> int:
    runner = build_runner(cfg, display)
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
    sub = p.add_subparsers(dest="command")
    app = sub.add_parser("app", help="menu-bar app with the ⌥ Space bar (default)")
    app.add_argument("--log", action="store_true", help="also print the developer view")
    sub.add_parser("dev", help="terminal hold-to-talk loop")
    sub.add_parser("eval", help="accuracy per confidence bucket on tests/eval")
    sub.add_parser("keys", help="print what the hotkey listener sees")
    sub.add_parser("install-app", help="write ~/Applications/Yapp.app")
    sub.add_parser("toggle", help="show/hide the bar of the running Yapp.app")
    sub.add_parser("escape", help="dismiss the bar of the running Yapp.app")
    ax = sub.add_parser("ax", help="spike: read an app's UI via Accessibility and let Jev pick")
    ax.add_argument("--app", default=None, help="running app name; default frontmost")
    ax.add_argument("--phrases", default="new tab|find on page|zoom in|search for fable five")
    ax.add_argument("--out", default=str(Path.home() / ".yapp" / "ax.log"))
    p.set_defaults(command="app", log=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config()
    display = Terminal()
    try:
        if args.once:
            return run_once(args.once, cfg, display, per_tick=args.per_tick)
        if args.command == "dev":
            from yapp.live import run_live

            return run_live(cfg, display)
        if args.command == "eval":
            from yapp.evaluate import run_eval

            return run_eval(cfg, display)
        if args.command == "keys":
            from yapp.audio import debug_keys

            return debug_keys(display, seconds=10)
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
