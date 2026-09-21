"""Stub until Task 13: hold-to-talk live loop."""

from __future__ import annotations

from yapp.config import Config
from yapp.display import Display


def run_live(cfg: Config, display: Display) -> int:
    display.status("live: not built yet")
    return 1
