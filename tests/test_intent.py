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
    expected = {"intent", "app", "key_combo", "is_complete", "ends_dictation", "is_addressed"}
    assert set(q) == expected
    intent = q["intent"]
    assert isinstance(intent, Choice)
    open_app = intent.criteria["open_app"]
    assert isinstance(open_app, dict) and open_app["examples"][0] == "open node"


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
        ("new tab", Intent.SCREEN, None, True),
        ("zoom in", Intent.SCREEN, None, True),
        ("find on page", Intent.SCREEN, None, True),
        ("search for fable five", Intent.SCREEN, None, True),
    ],
)
def test_live_classification(tail: str, intent: Intent, app: str | None, complete: bool) -> None:
    cfg = Config()
    d = classify(tail, ctx(), Jev(model=cfg.model), cfg)
    assert d.intent == intent, d.intent_probabilities
    if app:
        assert d.app is not None and d.app.key == app
    assert (d.is_complete >= cfg.thresholds.complete) == complete, d.is_complete


def test_spoken_forms_split_camel_case() -> None:
    from yapp.intent import spoken_forms

    assert spoken_forms("TextEdit") == ["textedit", "text edit"]
    assert spoken_forms("Google Chrome") == ["google chrome"]
    assert spoken_forms("QuickTime Player") == ["quicktime player", "quick time player"]


def test_intent_examples_include_how_installed_apps_are_said() -> None:
    from yapp.types import App

    apps = [App("textedit", "TextEdit", "Launch TextEdit"), App("notes", "Notes", "Launch Notes")]
    q = build_questions(ctx(apps=apps), tail="open text edit")
    intent = q["intent"]
    assert isinstance(intent, Choice)
    open_app = intent.criteria["open_app"]
    assert isinstance(open_app, dict) and "open text edit" in open_app["examples"]


def test_canonical_app_names_joins_split_camel_case() -> None:
    from yapp.intent import canonical_app_names
    from yapp.types import App

    apps = [App("textedit", "TextEdit", ""), App("facetime", "FaceTime", ""), APPS[0]]
    assert canonical_app_names("open text edit and then face time", apps) == (
        "open textedit and then facetime"
    )
    assert canonical_app_names("edit the text", apps) == "edit the text"
