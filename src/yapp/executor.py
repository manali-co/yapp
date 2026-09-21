"""macOS actions. Every shell call goes through one `run` seam so tests inject a fake."""

from __future__ import annotations

from pathlib import Path

from yapp.catalog import ShellRunner, run_capture
from yapp.types import App, Executed, Intent, Result

KEY_CODES = {"enter": 36, "escape": 53, "backspace": 51}
MODIFIERS = {
    "cmd": "command down",
    "shift": "shift down",
    "alt": "option down",
    "ctrl": "control down",
}
SE = 'tell application "System Events" to '


def applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class Executor:
    def __init__(self, run: ShellRunner = run_capture) -> None:
        self._run = run

    def _osa(self, script: str) -> str:
        return self._run(["osascript", "-e", script])

    def open_app(self, app: App) -> Result:
        self._run(["open", "-a", app.name])
        return Result(True, f"opened {app.name}")

    def type_text(self, text: str) -> Result:
        if not text:
            return Result(True, "nothing to type")
        self._osa(f'{SE}keystroke "{applescript_escape(text)}"')
        return Result(True, f"typed {len(text)} chars")

    def press_key(self, combo: str) -> Result:
        parts = combo.split("+")
        key = parts[-1]
        mods = [MODIFIERS[m] for m in parts[:-1] if m in MODIFIERS]
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        if key in KEY_CODES:
            script = f"{SE}key code {KEY_CODES[key]}{using}"
        else:
            script = f'{SE}keystroke "{applescript_escape(key)}"{using}'
        self._osa(script)
        return Result(True, f"pressed {combo}")

    def open_file(self, path: Path) -> Result:
        self._run(["open", str(path)])
        return Result(True, f"opened {path.name}")

    def frontmost_app(self) -> str:
        out = self._osa(f"{SE}get name of first application process whose frontmost is true")
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
            case Intent.PRESS_KEY:
                self._osa(f'{SE}keystroke "z" using {{command down}}')
                return Result(True, "sent cmd+z")
        return Result(False, "nothing to undo")
