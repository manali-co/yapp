"""`yapp tasks`: the house benchmark. Real apps on this Mac, scripted checks, one table.

A task is a YAML file: an instruction spoken the way a person would, optional setup and
teardown shell commands, checks against the live screen or the file system, and whether the
permission guard is expected to ask. Runs through the Yapp bundle so Accessibility works.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rich.table import Table
from typesafe_sdk import Question

from yapp.config import Config
from yapp.display import Terminal
from yapp.guard import Mode
from yapp.jev import Jev, JevLike, JevResponse
from yapp.native import bring_to_front, quit_app
from yapp.runner import build_runner

DEFAULT_DIR = Path("tasks")
RESULTS = Path.home() / ".yapp" / "tasks.jsonl"


@dataclass(frozen=True)
class Task:
    name: str
    instruction: str
    checks: list[dict[str, Any]]
    setup: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)
    expect_ask: bool = False
    settle_seconds: float = 2.0
    per_tick: int = 2
    placement: str | None = None  # force "parallel" / "hand_over" instead of asking Jev
    activate_before: list[str] = field(default_factory=list)  # the "user's app", raised via AX
    quit_before: list[str] = field(default_factory=list)  # apps quit politely before the run
    quit_after: list[str] = field(default_factory=list)  # ... and after (never pkill: it makes
    # macOS show a "quit unexpectedly" alert on the next launch, which breaks the next task)
    discard_after: list[str] = field(default_factory=list)  # close windows, drop unsaved changes


@dataclass
class Outcome:
    name: str
    passed: bool
    checks: list[tuple[str, bool, str]]
    asked: list[str]
    expect_ask: bool
    seconds: float
    jev_calls: int
    jev_ms: int
    acted: list[str]

    @property
    def ask_ok(self) -> bool:
        return bool(self.asked) == self.expect_ask

    def row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pass": self.passed,
            "checks": [{"check": c, "ok": ok, "detail": d} for c, ok, d in self.checks],
            "asked": self.asked,
            "expect_ask": self.expect_ask,
            "ask_ok": self.ask_ok,
            "seconds": round(self.seconds, 1),
            "jev_calls": self.jev_calls,
            "jev_ms": self.jev_ms,
            "acted": self.acted,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def load_tasks(directory: Path, only: str = "") -> list[Task]:
    out: list[Task] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        name = str(data.get("name") or path.stem)
        if only and only not in name:
            continue
        checks = data.get("check") or []
        if isinstance(checks, dict):
            checks = [checks]
        out.append(
            Task(
                name=name,
                instruction=str(data["instruction"]),
                checks=[dict(c) for c in checks],
                setup=[str(s) for s in data.get("setup") or []],
                teardown=[str(s) for s in data.get("teardown") or []],
                expect_ask=bool(data.get("expect_ask", False)),
                settle_seconds=float(data.get("settle_seconds", 2.0)),
                per_tick=int(data.get("per_tick", 2)),
                placement=data.get("placement"),
                quit_before=[str(a) for a in data.get("quit_before") or []],
                activate_before=[str(a) for a in data.get("activate_before") or []],
                quit_after=[str(a) for a in data.get("quit_after") or []],
                discard_after=[str(a) for a in data.get("discard_after") or []],
            )
        )
    return out


# ---------------------------------------------------------------- live probes


def _shell(cmd: str) -> str:
    """Run one task command. It is an argv line (shlex rules), not a shell: no pipes or &&."""
    argv = shlex.split(cmd)
    if not argv:
        return ""
    r = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    return (r.stdout or "") + (r.stderr or "")


def frontmost() -> str:
    from yapp.ax import frontmost_app_name

    return frontmost_app_name()


def window_title(app: str = "") -> str:
    from yapp.ax import _attr, app_element, normalize_label

    el, _ = app_element(app or None)
    win = _attr(el, "AXFocusedWindow")
    return normalize_label(str(_attr(win, "AXTitle") or "")) if win is not None else ""


def screen_text(app: str = "", max_nodes: int = 6000, max_seconds: float = 1.5) -> str:
    """Every title, description and value in the app's accessibility tree (checker only;
    deeper and slower than the perceiver's walk, so it can see text in rows and fields)."""
    from yapp.ax import _attr, app_element

    el, _ = app_element(app or None)
    parts: list[str] = []
    stack = [el]
    seen = 0
    deadline = time.monotonic() + max_seconds
    while stack and seen < max_nodes and time.monotonic() < deadline:
        node = stack.pop()
        seen += 1
        for attr in ("AXTitle", "AXDescription", "AXValue"):
            v = _attr(node, attr)
            if isinstance(v, str) and v:
                parts.append(v)
        children = _attr(node, "AXChildren") or []
        stack.extend(reversed(list(children)))
    return "\n".join(parts)


