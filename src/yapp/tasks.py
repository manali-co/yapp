"""`yapp tasks`: the house benchmark. Real apps on this Mac, scripted checks, one table.

A task is a YAML file: an instruction spoken the way a person would, optional setup and
teardown shell commands, checks against the live screen or the file system, and whether the
permission guard is expected to ask. Runs through the Yapp bundle so Accessibility works.
"""

from __future__ import annotations

import glob
import json
import os
import re
import secrets
import shlex
import shutil
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
    close_tab_after: list[str] = field(default_factory=list)  # press File › Close Tab in the app
    cleanup: bool = True  # unwind the runner's ledger (windows/apps Yapp opened) after checks
    # Every task snapshots Notes and Reminders and deletes what it created: a disturbed run
    # can dictate into whatever app the person at the Mac has in front.
    tidy_notes: bool = True
    tidy_reminders: bool = True
    # Paths (globs, ~ allowed) the task may create: whatever matches after the run and did
    # not match before it is removed; anything that was already there is never touched.
    owned_paths: list[str] = field(default_factory=list)
    # glob -> text a new match must contain to be removed (for folders other things also
    # write into, like an iCloud-synced one: a name alone never proves the file is ours)
    owned_containing: dict[str, str] = field(default_factory=dict)
    # Apps whose open documents are checked at the end: a document saved under a name that
    # carries this run's token is this run's, and its file is removed.
    saved_in: list[str] = field(default_factory=list)


RUN_MARK = "@RUN@"  # replaced in setup, teardown and checks by a per-run random token


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
                close_tab_after=[str(a) for a in data.get("close_tab_after") or []],
                cleanup=bool(data.get("cleanup", True)),
                tidy_notes=bool(data.get("tidy_notes", True)),
                tidy_reminders=bool(data.get("tidy_reminders", True)),
                owned_paths=[
                    str(g["glob"]) if isinstance(g, dict) else str(g)
                    for g in data.get("owned_paths") or []
                ],
                owned_containing={
                    str(g["glob"]): str(g["containing"])
                    for g in data.get("owned_paths") or []
                    if isinstance(g, dict) and g.get("containing")
                },
                saved_in=[str(a) for a in data.get("saved_in") or []],
            )
        )
    return out


# ---------------------------------------------------------------- live probes


def settle(seconds: float) -> None:
    """Wait like the real app does: with the main run loop turning, so overlay windows,
    animations, and NSWorkspace notifications actually happen while we wait."""
    from yapp.ax import refresh_workspace

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        refresh_workspace()
        time.sleep(0.1)


def _shell(cmd: str) -> str:
    """Run one task command. It is an argv line (shlex rules), not a shell: no pipes or &&."""
    return _shell_ok(cmd)[1]


def _shell_ok(cmd: str, timeout: float = 30.0) -> tuple[bool, str]:
    """(exit status 0?, output) of one task command. A hang (an app that never answers)
    is a failure after `timeout` seconds, never a stalled run."""
    argv = shlex.split(cmd)
    if not argv:
        return True, ""
    try:
        r = subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:.0f} s"
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def _matches(pattern: str) -> set[str]:
    return set(glob.glob(os.path.expanduser(pattern)))


def snapshot_paths(patterns: list[str]) -> dict[str, set[str]]:
    """What already matches each owned glob before the task: never the task's to remove."""
    return {g: _matches(g) for g in patterns}


def document_paths(app: str) -> list[str]:
    """Files behind the app's open windows (Accessibility AXDocument), for any folder the
    Save sheet picked, including ones this process cannot list."""
    from urllib.parse import unquote, urlparse

    from yapp import windows as win
    from yapp.ax import _attr

    out: list[str] = []
    for w in win.app_windows(app):
        url = _attr(w, "AXDocument")
        if isinstance(url, str) and url.startswith("file://"):
            out.append(unquote(urlparse(url).path))
    return out


def remove_saved(apps: list[str], names: list[str]) -> list[str]:
    """Remove files the run saved: open documents named exactly as the task's `saved_as`
    checks expect (names carry the run's token), plus any extension."""
    notes: list[str] = []
    wanted = {n.lower() for n in names if n}
    for app in apps:
        for path in document_paths(app):
            stem = os.path.splitext(os.path.basename(path))[0].lower()
            if stem in wanted and os.path.isfile(path):
                try:
                    os.unlink(path)
                    notes.append(f"removed {path}")
                except OSError as e:
                    notes.append(f"could not remove {path}: {e}")
    return notes


