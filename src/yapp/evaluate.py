"""`yapp eval`: accuracy per confidence bucket. Paste the table into PRs that touch thresholds."""

from __future__ import annotations

import json
from pathlib import Path

from rich.table import Table

from yapp.config import Config
from yapp.display import Display
from yapp.intent import Context, classify
from yapp.jev import Jev
from yapp.types import App

EVAL_APP_NAMES = [
    ("notes", "Notes"),
    ("safari", "Safari"),
    ("slack", "Slack"),
    ("numbers", "Numbers"),
    ("google_chrome", "Google Chrome"),
    ("terminal", "Terminal"),
    ("finder", "Finder"),
    ("mail", "Mail"),
    ("messages", "Messages"),
    ("music", "Music"),
]
EVAL_APPS = [App(k, n, f"Launch {n}") for k, n in EVAL_APP_NAMES]
BUCKETS = [(0.85, "≥ 0.85"), (0.60, "0.60–0.85"), (0.0, "< 0.60")]
DEFAULT_PATH = Path("tests/eval/transcripts.jsonl")


def run_eval(cfg: Config, display: Display, path: Path = DEFAULT_PATH) -> int:
    jev = Jev(model=cfg.model)
    ctx = Context(apps=EVAL_APPS, frontmost_app="Finder", already_done=[], dictating=False)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    stats: dict[str, list[bool]] = {label: [] for _, label in BUCKETS}
    wrong: list[str] = []
    for row in rows:
        d = classify(row["tail"], ctx, jev, cfg)
        ok = d.intent == row["intent"]
        if row.get("app") is not None:
            ok = ok and d.app is not None and d.app.key == row["app"]
        if "complete" in row:
            ok = ok and ((d.is_complete >= cfg.thresholds.complete) == row["complete"])
        for lo, label in BUCKETS:
            if d.intent_confidence >= lo:
                stats[label].append(bool(ok))
                break
        if not ok:
            app = d.app.key if d.app else ""
            wrong.append(
                f"{row['tail']!r} → {d.intent} {app} conf {d.intent_confidence:.2f}"
                f" complete {d.is_complete:.2f}"
            )
    t = Table(title=f"yapp eval · {len(rows)} rows · {cfg.model}")
    t.add_column("confidence")
    t.add_column("n", justify="right")
    t.add_column("accuracy", justify="right")
    for _, label in BUCKETS:
        xs = stats[label]
        t.add_row(label, str(len(xs)), f"{(sum(xs) / len(xs) * 100):.0f}%" if xs else "–")
    display.c.print(t)
    for w in wrong:
        display.c.print(f"[red]✗[/] {w}")
    return 0 if not wrong else 1
