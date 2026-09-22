"""Small persisted app state: how many sessions have run (drives the first-run hints)."""

from __future__ import annotations

import json
from pathlib import Path

HINT_SESSIONS = 5


class AppState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.sessions = 0
        try:
            data = json.loads(path.read_text())
            self.sessions = int(data.get("sessions", 0))
        except (OSError, ValueError):
            pass

    @property
    def show_hint(self) -> bool:
        return self.sessions < HINT_SESSIONS

    def bump_sessions(self) -> int:
        self.sessions += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"sessions": self.sessions}))
        return self.sessions