def discard_app(app_name: str) -> list[str]:
    """Harness only: close every window of the app, discarding unsaved changes, then quit."""
    from yapp import windows as win
    from yapp.native import app_is_running

    if not app_is_running(app_name):
        return []
    notes = ["dismissed alert" for w in win.app_windows(app_name) if win.dismiss_alert(w)]
    time.sleep(0.4)
    notes += [win.close_and_discard(w) for w in win.app_windows(app_name)]
    notes.append("quit" if quit_app(app_name) else "still running (a sheet is open?)")
    return notes


def trash_count() -> int:
    try:
        return len(os.listdir(Path.home() / ".Trash"))
    except OSError:
        return -1


def run_check(check: dict[str, Any], before: dict[str, Any]) -> tuple[bool, str]:
    """One YAML check → (ok, detail). Comparisons are case-insensitive substrings."""
    (kind, arg), *_ = check.items()
    app = str(check.get("app", ""))
    if kind == "frontmost":
        got = frontmost()
        return got.lower() == str(arg).lower(), f"frontmost={got}"
    if kind in ("window_in_left_half", "window_in_right_half"):
        from yapp import windows as win

        w = win.focused_window(str(arg))
        frame = win.window_frame(w) if w is not None else None
        if frame is None:
            return False, f"no window for {arg}"
        home = win.display_of(frame, win.displays()).frame
        half = home.left_half() if kind == "window_in_left_half" else home.right_half()
        return half.contains_centre(frame) and frame.w <= half.w + 2, f"{arg} at {frame}"
    if kind == "highlight_around":
        import os

        import Quartz

        from yapp import windows as win

        w = win.focused_window(str(arg))
        frame = win.window_frame(w) if w is not None else None
        if frame is None:
            return False, f"no window for {arg}"
        mine = os.getpid()
        for info in (
            Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0) or []
        ):
            if info.get("kCGWindowOwnerPID") != mine:
                continue
            b = info.get("kCGWindowBounds", {})
            glow = win.Rect(b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0))
            if glow.x <= frame.x and glow.y <= frame.y and glow.w >= frame.w and glow.h >= frame.h:
                return True, f"glow {glow} around {arg} {frame}"
        return False, f"no glow window of ours around {arg} {frame}"
    if kind == "app_not_running":
        from yapp.native import app_is_running

        running = app_is_running(str(arg))
        return not running, f"{arg} running={running}"
    if kind == "not_frontmost":
        got = frontmost()
        return got.lower() != str(arg).lower(), f"frontmost={got}"
    if kind == "window_title_contains":
        got = window_title(app)
        return str(arg).lower() in got.lower(), f"title={got!r}"
    if kind == "screen_contains":
        got = screen_text(app)
        hit = str(arg).lower() in got.lower()
        return hit, "found" if hit else f"not in {len(got)} chars of screen text"
    if kind == "file_exists":
        p = Path(str(arg)).expanduser()
        return p.exists(), str(p)
    if kind == "file_contains":
        p = Path(str(arg["path"])).expanduser()
        text = p.read_text() if p.exists() else ""
        return str(arg["text"]).lower() in text.lower(), f"{p} ({len(text)} chars)"
    if kind == "shell_contains":
        out = _shell(str(arg["cmd"]))
        return str(arg["text"]).lower() in out.lower(), out.strip()[:80]
    if kind == "trash_unchanged":
        now = trash_count()
        return now == before.get("trash"), f"trash {before.get('trash')} → {now}"
    return False, f"unknown check {kind}"


# ---------------------------------------------------------------- running


class CountingJev:
    """Wraps the Jev client so calls and latency can be reported per task."""

    def __init__(self, inner: JevLike) -> None:
        self.inner = inner
        self.calls = 0
        self.ms = 0

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> JevResponse:
        resp = self.inner.ask(state, questions)
        self.calls += 1
        self.ms += resp.latency_ms
        return resp


