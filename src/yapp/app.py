"""CLI entry: live loop, --once scripted words, eval."""

from __future__ import annotations

import argparse
import sys
import time

from yapp.config import Config
from yapp.display import Display
from yapp.jev import JevError
from yapp.runner import build_runner


def run_once(text: str, cfg: Config, display: Display | None, per_tick: int = 2) -> int:
    runner = build_runner(cfg, display)
    words = text.split()
    for i in range(per_tick, len(words) + per_tick, per_tick):
        runner.tick(words[:i], words[i : i + 1])
        time.sleep(cfg.tick_seconds)
    runner.finish()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="yapp")
    p.add_argument("command", nargs="?", choices=["live", "eval", "keys"], default="live")
    p.add_argument("--once", metavar="TEXT", help="run the pipeline on typed words, no audio")
    p.add_argument("--per-tick", type=int, default=2, help="words per tick in --once mode")
    p.add_argument("--headless", action="store_true", help="no window (default until UI ships)")
    args = p.parse_args(argv)
    cfg = Config()
    display = Display()
    try:
        if args.once:
            return run_once(args.once, cfg, display, per_tick=args.per_tick)
        if args.command == "keys":
            from yapp.audio import debug_keys

            return debug_keys(display, seconds=10)
        if args.command == "eval":
            from yapp.evaluate import run_eval

            return run_eval(cfg, display)
        from yapp.live import run_live

        return run_live(cfg, display)
    except JevError as e:
        display.show_error(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
