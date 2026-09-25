"""Transcript tail -> Decision. The only module that designs Jev questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml
from typesafe_sdk import Choice, Noul, Question

from yapp.catalog import narrow
from yapp.config import Config
from yapp.jev import JevLike
from yapp.types import App, Decision, Intent

Examples = dict[str, list[str]]
CONJUNCTIONS = {"and", "then", "also"}
TYPE_VERB = re.compile(r"^(type|write|enter|say)\b[:,]?\s*", re.I)
FILE_VERB = re.compile(r"^(open|find|show)\b\s*(my|the)?\s*", re.I)
FILE_TRAIL = re.compile(r"\s*\b(file|document|doc|pdf)$", re.I)
KEY_COMBOS = ("cmd+s", "cmd+c", "cmd+v", "cmd+a", "cmd+w", "enter", "escape")


@dataclass(frozen=True)
class Context:
    apps: list[App]
    frontmost_app: str
    already_done: list[str]
    dictating: bool
    examples: Examples = field(default_factory=dict)
    negatives: Examples = field(default_factory=dict)


def _load_yaml() -> dict[str, Any]:
    text = resources.files("yapp").joinpath("questions.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(text)
    return data


QUESTIONS = _load_yaml()


def extract_text(tail: str) -> str:
    return TYPE_VERB.sub("", tail, count=1).strip()


def extract_file_query(tail: str) -> str:
    return FILE_TRAIL.sub("", FILE_VERB.sub("", tail, count=1)).strip()


def strip_leading_conjunctions(tail: str) -> str:
    words = tail.split()
    while words and words[0] in CONJUNCTIONS:
        words.pop(0)
    return " ".join(words)


def consumed_for(tail: str, intent: Intent) -> int:
    words = tail.split()
    lead = 0
    while lead < len(words) and words[lead] in CONJUNCTIONS:
        lead += 1
    if intent == Intent.TYPE_TEXT:
        return lead + 1  # the verb only; dictation types the rest
    if intent == Intent.CLEANUP:
        return len(words)
    for i in range(lead + 1, len(words)):
        if words[i] in CONJUNCTIONS:
            return i
    return len(words)


def spoken_forms(name: str) -> list[str]:
    """How a name is said: 'TextEdit' -> ['textedit', 'text edit']; 'Google Chrome' -> [...]."""
    lower = name.lower()
    split = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()
    return [lower] if split == lower else [lower, split]


def canonical_app_names(text: str, apps: list[App]) -> str:
    """Whisper writes 'text edit' for TextEdit; say it the way the catalog spells it.

    Only the words Jev reads change; word counts used for the transcript cursor do not.
    """
    out = text
    for app in apps:
        forms = spoken_forms(app.name)
        if len(forms) == 2 and re.search(rf"\b{re.escape(forms[1])}\b", out):
            out = re.sub(rf"\b{re.escape(forms[1])}\b", forms[0], out)
    return out


def _app_option(app: App, learned: list[str], negatives: list[str]) -> dict[str, Any]:
    words = [w for w in app.name.lower().split() if len(w) > 1]
    forms = spoken_forms(app.name)
    generated = [f"open {f}" for f in forms] + [f"open {w}" for w in words[:1]]
    generated += [f"switch to {forms[-1]}"]
    option: dict[str, Any] = {
        "what": app.description,
        "examples": (learned[-5:] + generated)[:8],
    }
    if negatives:
        option["not_for"] = "; ".join(negatives[-3:])
    return option


def _with_learned_intent_examples(
    criteria: dict[str, Any], learned: Examples, extra: list[str] | None = None
) -> dict[str, Any]:
    """Phrases learned for app options are also open_app phrasings; tell the intent question."""
    phrases = [p for key, ps in learned.items() if key not in KEY_COMBOS for p in ps[-2:]]
    phrases += extra or []
    if not phrases:
        return criteria
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in criteria.items()}
    open_app = out["open_app"]
    open_app["examples"] = (phrases + list(open_app.get("examples", [])))[:10]
    return out


def build_questions(ctx: Context, tail: str = "", limit: int = 60) -> dict[str, Question]:
    q = QUESTIONS
    if tail:
        apps = narrow(ctx.apps, tail, limit)
    else:
        apps = sorted(ctx.apps, key=lambda a: a.name)[:limit]
    app_criteria: dict[str, Any] = {
        a.key: _app_option(a, ctx.examples.get(a.key, []), ctx.negatives.get(a.key, []))
        for a in apps
    }
    app_criteria["unsure"] = "None of these applications"
    # The intent question must know how the apps on THIS Mac are said ("open text edit").
    catalog_phrases = (
        {f"open {form}" for a in apps[:3] for form in spoken_forms(a.name)} if tail else set()
    )
    intent_criteria = _with_learned_intent_examples(
        q["intent"]["criteria"], ctx.examples, sorted(catalog_phrases)
    )
    return {
        "intent": Choice(instructions=q["intent"]["instructions"], criteria=intent_criteria),
        "app": Choice(instructions="Which application does the user mean?", criteria=app_criteria),
        "key_combo": Choice(
            instructions=q["key_combo"]["instructions"], criteria=q["key_combo"]["criteria"]
        ),
        "is_complete": Noul(
            instructions=q["is_complete"]["instructions"], criteria=q["is_complete"]["criteria"]
        ),
        "ends_dictation": Noul(
            instructions=q["ends_dictation"]["instructions"],
            criteria=q["ends_dictation"]["criteria"],
        ),
        "is_addressed": Noul(
            instructions=q["is_addressed"]["instructions"],
            criteria=q["is_addressed"]["criteria"],
        ),
    }


def classify(tail: str, ctx: Context, jev: JevLike, cfg: Config) -> Decision:
    state = {
        "instruction_so_far": canonical_app_names(strip_leading_conjunctions(tail), ctx.apps),
        "already_done": ctx.already_done[-3:],
        "frontmost_app": ctx.frontmost_app,
        "dictating": ctx.dictating,
        # Names on this Mac that sound like the words said ("text edit" -> TextEdit).
        "installed_apps_like_these_words": [a.name for a in narrow(ctx.apps, tail, 3)],
    }
    questions = build_questions(ctx, tail, cfg.catalog_limit)
    resp = jev.ask(state, questions)
    intent_r = resp.choice("intent")
    intent = Intent(intent_r.key)
    app_r = resp.choice("app")
    by_key = {a.key: a for a in ctx.apps}
    app = by_key.get(app_r.key) if intent == Intent.OPEN_APP else None
    combo_r = resp.choice("key_combo")
    is_key = intent == Intent.PRESS_KEY and combo_r.key != "unsure"
    return Decision(
        tail=tail,
        intent=intent,
        intent_confidence=intent_r.confidence,
        intent_probabilities=intent_r.probabilities,
        app=app,
        app_confidence=app_r.confidence if intent == Intent.OPEN_APP else None,
        text=extract_text(tail) if intent == Intent.TYPE_TEXT else None,
        key_combo=combo_r.key if is_key else None,
        file_query=extract_file_query(tail) if intent == Intent.OPEN_FILE else None,
        is_complete=resp.noul("is_complete"),
        ends_dictation=resp.noul("ends_dictation"),
        is_addressed=resp.noul("is_addressed"),
        consumed_words=consumed_for(tail, intent),
        latency_ms=resp.latency_ms,
        raw=resp.raw,
    )