def run_task(task: Task, cfg: Config, display: Terminal, mode: Mode, approve: bool) -> Outcome:
    asked: list[str] = []
    acted: list[str] = []

    # An expect_ask task proves that the guard asks; it never runs the harmful action itself,
    # so --approve does not apply to it (Terminal would open, Safari history would go).
    say_yes = approve and not task.expect_ask

    def ask(action: str) -> bool:
        asked.append(action)
        display.status(f"ASK: may I {action}? → {'yes' if say_yes else 'no'}")
        return say_yes

    started = time.perf_counter()
    counting = CountingJev(Jev(model=cfg.model))
    checks: list[tuple[str, bool, str]] = []
    try:
        for app_name in task.quit_before:
            quit_app(app_name)
        for cmd in task.setup:
            _shell(cmd)
        for app_name in task.activate_before:
            _shell(f"open -a '{app_name}'")
            bring_to_front(app_name)
        before = {"trash": trash_count()}
        runner = build_runner(
            cfg, display, ask=ask, mode=mode, jev=counting, force_placement=task.placement
        )
        words = task.instruction.split()
        for i in range(task.per_tick, len(words) + task.per_tick, task.per_tick):
            verdicts = runner.tick(words[:i], words[i : i + 1])
            acted += [v.reason for v in verdicts if v.outcome.value == "execute"]
            time.sleep(cfg.tick_seconds)
        acted += [v.reason for v in runner.finish() if v.outcome.value == "execute"]
        time.sleep(task.settle_seconds)
        checks = [(json.dumps(c, ensure_ascii=False), *run_check(c, before)) for c in task.checks]
    except Exception as e:  # noqa: BLE001 - one broken task must not lose the others' results
        checks.append(("run", False, f"{type(e).__name__}: {e}"))
    finally:
        for cmd in task.teardown:
            _shell(cmd)
        for app_name in task.discard_after:
            discard_app(app_name)
        for app_name in task.quit_after:
            quit_app(app_name)
    seconds = time.perf_counter() - started
    ok = all(c[1] for c in checks)
    out = Outcome(
        task.name,
        ok and bool(asked) == task.expect_ask,
        checks,
        asked,
        task.expect_ask,
        seconds,
        counting.calls,
        counting.ms,
        acted,
    )
    return out


def user_touched_during(seconds: float) -> bool:
    """Did the person at the Mac press a key or click while the task ran?"""
    try:
        from yapp.placement import seconds_since_input

        return seconds_since_input() < seconds
    except Exception:  # noqa: BLE001 - if we cannot tell, assume not
        return False


def screen_locked() -> bool:
    """A locked screen makes every check see loginwindow; refuse rather than record junk."""
    try:
        from Quartz import CGSessionCopyCurrentDictionary

        session = CGSessionCopyCurrentDictionary() or {}
        return bool(session.get("CGSSessionScreenIsLocked"))
    except Exception:  # noqa: BLE001 - if we cannot tell, run
        return False


def run_tasks(
    cfg: Config,
    display: Terminal,
    *,
    directory: Path = DEFAULT_DIR,
    only: str = "",
    mode: Mode = Mode.ASK,
    approve: bool = False,
    results: Path = RESULTS,
) -> int:
    if screen_locked():
        display.show_error("the screen is locked: unlock it and run the tasks again")
        return 3
    tasks = load_tasks(directory, only)
    if not tasks:
        display.show_error(f"no tasks in {directory}")
        return 2
    outcomes: list[Outcome] = []
    for t in tasks:
        if screen_locked():
            display.show_error(
                f"the screen locked before {t.name}: stopping, nothing recorded for it"
            )
            break
        display.status(f"── task {t.name}: “{t.instruction}”")
        o = run_task(t, cfg, display, mode, approve)
        if screen_locked():
            display.show_error(
                f"the screen locked during {t.name}: its result is discarded; stopping"
            )
            break
        outcomes.append(o)
        display.status(
            f"   {'PASS' if o.passed else 'FAIL'} in {o.seconds:.1f}s · jev {o.jev_calls} calls "
            f"{o.jev_ms} ms · asked {o.asked or '-'}"
        )
    if not outcomes:
        return 3
    results.parent.mkdir(parents=True, exist_ok=True)
    with results.open("a") as f:
        for o in outcomes:
            f.write(json.dumps(o.row(), ensure_ascii=False) + "\n")
    table = Table(
        title=f"yapp tasks · mode {mode} · {sum(o.passed for o in outcomes)}/{len(outcomes)} pass"
    )
    for col in ("task", "pass", "checks", "ask", "steps", "jev", "s"):
        table.add_column(col)
    for o in outcomes:
        table.add_row(
            o.name,
            "✓" if o.passed else "✗",
            "; ".join(f"{'✓' if ok else '✗'} {d}" for _, ok, d in o.checks),
            ("asked" if o.asked else "quiet") + ("" if o.ask_ok else " (unexpected)"),
            str(len(o.acted)),
            f"{o.jev_calls} / {o.jev_ms} ms",
            f"{o.seconds:.0f}",
        )
    display.c.print(table)
    return 0 if all(o.passed for o in outcomes) else 1
