"""Display protocol and the developer view in the terminal."""

from __future__ import annotations

from typing import Protocol

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from yapp.theme import YAPP_THEME
from yapp.types import Decision, Outcome, Result, Verdict


class Display(Protocol):
    """What the runner tells about each tick. The terminal and the bar both implement it."""

    def status(self, msg: str) -> None: ...
    def listening(self, level: float) -> None: ...
    def thinking(self) -> None: ...
    def show_transcript(self, committed: list[str], pending: list[str]) -> None: ...
    def show_decision(self, d: Decision) -> None: ...
    def show_verdict(self, v: Verdict) -> None: ...
    def show_result(self, r: Result) -> None: ...
    def show_error(self, msg: str) -> None: ...


VERDICT_STYLE = {
    Outcome.EXECUTE: "yapp.verdict.act",
    Outcome.WAIT: "yapp.dim",
    Outcome.IGNORE: "yapp.verdict.unsure",
    Outcome.REFUSE: "yapp.verdict.refuse",
}


class Terminal:
    def __init__(self, console: Console | None = None) -> None:
        self.c = console or Console(theme=YAPP_THEME)

    def status(self, msg: str) -> None:
        self.c.print(f"[bold cyan]{msg}[/]")

    def listening(self, level: float) -> None:
        n = int(level * 20)
        bars = f"[yapp.bar.fill]{'▮' * n}[/][yapp.bar.track]{'▯' * (20 - n)}[/]"
        self.c.print(f"[bold green]● listening[/] {bars} {level:.2f}  (release to finish)")

    def thinking(self) -> None:
        self.c.print("[yapp.dim]thinking…[/]")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        t = Text(" ".join(committed), style="yapp.transcript")
        if pending:
            t.append(" " + " ".join(pending), style="yapp.transcript.pending")
        self.c.print(Panel(t, title="heard", border_style="yapp.dim"))

    def show_decision(self, d: Decision) -> None:
        table = Table(
            title=f"jev {d.latency_ms} ms · tail: “{d.tail}”",
            show_header=True,
            header_style="yapp.table.header",
        )
        table.add_column("intent")
        table.add_column("p", justify="right")
        for k, p in sorted(d.intent_probabilities.items(), key=lambda kv: -kv[1]):
            style = "yapp.table.top" if k == d.intent else "yapp.table.row"
            table.add_row(k, f"{p:.2f}", style=style)
        table.add_row("[yapp.dim]confidence[/]", f"{d.intent_confidence:.2f}")
        table.add_row("[yapp.dim]is_complete[/]", f"{d.is_complete:.2f}")
        table.add_row("[yapp.dim]ends_dictation[/]", f"{d.ends_dictation:.2f}")
        table.add_row("[yapp.dim]is_destructive[/]", f"{d.is_destructive:.2f}")
        if d.app:
            table.add_row("[yapp.dim]app[/]", f"{d.app.name} ({d.app_confidence or 0:.2f})")
        self.c.print(table)

    def show_verdict(self, v: Verdict) -> None:
        self.c.print(f"[{VERDICT_STYLE[v.outcome]}]{v.outcome.upper()}[/] {v.reason}")

    def show_result(self, r: Result) -> None:
        if r.ok:
            self.c.print(f"[yapp.verdict.ok]✓[/] {r.message}")
        else:
            self.c.print(f"[yapp.verdict.refuse]✗[/] {r.message}")

    def show_error(self, msg: str) -> None:
        self.c.print(f"[yapp.verdict.refuse]error:[/] {msg}")
