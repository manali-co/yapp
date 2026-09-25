"""macOS actions. Every shell call goes through one `run` seam so tests inject a fake."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from yapp.catalog import ShellError, ShellRunner, run_capture
from yapp.types import App, Executed, Intent, Result

KEY_CODES = {"enter": 36, "escape": 53, "backspace": 51}
MODIFIERS = {
    "cmd": "command down",
    "shift": "shift down",
    "alt": "option down",
    "ctrl": "control down",
}
SE = 'tell application "System Events" to '


class ScreenFn(Protocol):
    def __call__(self, words: str, *, app: str | None = None, parallel: bool = False) -> Result: ...


def applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class Executor:
    def __init__(
        self,
        run: ShellRunner = run_capture,
        screen: ScreenFn | None = None,
        leave_full_screen: Callable[[], bool] | None = None,
        raise_app: Callable[[str], bool] | None = None,
    ) -> None:
        self._run = run
        self.screen_fn = screen
        self.leave_full_screen = leave_full_screen
        self.raise_app = raise_app

    def screen(self, words: str, *, app: str | None = None, parallel: bool = False) -> Result:
        """A screen action: the app (in front, or the one Yapp works in) is read live and Jev
        picks a target per step (see ax.py)."""
        if self.screen_fn is None:
            return Result(False, "screen actions are not available")
        return self.screen_fn(words, app=app, parallel=parallel)

    def _osa(self, script: str) -> str:
        return self._run(["osascript", "-e", script])

    def _attempt(self, argv_or_script: list[str] | str, ok_message: str) -> Result:
        """Run one command; a non-zero exit becomes Result(False, stderr) instead of a lie."""
        try:
            if isinstance(argv_or_script, str):
                self._osa(argv_or_script)
            else:
                self._run(argv_or_script)
        except ShellError as err:
            return Result(False, str(err))
        return Result(True, ok_message)

    def open_app(self, app: App, *, activate: bool = True) -> Result:
        """Launch or switch to the app. `activate=False` (parallel mode) leaves the user's
        window and keyboard alone: `open -g` and no raise."""
        if not activate:
            return self._attempt(["open", "-g", "-a", app.name], f"opened {app.name} on the side")
        left = bool(self.leave_full_screen and self.leave_full_screen())
        r = self._attempt(["open", "-a", app.name], f"opened {app.name}")
        if r.ok and self.raise_app is not None and not self.raise_app(app.name):
            r = Result(True, f"opened {app.name} (could not bring it to the front)")
        return Result(r.ok, f"left full screen, {r.message}") if left and r.ok else r

    def type_ax(self, app: str, text: str) -> bool:
        """Append text to the app's focused element without the keyboard (parallel mode)."""
        try:
            from ApplicationServices import AXUIElementSetAttributeValue

            from yapp.ax import _attr, app_element

            el, _ = app_element(app)
            focused = _attr(el, "AXFocusedUIElement")
            if focused is None:
                return False
            current = str(_attr(focused, "AXValue") or "")
            wanted = current + text
            if AXUIElementSetAttributeValue(focused, "AXValue", wanted) != 0:
                return False
            return str(_attr(focused, "AXValue") or "") == wanted
        except Exception:  # noqa: BLE001 - any refusal means: borrow focus instead
            return False

    def type_text(self, text: str) -> Result:
        if not text:
            return Result(True, "nothing to type")
        return self._attempt(
            f'{SE}keystroke "{applescript_escape(text)}"', f"typed {len(text)} chars"
        )

    def press_key(self, combo: str) -> Result:
        parts = combo.split("+")
        key = parts[-1]
        mods = [MODIFIERS[m] for m in parts[:-1] if m in MODIFIERS]
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        if key in KEY_CODES:
            script = f"{SE}key code {KEY_CODES[key]}{using}"
        else:
            script = f'{SE}keystroke "{applescript_escape(key)}"{using}'
        return self._attempt(script, f"pressed {combo}")

    def open_file(self, path: Path) -> Result:
        return self._attempt(["open", str(path)], f"opened {path.name}")

    def frontmost_app(self) -> str:
        try:
            out = self._osa(f"{SE}get name of first application process whose frontmost is true")
        except ShellError:
            return "unknown"
        return out.strip() or "unknown"

    def undo(self, last: Executed) -> Result:
        d = last.decision
        match d.intent:
            case Intent.OPEN_APP if d.app is not None:
                self._osa(f'quit app "{applescript_escape(d.app.name)}"')
                return Result(True, f"quit {d.app.name}")
            case Intent.TYPE_TEXT:
                n = max(last.typed_chars, 0)
                if n:
                    self._osa(f"{SE}repeat {n} times\nkey code 51\nend repeat")
                return Result(True, f"erased {n} chars")
            case Intent.OPEN_FILE:
                self._osa(f'{SE}keystroke "w" using {{command down}}')
                return Result(True, "closed window")
            case Intent.PRESS_KEY | Intent.SCREEN:
                self._osa(f'{SE}keystroke "z" using {{command down}}')
                return Result(True, "sent cmd+z")
        return Result(False, "nothing to undo")
