"""Yapp terminal palette for Python rich.

Companion to ui/tokens.css; ported from the design project.
"""

from rich.theme import Theme

YAPP_THEME = Theme(
    {
        "yapp.transcript": "#EFEBE4",  # locked-in words
        "yapp.transcript.pending": "#6B6760",  # still settling
        "yapp.table.header": "#6B6760",
        "yapp.table.top": "bold #E9B88F",
        "yapp.table.row": "#A39E95",
        "yapp.bar.fill": "#E9B88F",
        "yapp.bar.track": "#3A3835",
        "yapp.verdict.act": "bold #E9B88F",  # → Opening Notes
        "yapp.verdict.typing": "#DCCB9A",  # ⌨ Typing…
        "yapp.verdict.ok": "bold #A7D2B3",  # ✓ Undone
        "yapp.verdict.unsure": "#A39E95",  # ~ Not sure what you meant
        "yapp.verdict.refuse": "bold #C97A67",  # ✕ Won't do that
        "yapp.dim": "#6B6760",
    }
)
