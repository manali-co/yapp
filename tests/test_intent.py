import pytest
from typesafe_sdk import Choice

from yapp.config import Config
from yapp.intent import (
    Context,
    build_questions,
    classify,
    consumed_for,
    extract_file_query,
    extract_text,
    strip_leading_conjunctions,
)
from yapp.jev import Jev
from yapp.types import App, Intent

APPS = [
    App("notes", "Notes", "Launch Notes"),
    App("safari", "Safari", "Launch Safari"),
    App("slack", "Slack", "Launch Slack"),
]


def ctx(**kw: object) -> Context:
    base: dict[str, object] = dict(
        apps=APPS, frontmost_app="Finder", already_done=[], dictating=False, examples={}
    )
    base.update(kw)
    return Context(**base)  # type: ignore[arg-type]


def test_extract_text() -> None:
    assert extract_text("type hello there") == "hello there"
    assert extract_text("write: dear sam") == "dear sam"
    assert extract_text("type") == ""


def test_extract_file_query() -> None:
    assert extract_file_query("open my resume") == "resume"
    assert extract_file_query("find the budget spreadsheet file") == "budget spreadsheet"


def test_strip_leading_conjunctions() -> None:
    assert strip_leading_conjunctions("and then switch to slack") == "switch to slack"
    assert strip_leading_conjunctions("open notes and") == "open notes and"


def test_consumed_stops_at_conjunction() -> None:
    assert consumed_for("open notes and switch to safari", Intent.OPEN_APP) == 2
    assert consumed_for("open notes", Intent.OPEN_APP) == 2
    assert consumed_for("type hello and then some", Intent.TYPE_TEXT) == 1  # verb only
    assert consumed_for("and switch to safari", Intent.OPEN_APP) == 4  # leading 'and' too


def test_build_questions_has_unsure_and_learned_examples() -> None:
    q = build_questions(ctx(examples={"notes": ["open node"]}, negatives={"notes": ["open nodes"]}))
    app = q["app"]
    assert isinstance(app, Choice)
    assert "unsure" in app.criteria
    notes = app.criteria["notes"]
    assert isinstance(notes, dict)
    assert "open node" in notes["examples"]
    assert notes["not_for"] == "open nodes"
    expected = {"intent", "app", "key_combo", "is_complete", "ends_dictation", "is_destructive"}
    assert set(q) == expected


@pytest.mark.jev
@pytest.mark.parametrize(
    ("tail", "intent", "app", "complete"),
    [
        ("open notes", Intent.OPEN_APP, "notes", True),
        ("open notes and", Intent.OPEN_APP, "notes", True),
        ("switch to safari", Intent.OPEN_APP, "safari", True),
        ("open", Intent.OPEN_APP, None, False),
        ("type hello there", Intent.TYPE_TEXT, None, True),
        ("undo", Intent.UNDO, None, True),
        ("save that", Intent.PRESS_KEY, None, True),
        ("um so", Intent.NONE, None, False),
    ],
)
def test_live_classification(tail: str, intent: Intent, app: str | None, complete: bool) -> None:
    cfg = Config()
    d = classify(tail, ctx(), Jev(model=cfg.model), cfg)
    assert d.intent == intent, d.intent_probabilities
    if app:
        assert d.app is not None and d.app.key == app
    assert (d.is_complete >= cfg.thresholds.complete) == complete, d.is_complete
