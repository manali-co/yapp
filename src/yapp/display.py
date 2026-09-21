"""Developer view in the terminal."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from yapp.types import Decision, Outcome, Result, Verdict

COLORS = {
    Outcome.EXECUTE: "green",
    Outcome.WAIT: "yellow",
    Outcome.IGNORE: "grey50",
    Outcome.REFUSE: "red",
}


class Display:
    def __init__(self, console: Console | None = None) -> None:
        self.c = console or Console()

    def status(self, msg: str) -> None:
        self.c.print(f"[bold cyan]{msg}[/]")

    def listening(self, level: float) -> None:
        bars = "▮" * int(level * 20) + "▯" * (20 - int(level * 20))
        self.c.print(f"[bold green]● listening[/] {bars} {level:.2f}  (release to finish)")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        t = Text(" ".join(committed), style="bold")
        if pending:
            t.append(" " + " ".join(pending), style="dim")
        self.c.print(Panel(t, title="heard", border_style="cyan"))

    def show_decision(self, d: Decision) -> None:
        table = Table(title=f"jev {d.latency_ms} ms · tail: “{d.tail}”", show_header=True)
        table.add_column("intent")
        table.add_column("p", justify="right")
        for k, p in sorted(d.intent_probabilities.items(), key=lambda kv: -kv[1]):
            table.add_row(k, f"{p:.2f}", style="bold" if k == d.intent else "")
        table.add_row("[dim]confidence[/]", f"{d.intent_confidence:.2f}")
        table.add_row("[dim]is_complete[/]", f"{d.is_complete:.2f}")
        table.add_row("[dim]ends_dictation[/]", f"{d.ends_dictation:.2f}")
        table.add_row("[dim]is_destructive[/]", f"{d.is_destructive:.2f}")
        if d.app:
            table.add_row("[dim]app[/]", f"{d.app.name} ({d.app_confidence or 0:.2f})")
        self.c.print(table)

    def show_verdict(self, v: Verdict) -> None:
        self.c.print(f"[{COLORS[v.outcome]}]{v.outcome.upper()}[/] {v.reason}")

    def show_result(self, r: Result) -> None:
        self.c.print(f"[green]✓[/] {r.message}" if r.ok else f"[red]✗[/] {r.message}")

    def show_error(self, msg: str) -> None:
        self.c.print(f"[red]error:[/] {msg}")
