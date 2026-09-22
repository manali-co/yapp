"""Screen actions: read the frontmost app's UI as text through Accessibility, let Jev pick.

Nothing here is per app. Menus are cached per app for a few minutes; the focused window's
controls are walked on every request. AX calls sit behind small functions so tests inject
fakes for perception and execution.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz
from typesafe_sdk import Choice, Noul

from yapp.jev import Jev
from yapp.types import Result

PRESSABLE = {
    "AXButton",
    "AXLink",
    "AXTab",
    "AXRadioButton",
    "AXCheckBox",
    "AXPopUpButton",
    "AXMenuButton",
    "AXMenuItem",
    "AXDisclosureTriangle",
}
TYPEABLE = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}
INTERESTING = PRESSABLE | TYPEABLE | {"AXSlider", "AXIncrementor"}
MAX_NODES = 3000
MAX_SECONDS = 0.5
MENU_TTL = 300.0
MOD_NAMES = {0: "⌘", 1: "⇧⌘", 2: "⌥⌘", 3: "⌥⇧⌘", 4: "⌃⌘", 8: "⌃⌥⌘", 12: "⌃⌥⌘"}
VERBS = r"(?:search for|search|look up|google|type|enter|write|find|say)"


def normalize_label(s: str) -> str:
    s = s.replace("…", "").replace("...", "").replace("…", "")
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class Target:
    key: str
    kind: str  # "menu" | "control"
    role: str
    label: str
    path: str  # "File › New Tab" for menus, window title for controls
    shortcut: str = ""
    ref: Any = field(default=None, compare=False, repr=False)

    @property
    def typeable(self) -> bool:
        return self.role in TYPEABLE

    def describe(self) -> str:
        if self.kind == "menu":
            return f"menu: {self.path}" + (f" ({self.shortcut})" if self.shortcut else "")
        return f"{self.role[2:]}: {self.label}"

    def criteria(self) -> dict[str, Any]:
        """Structured option for Jev: what it is, plus phrasings a person would use."""
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", self.label)]
        base = " ".join(words)
        if self.typeable:
            what = f"Text field '{self.label}' in this window: type here"
            examples = [f"type in {base}", "search for something", f"enter text in {base}"]
        elif self.kind == "menu":
            what = f"Menu command {self.path}" + (
                f", shortcut {self.shortcut}" if self.shortcut else ""
            )
            examples = [base, f"{base} please", f"do {base}"]
        else:
            what = f"{self.role[2:]} '{self.label}' in this window: click it"
            examples = [base, f"click {base}", f"press {base}"]
        return {"what": what, "examples": [e for e in examples if e.strip()][:4]}


# ---------------------------------------------------------------- perception (AX)


def _attr(el: Any, name: str) -> Any:
    from ApplicationServices import AXUIElementCopyAttributeValue

    err, value = AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def frontmost_app_name() -> str:
    from AppKit import NSWorkspace

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.localizedName()) if app is not None else "unknown"


def app_element(name: str | None) -> tuple[Any, str]:
    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCreateApplication

    ws = NSWorkspace.sharedWorkspace()
    app = None
    if name:
        for a in ws.runningApplications():
            if name.lower() in (a.localizedName() or "").lower():
                app = a
                break
    if app is None:
        app = ws.frontmostApplication()
    return AXUIElementCreateApplication(app.processIdentifier()), str(app.localizedName())


def ax_menus(app_name: str) -> list[Target]:
    app, _ = app_element(app_name)
    out: list[Target] = []
    bar = _attr(app, "AXMenuBar")
    if bar is None:
        return out

    def walk(el: Any, trail: list[str], depth: int) -> None:
        for child in _attr(el, "AXChildren") or []:
            role = _attr(child, "AXRole") or ""
            title = normalize_label(_attr(child, "AXTitle") or "")
            if role == "AXMenu":
                walk(child, trail, depth)
                continue
            if not title:
                continue
            kids = _attr(child, "AXChildren") or []
            if kids and depth < 3:
                walk(child, [*trail, title], depth + 1)
            elif role == "AXMenuItem" and _attr(child, "AXEnabled") is not False:
                cmd = _attr(child, "AXMenuItemCmdChar") or ""
                mods = _attr(child, "AXMenuItemCmdModifiers")
                shortcut = f"{MOD_NAMES.get(int(mods or 0), '⌘')}{cmd}" if cmd else ""
                path = " › ".join([*trail, title])
                out.append(Target(f"m{len(out)}", "menu", role, title, path, shortcut, child))

    walk(bar, [], 0)
    return out


def ax_controls(app_name: str) -> list[Target]:
    app, _ = app_element(app_name)
    out: list[Target] = []
    win = _attr(app, "AXFocusedWindow") or (_attr(app, "AXWindows") or [None])[0]
    if win is None:
        return out
    title = normalize_label(_attr(win, "AXTitle") or "")
    seen = 0
    started = time.perf_counter()
    stack = [win]
    while stack and seen < MAX_NODES and time.perf_counter() - started < MAX_SECONDS:
        el = stack.pop()
        seen += 1
        role = _attr(el, "AXRole") or ""
        if role == "AXSecureTextField":
            continue
        if role in INTERESTING:
            label = normalize_label(_attr(el, "AXTitle") or _attr(el, "AXDescription") or "")
            if label:
                out.append(Target(f"c{len(out)}", "control", role, label, title, "", el))
        stack.extend(_attr(el, "AXChildren") or [])
    return out


def ax_press(t: Target) -> bool:
    from ApplicationServices import AXUIElementPerformAction

    return bool(AXUIElementPerformAction(t.ref, "AXPress") == 0)


def ax_focus(t: Target) -> bool:
    from ApplicationServices import AXUIElementSetAttributeValue

    return bool(AXUIElementSetAttributeValue(t.ref, "AXFocused", True) == 0)


# ---------------------------------------------------------------- narrowing


def score(words: str, t: Target) -> float:
    by_label = fuzz.token_set_ratio(words, t.label)
    by_path = fuzz.partial_ratio(words, t.path) * 0.9 if t.kind == "menu" else 0.0
    return float(max(by_label, by_path))


def narrow(targets: list[Target], words: str, limit: int) -> list[Target]:
    ranked = sorted(targets, key=lambda t: (-score(words, t), t.key))[:limit]
    return sorted(ranked, key=lambda t: (t.kind, int(t.key[1:])))


class Perceiver:
    def __init__(
        self,
        read_menus: Callable[[str], list[Target]] = ax_menus,
        read_controls: Callable[[str], list[Target]] = ax_controls,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = MENU_TTL,
    ) -> None:
        self._menus = read_menus
        self._controls = read_controls
        self._clock = clock
        self._ttl = ttl
        self._cache: dict[str, tuple[float, list[Target]]] = {}

    def menus(self, app: str) -> list[Target]:
        hit = self._cache.get(app)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        items = self._menus(app)
        self._cache[app] = (self._clock(), items)
        return items

    def targets(self, app: str, words: str, limit: int = 30) -> list[Target]:
        return narrow(self.menus(app) + self._controls(app), words, limit)


# ---------------------------------------------------------------- decision


def spans(words: str) -> list[str]:
    """Candidate texts to type, cut from the spoken words. Jev chooses; nothing is generated."""
    out: list[str] = [q.strip() for q in re.findall(r"[\"“](.+?)[\"”]", words)]
    m = re.search(rf"\b{VERBS}\b[:,]?\s+(.+)$", words, re.I)
    if m:
        out.append(m.group(1).strip().strip('"“”'))
    out.append(words.strip())
    seen: list[str] = []
    for s in out:
        if s and s not in seen:
            seen.append(s)
    return seen


@dataclass(frozen=True)
class ScreenDecision:
    target: Target | None
    operation: str  # press | type | none
    text: str
    submit: float
    confidence: float
    probabilities: dict[str, float]
    latency_ms: int


def fits(operation: str, target: Target | None) -> bool:
    if target is None or operation == "none":
        return False
    if operation == "press":
        return target.role in PRESSABLE
    if operation == "type":
        return target.typeable
    return False


def decide(words: str, targets: list[Target], jev: Jev) -> ScreenDecision:
    criteria: dict[str, Any] = {t.key: t.criteria() for t in targets}
    criteria["none"] = {
        "what": "Nothing listed fits: the user wants another app, or is not giving a command",
        "examples": ["open safari", "what time is it", "never mind", "switch to notes"],
    }
    candidates = spans(words)
    text_criteria = {f"s{i}": s for i, s in enumerate(candidates)}
    resp = jev.ask(
        {"instruction": words, "app_targets": [t.describe() for t in targets]},
        {
            "target": Choice(
                instructions="Which menu command or on-screen control does the user mean?",
                criteria=criteria,
            ),
            "operation": Choice(
                instructions="What should be done with the chosen target?",
                criteria={
                    "press": "Click or activate it: buttons, menu commands, links, tabs",
                    "type": "Put the spoken text into it: text fields, search fields",
                    "none": "Nothing",
                },
            ),
            "text": Choice(
                instructions=(
                    "If text should be typed, which of these spans of the user's words is it?"
                ),
                criteria=text_criteria,
            ),
            "submit": Noul(
                instructions=(
                    "After typing, the user wants it submitted (a search, an address, 'go')"
                ),
                criteria={
                    "true": {
                        "examples": ["search for cats", "go to youtube", "look up the weather"]
                    },
                    "false": {"examples": ["type hello there", "write dear sam"]},
                },
            ),
        },
    )
    tgt = resp.choice("target")
    op = resp.choice("operation").key
    text_key = resp.choice("text").key
    by = {t.key: t for t in targets}
    return ScreenDecision(
        target=by.get(tgt.key),
        operation=op,
        text=text_criteria.get(text_key, candidates[-1] if candidates else ""),
        submit=resp.noul("submit"),
        confidence=tgt.confidence,
        probabilities=tgt.probabilities,
        latency_ms=resp.latency_ms,
    )


# ---------------------------------------------------------------- execution


class Screen:
    """perceive -> decide -> act for one spoken instruction against the frontmost app."""

    def __init__(
        self,
        jev: Jev,
        perceiver: Perceiver | None = None,
        *,
        frontmost: Callable[[], str] = frontmost_app_name,
        press: Callable[[Target], bool] = ax_press,
        focus: Callable[[Target], bool] = ax_focus,
        type_text: Callable[[str], Result] | None = None,
        press_key: Callable[[str], Result] | None = None,
        threshold: float = 0.60,
        log: Callable[[str], None] = lambda s: None,
    ) -> None:
        self.jev = jev
        self.perceiver = perceiver or Perceiver()
        self.frontmost = frontmost
        self.press = press
        self.focus = focus
        self.type_text = type_text
        self.press_key = press_key
        self.threshold = threshold
        self.log = log
        self.last: ScreenDecision | None = None

    def run(self, words: str) -> Result:
        app = self.frontmost()
        t0 = time.perf_counter()
        targets = self.perceiver.targets(app, words)
        ms = (time.perf_counter() - t0) * 1000
        self.log(f"screen: {app}: {len(targets)} candidates in {ms:.0f} ms")
        if not targets:
            return Result(False, "I don't see anything to act on here")
        d = decide(words, targets, self.jev)
        self.last = d
        top = sorted(d.probabilities.items(), key=lambda kv: -kv[1])[:3]
        by = {t.key: t.describe() for t in targets}
        self.log(
            f"screen: jev {d.latency_ms} ms → {d.operation} "
            f"{d.target.describe() if d.target else 'none'} conf {d.confidence:.2f}; "
            + ", ".join(f"{by.get(k, k)} {p:.2f}" for k, p in top)
        )
        if d.target is None or d.confidence < self.threshold or not fits(d.operation, d.target):
            return Result(False, "I don't see that here")
        if d.operation == "press":
            ok = self.press(d.target)
            return Result(ok, f"pressed {d.target.describe()}" if ok else "couldn't press that")
        if self.type_text is None:
            return Result(False, "typing is not available")
        if not self.focus(d.target):
            return Result(False, "couldn't focus the field")
        if self.press_key:
            self.press_key("cmd+a")
        r = self.type_text(d.text)
        if r.ok and d.submit >= 0.5 and self.press_key:
            self.press_key("enter")
        return Result(r.ok, f"typed '{d.text}' into {d.target.label}" if r.ok else r.message)


# ---------------------------------------------------------------- spike CLI


def run_ax(app_name: str | None, phrases: list[str], model: str, out_path: str) -> int:
    with open(out_path, "a") as f:

        def p(line: str = "") -> None:
            f.write(line + "\n")
            f.flush()

        _, name = app_element(app_name)
        perceiver = Perceiver()
        t0 = time.perf_counter()
        menus = perceiver.menus(name)
        controls = ax_controls(name)
        p(
            f"=== {name}: {len(menus)} menu items, {len(controls)} labelled controls "
            f"in {(time.perf_counter() - t0) * 1000:.0f} ms ==="
        )
        jev = Jev(model=model)
        for ph in phrases:
            cands = narrow(menus + controls, ph, 30)
            d = decide(ph, cands, jev)
            by = {t.key: t.describe() for t in cands}
            p(
                f'\n"{ph}" -> {d.operation} {d.target.describe() if d.target else "none"}'
                f'  text="{d.text}" submit={d.submit:.2f} conf={d.confidence:.2f}'
                f" jev={d.latency_ms} ms"
            )
            for k, v in sorted(d.probabilities.items(), key=lambda kv: -kv[1])[:3]:
                p(f"    {v:.2f}  {by.get(k, k)}")
    return 0
