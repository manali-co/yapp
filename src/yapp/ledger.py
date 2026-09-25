"""What Yapp opened this session, so "clean up" can close exactly that and nothing else."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

HAND_OFF = "hand_off"
TOOL = "tool"
PENDING = "pending"  # decided at session end, once, from the whole utterance


@dataclass(frozen=True)
class OpenedWindow:
    app: str
    title: str
    ref: Any = field(compare=False)
    purpose: str = PENDING  # hand_off windows become the user's at session end


@dataclass
class Ledger:
    launched_apps: list[str] = field(default_factory=list)  # were not running before
    windows: list[OpenedWindow] = field(default_factory=list)
    app_purpose: dict[str, str] = field(default_factory=dict)  # per launched app

    def note_launch(self, app: str, was_running: bool, purpose: str = PENDING) -> None:
        if not was_running and app not in self.launched_apps:
            self.launched_apps.append(app)
            self.app_purpose[app] = purpose

    def note_windows(
        self,
        app: str,
        before: list[Any],
        after: list[Any],
        title: Callable[[Any], str],
        purpose: str = PENDING,
    ) -> int:
        """Windows present after an action that were not there before belong to Yapp."""
        known = {id(w) for w in before} | {_key(w) for w in before}
        new = [w for w in after if id(w) not in known and _key(w) not in known]
        for w in new:
            self.windows.append(OpenedWindow(app, title(w), w, purpose))
        return len(new)

    def settle_purposes(self, kind: str) -> None:
        """Give every entry still pending this session's purpose."""
        self.windows = [
            OpenedWindow(w.app, w.title, w.ref, kind) if w.purpose == PENDING else w
            for w in self.windows
        ]
        for app, purpose in list(self.app_purpose.items()):
            if purpose == PENDING:
                self.app_purpose[app] = kind

    def release_hand_offs(self) -> list[str]:
        """Session over: what was opened for the user is theirs now. Drop it from the ledger
        (clean-up never touches it) and say what was handed over."""
        handed = [f"{w.app} window '{w.title}'" for w in self.windows if w.purpose == HAND_OFF]
        self.windows = [w for w in self.windows if w.purpose != HAND_OFF]
        for app in list(self.launched_apps):
            if self.app_purpose.get(app) == HAND_OFF:
                handed.append(app)
                self.launched_apps.remove(app)
                self.app_purpose.pop(app, None)
        return handed

    @property
    def empty(self) -> bool:
        return not self.launched_apps and not self.windows

    def cleanup(
        self,
        *,
        close: Callable[[Any], bool],
        quit_app: Callable[[str], bool],
        restore: Callable[[], bool],
        discard: Callable[[OpenedWindow], str | None] = lambda w: None,
        log: Callable[[str], None] = lambda s: None,
    ) -> list[str]:
        """Unwind in reverse: windows (a save sheet goes through `discard`, which asks the
        guard), then apps, then the user's window frame."""
        done: list[str] = []
        for w in reversed(self.windows):
            if close(w.ref):
                done.append(f"closed {w.app} window '{w.title}'")
                note = discard(w)
                if note:
                    done.append(note)
            else:
                log(f"cleanup: could not close {w.app} window '{w.title}'")
        for app in reversed(self.launched_apps):
            if quit_app(app):
                done.append(f"quit {app}")
            else:
                done.append(f"asked {app} to quit")  # it may still be showing a Save sheet
                log(f"cleanup: {app} did not quit in time")
        if restore():
            done.append("put your window back")
        self.windows.clear()
        self.launched_apps.clear()
        return done


def _key(win: Any) -> Any:
    try:
        return hash(win)
    except TypeError:
        return id(win)
