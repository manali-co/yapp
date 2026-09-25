"""Confidence gates. Pure. Yapp acts or stays quiet; it never asks."""

from __future__ import annotations

from yapp.config import Thresholds
from yapp.types import Decision, Intent, Outcome, Verdict


def decide(
    d: Decision, t: Thresholds, *, dictating: bool = False, has_last: bool = False
) -> Verdict:
    if dictating and d.ends_dictation < t.ends_dictation:
        return Verdict(Outcome.IGNORE, "dictating")
    if not dictating and d.is_addressed < t.addressed:
        return Verdict(Outcome.IGNORE, f"not talking to me ({d.is_addressed:.2f})")
    if d.intent == Intent.NONE:
        return Verdict(Outcome.IGNORE, "not an instruction")
    if d.is_complete < t.complete:
        return Verdict(Outcome.WAIT, f"waiting: complete {d.is_complete:.2f} < {t.complete}")
    c = d.intent_confidence
    match d.intent:
        case Intent.OPEN_APP:
            if d.app is None:
                return Verdict(Outcome.IGNORE, "no app matched")
            return _gate(c, t.open_app, f"open {d.app.name}")
        case Intent.TYPE_TEXT:
            return _gate(c, t.type_text, "dictate")
        case Intent.OPEN_FILE:
            if not d.file_query:
                return Verdict(Outcome.IGNORE, "no file named")
            return _gate(c, t.open_file, f"open file '{d.file_query}'")
        case Intent.PRESS_KEY:
            if d.key_combo is None:
                return Verdict(Outcome.IGNORE, "no shortcut matched")
            return _gate(c, t.press_key, f"press {d.key_combo}")
        case Intent.UNDO:
            if not has_last:
                return Verdict(Outcome.IGNORE, "nothing to undo")
            return _gate(c, t.undo, "undo")
        case Intent.SCREEN:
            return _gate(c, t.screen, f"screen '{d.tail}'")
        case Intent.CLEANUP:
            return _gate(c, t.cleanup, "cleanup")
    return Verdict(Outcome.IGNORE, "unhandled intent")


def _gate(conf: float, threshold: float, action: str) -> Verdict:
    if conf >= threshold:
        return Verdict(Outcome.EXECUTE, f"{action} ({conf:.2f} ≥ {threshold})")
    return Verdict(Outcome.IGNORE, f"{action} below threshold ({conf:.2f} < {threshold})")
