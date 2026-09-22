"""Yapp terminal palette for Python rich.

Neutral: uses the terminal's own ANSI colours so it follows the user's theme, with the
terminal's blue standing in for the macOS accent.
"""

from rich.theme import Theme

YAPP_THEME = Theme(
    {
        "yapp.transcript": "default",  # locked-in words
        "yapp.transcript.pending": "dim",  # still settling
        "yapp.table.header": "dim",
        "yapp.table.top": "bold blue",  # winning intent
        "yapp.table.row": "default",
        "yapp.bar.fill": "blue",
        "yapp.bar.track": "bright_black",
        "yapp.verdict.act": "bold blue",  # → Opening Notes
        "yapp.verdict.typing": "blue",  # ⌨ Typing…
        "yapp.verdict.ok": "bold green",  # ✓ Undone
        "yapp.verdict.unsure": "yellow",  # ~ Not sure what you meant
        "yapp.verdict.refuse": "bold red",  # ✕ Won't do that
        "yapp.verdict.error": "red",  # ! Heard you, can't decide
        "yapp.dim": "dim",
    }
)

# from rich.console import Console
# console = Console(theme=YAPP_THEME)
# console.print("[yapp.transcript]open notes and[/] [yapp.transcript.pending]switch to saf[/]")
# console.print("[yapp.verdict.act]→ Opening Notes[/] [yapp.dim]0.93 · 184 ms[/]")
