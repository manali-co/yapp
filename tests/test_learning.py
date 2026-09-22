import json
from pathlib import Path

from yapp.config import Config
from yapp.learning import Learning
from yapp.types import App, Decision, Intent

NOTES = App("notes", "Notes", "")


def dec(tail: str) -> Decision:
    return Decision(
        tail=tail,
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={},
        app=NOTES,
        consumed_words=2,
    )


def test_positive_after_delay(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl", learn_after_seconds=10)
    learning = Learning(cfg)
    learning.executed(dec("open node"), at=100.0)
    learning.flush(105.0)
    assert learning.examples() == {}
    learning.flush(111.0)
    assert learning.examples() == {"notes": ["open node"]}
    rows = [json.loads(x) for x in (tmp_path / "l.jsonl").read_text().splitlines()]
    assert rows[0]["label"] == "positive" and rows[0]["option"] == "notes"


def test_undo_marks_negative(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl")
    learning = Learning(cfg)
    learning.executed(dec("open nodes"), at=100.0)
    learning.undone(at=102.0)
    learning.flush(200.0)
    assert learning.examples() == {}
    assert learning.negatives() == {"notes": ["open nodes"]}


def test_reload_from_disk(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl")
    learning = Learning(cfg)
    learning.executed(dec("open node"), at=0.0)
    learning.flush(100.0)
    assert Learning(cfg).examples() == {"notes": ["open node"]}


def test_two_actions_in_one_tick_both_learn(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl", learn_after_seconds=10)
    learning = Learning(cfg)
    learning.executed(dec("open node"), at=100.0)
    d2 = Decision(
        tail="open notes",
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={},
        app=App("safari", "Safari", ""),
        consumed_words=2,
    )
    learning.executed(d2, at=100.2)
    learning.flush(111.0)
    assert learning.examples() == {"notes": ["open node"], "safari": ["open notes"]}