def _contains(path: str, text: str) -> bool:
    """Does the file (or any file inside a document package) contain `text`?"""
    files = [path]
    if os.path.isdir(path):
        files = [os.path.join(r, f) for r, _, fs in os.walk(path) for f in fs]
    for f in files:
        try:
            with open(f, "rb") as fh:
                if text.lower() in fh.read(1_000_000).decode("utf-8", "ignore").lower():
                    return True
        except OSError:
            continue
    return False


def remove_new_paths(
    before: dict[str, set[str]], containing: dict[str, str] | None = None
) -> list[str]:
    """Remove only what matches now and did not match before the task, and, where the
    task names the text, only files that contain it."""
    removed: list[str] = []
    for pattern, old in before.items():
        needle = (containing or {}).get(pattern)
        for path in sorted(_matches(pattern) - old):
            if needle and not _contains(path, needle):
                removed.append(f"left {path}: new, but not the task's (no '{needle}')")
                continue
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)
                removed.append(f"removed {path}")
            except OSError as e:
                removed.append(f"could not remove {path}: {e}")
    return removed


def with_token(task: Task, token: str) -> Task:
    """The task with every @RUN@ (instruction, setup, teardown, checks, owned paths)
    replaced by `token`."""

    def sub(x: Any) -> Any:
        if isinstance(x, str):
            return x.replace(RUN_MARK, token)
        if isinstance(x, dict):
            return {k: sub(v) for k, v in x.items()}
        if isinstance(x, list):
            return [sub(v) for v in x]
        return x

    from dataclasses import replace

    return replace(
        task,
        instruction=sub(task.instruction),
        setup=sub(task.setup),
        teardown=sub(task.teardown),
        checks=sub(task.checks),
        owned_paths=sub(task.owned_paths),
    )


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


