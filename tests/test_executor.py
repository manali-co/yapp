from pathlib import Path

from yapp.executor import Executor, applescript_escape
from yapp.types import App, Decision, Executed, Intent, Result

NOTES = App("notes", "Notes", "Launch Notes")


class Fake:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["osascript", "-e"] and "frontmost" in argv[2]:
            return "Safari\n"
        return ""


def test_escape() -> None:
    assert applescript_escape('say "hi" \\ bye') == 'say \\"hi\\" \\\\ bye'


def test_open_app() -> None:
    f = Fake()
    assert Executor(f).open_app(NOTES) == Result(True, "opened Notes")
    assert f.calls == [["open", "-a", "Notes"]]


def test_type_text_uses_system_events() -> None:
    f = Fake()
    Executor(f).type_text('hello "world"')
    assert f.calls[0][:2] == ["osascript", "-e"]
    assert 'keystroke "hello \\"world\\""' in f.calls[0][2]


def test_press_key() -> None:
    f = Fake()
    Executor(f).press_key("cmd+s")
    assert 'keystroke "s" using {command down}' in f.calls[0][2]
    Executor(f).press_key("enter")
    assert "key code 36" in f.calls[1][2]


def test_frontmost() -> None:
    assert Executor(Fake()).frontmost_app() == "Safari"


def test_undo_open_app_quits() -> None:
    f = Fake()
    d = Decision(
        tail="open notes",
        intent=Intent.OPEN_APP,
        intent_confidence=1,
        intent_probabilities={},
        app=NOTES,
    )
    Executor(f).undo(Executed(d, Result(True, "")))
    assert 'quit app "Notes"' in f.calls[0][2]


def test_undo_dictation_backspaces() -> None:
    f = Fake()
    d = Decision(
        tail="type hi", intent=Intent.TYPE_TEXT, intent_confidence=1, intent_probabilities={}
    )
    Executor(f).undo(Executed(d, Result(True, ""), typed_chars=3))
    assert "key code 51" in f.calls[0][2] and "repeat 3 times" in f.calls[0][2]


def test_open_file() -> None:
    f = Fake()
    Executor(f).open_file(Path("/tmp/a b.pdf"))
    assert f.calls == [["open", "/tmp/a b.pdf"]]
