from rich.console import Console

from yapp.display import Display, Terminal


def test_terminal_is_a_display() -> None:
    t = Terminal(Console(record=True, width=80))
    d: Display = t
    d.thinking()
    d.status("x")
    assert isinstance(t, Terminal)