def _osascript(script: str, timeout: float = 10.0) -> tuple[bool, str]:
    """(ok, text). Automation denied, a failed command, or a hang (a consent prompt waiting
    for a click) is a failure, never a result."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"osascript timed out after {timeout:.0f} s"
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr).strip()


DICTATION_VERBS = ("type", "write", "enter", "say")


def dictated_text(instruction: str) -> str:
    """The content a task dictates: the words after its last 'type'/'write'/'enter'/'say'.
    Only these are task-specific; "new reminder" is a phrase anyone might use."""
    words = instruction.lower().split()
    for i in range(len(words) - 1, -1, -1):
        if words[i] in DICTATION_VERBS:
            return " ".join(words[i + 1 :])
    return ""


def owned_by_task(name: str, instruction: str) -> bool:
    """Ownership by content: a new item is the task's only if its name carries two
    consecutive words of what the task dictated. Blank items are never deleted: nothing
    proves a blank one is the task's rather than one that arrived through sync. A person's
    own new item does not qualify either."""
    content = [w for w in re.findall(r"[a-z0-9']+", dictated_text(instruction)) if len(w) > 1]
    if not content:
        return False
    text = name.lower()
    return any(f"{a} {b}" in text for a, b in zip(content, content[1:], strict=False))


def _ids(app: str, what: str) -> set[str] | None:
    """Ids of every item, or None when the read failed (an empty library is a set)."""
    ok, out = _osascript(f'tell application "{app}" to get id of every {what}')
    if not ok:
        return None
    return {x.strip() for x in out.split(",") if x.strip()}


def _names(app: str, what: str, ids: set[str]) -> dict[str, str]:
    """Names of the given items; an item whose name could not be read is left out, so a
    transient failure can never make it look like a task-created (empty-named) item."""
    out: dict[str, str] = {}
    for i in ids:
        ok, name = _osascript(f'tell application "{app}" to get name of {what} id "{i}"')
        if ok:
            out[i] = name
    return out


def snapshot_content(task: Task) -> dict[str, set[str] | None]:
    """Ids of notes/reminders before a task (None = the read failed), for tidy-up."""
    snap: dict[str, set[str] | None] = {}
    if task.tidy_notes:
        snap["Notes"] = _ids("Notes", "note")
    if task.tidy_reminders:
        snap["Reminders"] = _ids("Reminders", "reminder")
    return snap


def delete_new_content(snap: dict[str, set[str] | None], instruction: str) -> list[str]:
    """Delete the notes/reminders the task created: new since the snapshot AND owned by the
    task by content (see owned_by_task). Anything else new is left alone."""
    notes: list[str] = []
    for app, what in (("Notes", "note"), ("Reminders", "reminder")):
        if app not in snap:
            continue
        before = snap[app]
        if before is None:
            notes.append(f"{app}: the snapshot before the task failed; deleting nothing")
            continue
        time.sleep(1.0)  # a just-created item can take a moment to show up to AppleScript
        after = _ids(app, what)
        if after is None:
            notes.append(f"{app}: could not list items after the task; deleting nothing")
            continue
        new = after - before
        names = _names(app, what, new)
        mine = [i for i in new if i in names and owned_by_task(names[i], instruction)]
        unread = len(new) - len(names)
        failed = 0
        for i in mine:
            ok, _ = _osascript(f'tell application "{app}" to delete {what} id "{i}"')
            failed += 0 if ok else 1
        skipped = len(new) - len(mine)
        notes.append(
            f"deleted {len(mine) - failed} of {len(mine)} {what}(s) the task created"
            + (f"; {failed} could not be deleted" if failed else "")
            + (f"; left {skipped} new {what}(s) that are not the task's" if skipped else "")
            + (f" ({unread} could not be read)" if unread else "")
        )
    return notes


def close_tab(app_name: str) -> bool:
    """Harness helper: press the app's 'Close Tab' menu command (the tab a task opened)."""
    from yapp.ax import ax_menus, ax_press
    from yapp.native import app_is_running

    if not app_is_running(app_name):
        return False
    for t in ax_menus(app_name):
        if t.label.lower() == "close tab":
            return ax_press(t)
    return False


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
    """Items in the trash, or -1 when it cannot be read. Finder is asked first: reading
    ~/.Trash directly needs Full Disk Access, which the bundle usually does not have."""
    ok, out = _osascript('tell application "Finder" to count items of trash')
    if ok and out.strip().isdigit():
        return int(out.strip())
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
        import Quartz

        from yapp import windows as win

        w = win.focused_window(str(arg))
        frame = win.window_frame(w) if w is not None else None
        if frame is None:
            return False, f"no window for {arg}"
        settle(0.5)  # the window server applies our ordering a beat after the run loop turns
        mine = os.getpid()
        ours = [
            info.get("kCGWindowBounds", {})
            for info in (
                Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0) or []
            )
            if info.get("kCGWindowOwnerPID") == mine
        ]
        front_app = frontmost()
        if front_app.lower() != str(arg).lower():
            fw = win.focused_window(front_app)
            ff = win.window_frame(fw) if fw is not None else None
            if ff is not None and ff.overlap(frame) > 0:
                # The user's window overlaps Yapp's: the glow must be concealed right now.
                if ours:
                    return False, f"front app {front_app} overlaps {arg} but the glow is on screen"
                return True, f"front app {front_app} overlaps {arg}: glow concealed"
        for b in ours:
            glow = win.Rect(b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0))
            pairs = ((glow.x, frame.x), (glow.y, frame.y), (glow.w, frame.w), (glow.h, frame.h))
            if all(abs(a - c) <= 2 for a, c in pairs):
                return True, f"glow {glow} on {arg} {frame}"
        from yapp.highlight import debug_state

        return False, f"no glow window of ours around {arg} {frame}; {debug_state()}"
    if kind == "app_running":
        from yapp.native import app_is_running

        running = app_is_running(str(arg))
        return running, f"{arg} running={running}"
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
    if kind == "saved_as":
        app_name, name = str(arg["app"]), str(arg["name"])
        paths = document_paths(app_name)
        saved = [q for q in paths if name.lower() in os.path.basename(q).lower()]
        return bool(saved), (f"saved: {saved[0]}" if saved else f"open documents: {paths[:3]}")
    if kind == "created":
        was = before.get("paths", {}).get(str(arg))
        if was is None:
            return False, f"{arg} was not snapshotted before the run"
        new = sorted(_matches(str(arg)) - was)
        return bool(new), (f"new: {new[0]}" if new else f"nothing new matches {arg}")
    if kind == "shell_unchanged":
        was = before.get("shell", {}).get(str(arg))
        ok, now = _shell_ok(str(arg))
        if was is None or not ok:
            return False, f"could not compare: {now.strip()[:60]}"
        return now == was, f"{was.strip()[:40]!r} → {now.strip()[:40]!r}"
    if kind == "trash_unchanged":
        count_now = trash_count()
        count_was = int(before.get("trash", -1))
        if count_was < 0 or count_now < 0:
            return False, f"trash could not be counted ({count_was} → {count_now}): nothing proven"
        return count_now == count_was, f"trash {count_was} → {count_now}"
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
    asked_by_task: list[str] = []
    runner = None
    content_before: dict[str, set[str] | None] = {}
    token = secrets.token_hex(3)
    task = with_token(task, token)
    created = [str(c["created"]) for c in task.checks if "created" in c]
    paths_before = snapshot_paths(list(dict.fromkeys(task.owned_paths + created)))
    try:
        content_before = snapshot_content(task)
        for app_name in task.quit_before:
            if not quit_app(app_name):  # polite: unsaved work keeps it open, never discarded
                raise RuntimeError(f"setup failed: {app_name} did not quit (unsaved work?)")
        for cmd in task.setup:
            planted, said = _shell_ok(cmd)
            if not planted:  # a fixture that could not be planted proves nothing: stop here
                raise RuntimeError(f"setup failed: {cmd} → {said.strip()[:120]}")
        for app_name in task.activate_before:
            _shell(f"open -a '{app_name}'")
            bring_to_front(app_name)
        shell_cmds = [str(c["shell_unchanged"]) for c in task.checks if "shell_unchanged" in c]
        before: dict[str, Any] = {
            "trash": trash_count(),
            "paths": paths_before,
            "shell": {c: r[1] for c in shell_cmds for r in [_shell_ok(c)] if r[0]},
        }
        runner = build_runner(
            cfg, display, ask=ask, mode=mode, jev=counting, force_placement=task.placement
        )
        words = task.instruction.split()
        for i in range(task.per_tick, len(words) + task.per_tick, task.per_tick):
            verdicts = runner.tick(words[:i], words[i : i + 1])
            acted += [v.reason for v in verdicts if v.outcome.value == "execute"]
            time.sleep(cfg.tick_seconds)
        # The glow is a property of the session: hand-off windows lose it when the session
        # ends, so glow checks run before finish(); everything else after.
        during = [c for c in task.checks if "highlight_around" in c]
        after = [c for c in task.checks if "highlight_around" not in c]
        settle(1.0)
        checks = [(json.dumps(c, ensure_ascii=False), *run_check(c, before)) for c in during]
        acted += [v.reason for v in runner.finish() if v.outcome.value == "execute"]
        settle(task.settle_seconds)
        checks += [(json.dumps(c, ensure_ascii=False), *run_check(c, before)) for c in after]
        asked_by_task = list(asked)  # clean-up may ask too (a save sheet); that is not the task
    except Exception as e:  # noqa: BLE001 - one broken task must not lose the others' results
        checks.append(("run", False, f"{type(e).__name__}: {e}"))
    finally:
        saved_names = [str(c["saved_as"]["name"]) for c in task.checks if "saved_as" in c]
        for note in remove_saved(task.saved_in, saved_names):  # while windows still show it
            display.status(f"   {note}")
        ws = getattr(runner, "workspace", None)
        if task.cleanup and ws is not None:
            done = ws.cleanup()  # what this task opened goes away again
            if done:
                display.status("   cleanup: " + ", ".join(done))
        for app_name in task.close_tab_after:
            close_tab(app_name)
        for note in delete_new_content(content_before, task.instruction):
            display.status(f"   {note}")
        for cmd in task.teardown:
            _shell(cmd)
        for app_name in task.discard_after:
            discard_app(app_name)
        for app_name in task.quit_after:
            quit_app(app_name)
        # Last: closing an app can itself write files (an autosaved untitled document).
        for note in remove_new_paths(paths_before, task.owned_containing):  # only this run's
            display.status(f"   {note}")
    seconds = time.perf_counter() - started
    ok = all(c[1] for c in checks)
    out = Outcome(
        task.name,
        ok and bool(asked_by_task) == task.expect_ask,
        checks,
        asked_by_task,
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
