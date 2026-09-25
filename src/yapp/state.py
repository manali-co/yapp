"""Small persisted app state: sessions run (drives first-run hints) and the permission mode."""

from __future__ import annotations

import json
from pathlib import Path

HINT_SESSIONS = 5


class AppState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.sessions = 0
        self.mode = "ask"
        try:
            data = json.loads(path.read_text())
            self.sessions = int(data.get("sessions", 0))
            self.mode = str(data.get("mode", "ask"))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"sessions": self.sessions, "mode": self.mode}))

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._save()

    @property
    def show_hint(self) -> bool:
        return self.sessions < HINT_SESSIONS

    def bump_sessions(self) -> int:
        self.sessions += 1
        self._save()
        return self.sessions
