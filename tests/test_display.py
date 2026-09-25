from rich.console import Console

from yapp.display import Display, Terminal


def test_terminal_is_a_display() -> None:
    t = Terminal(Console(record=True, width=80))
    d: Display = t
    d.thinking()
    d.status("x")
    assert isinstance(t, Terminal)


def test_terminal_with_plain_console_renders_every_panel() -> None:
    from yapp.types import App, Decision, Intent, Outcome, Result, Verdict

    console = Console(record=True, width=100, file=open("/dev/null", "w"))
    t = Terminal(console)  # no theme passed in: styles must still resolve
    t.listening(0.3)
    t.show_transcript(["open", "notes"], ["and"])
    d = Decision(
        tail="open notes",
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={"open_app": 0.9, "none": 0.1},
        app=App("notes", "Notes", ""),
        app_confidence=0.8,
    )
    t.show_decision(d)
    t.show_verdict(Verdict(Outcome.EXECUTE, "open Notes"))
    t.show_result(Result(True, "opened Notes"))
    t.show_result(Result(False, "nope"))
    t.show_error("boom")


def test_free_text_is_never_parsed_as_markup() -> None:
    from io import StringIO

    from rich.console import Console

    from yapp.display import Terminal
    from yapp.types import Result

    buf = StringIO()
    term = Terminal(Console(file=buf, force_terminal=False, width=200))
    term.status("pressed [/b] weird [bold]label")  # a control label with rich-like brackets
    term.show_result(Result(True, "typed '[x]' into [/]"))
    term.show_error("[/] not markup")
    out = buf.getvalue()
    assert "[/b] weird [bold]label" in out and "[x]" in out and "[/] not markup" in out
