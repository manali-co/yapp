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

from yapp.jev import Jev, JevLike
from yapp.semantic import Embedder, EmbeddingCache, cosine, rank_fusion
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

    def phrasing(self) -> str:
        """What this target is, in plain words, for embedding. Nothing invented."""
        if self.kind == "menu":
            return f"{self.label} ({self.path.rsplit(' › ', 1)[0]} menu)"
        return f"{self.label} ({self.role[2:].lower()})"

    def criteria(self) -> dict[str, Any]:
        """Structured option for Jev: what it is and where it lives. The label is the example."""
        if self.kind == "menu":
            what = f"Menu command {self.path}" + (
                f", shortcut {self.shortcut}" if self.shortcut else ""
            )
        elif self.typeable:
            what = f"Text field '{self.label}' in this window; typing goes here"
        else:
            what = f"{self.role[2:]} '{self.label}' in this window"
        return {"what": what, "examples": [self.label.lower()]}


# ---------------------------------------------------------------- perception (AX)


def _attr(el: Any, name: str) -> Any:
    from ApplicationServices import AXUIElementCopyAttributeValue

    err, value = AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def refresh_workspace() -> None:
    """NSWorkspace learns about activation changes from the main run loop; a script that
    never spins it (yapp --once, yapp tasks) would keep seeing the first app forever."""
    from Foundation import NSDate, NSRunLoop, NSThread

    if NSThread.isMainThread():
        NSRunLoop.mainRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))


def frontmost_app_name() -> str:
    from AppKit import NSWorkspace

    refresh_workspace()
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.localizedName()) if app is not None else "unknown"


def app_element(name: str | None) -> tuple[Any, str]:
    from AppKit import NSWorkspace
    from ApplicationServices import AXUIElementCreateApplication

    refresh_workspace()
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
            value = _attr(el, "AXValue")
            if isinstance(value, (str, int, float)) and str(value) and len(str(value)) < 80:
                label = (
                    f"{label} [{normalize_label(str(value))}]"
                    if label
                    else normalize_label(str(value))
                )
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


def ax_summary(app_name: str) -> str:
    """One line describing the front app's state, for the step history."""
    app, name = app_element(app_name)
    win = _attr(app, "AXFocusedWindow")
    title = normalize_label(_attr(win, "AXTitle") or "") if win is not None else ""
    focused = _attr(app, "AXFocusedUIElement")
    frole = (_attr(focused, "AXRole") or "")[2:] if focused is not None else ""
    flabel = (
        normalize_label(_attr(focused, "AXTitle") or _attr(focused, "AXDescription") or "")
        if focused is not None
        else ""
    )
    parts = [f"app {name}"]
    if title:
        parts.append(f"window '{title}'")
    if frole:
        parts.append(
            f"focus on {frole.lower()} '{flabel}'" if flabel else f"focus on {frole.lower()}"
        )
    return ", ".join(parts)


# ---------------------------------------------------------------- narrowing


def score(words: str, t: Target) -> float:
    w = words.lower()
    by_label = fuzz.token_set_ratio(w, t.label.lower())
    by_path = fuzz.partial_ratio(w, t.path.lower()) * 0.9 if t.kind == "menu" else 0.0
    return float(max(by_label, by_path))


def merge_equivalents(targets: list[Target]) -> list[Target]:
    """A toolbar button and a menu item with the same name are one action; keep the menu one
    (it carries the shortcut) so Jev's vote is not split between two spellings of one thing."""
    menus = {t.label.lower(): t for t in targets if t.kind == "menu"}
    out: list[Target] = []
    seen_menu: set[tuple[str, str]] = set()
    for t in targets:
        if t.kind == "control" and t.role == "AXButton" and t.label.lower() in menus:
            continue
        if t.kind == "menu":
            # The same command listed under two menus (Safari › Clear History… and
            # History › Clear History…) is one action; a split vote would drop it.
            key = (t.label.lower(), t.shortcut)
            if key in seen_menu:
                continue
            seen_menu.add(key)
        out.append(t)
    return out


def narrow(
    targets: list[Target], words: str, limit: int, embeddings: EmbeddingCache | None = None
) -> list[Target]:
    """Keep the `limit` most plausible targets: lexical rank fused with semantic rank."""
    targets = merge_equivalents(targets)
    by_key = {t.key: t for t in targets}
    lexical = [t.key for t in sorted(targets, key=lambda t: (-score(words, t), t.key))]
    rankings = [lexical]
    if embeddings is not None:
        q = embeddings.get(words)
        if q is not None:
            sims = {t.key: cosine(q, embeddings.get(t.phrasing())) for t in targets}
            rankings.append(sorted(sims, key=lambda key: (-sims[key], key)))
    keep = [by_key[k] for k in rank_fusion(rankings)[:limit]]
    return sorted(keep, key=lambda t: (t.kind, int(t.key[1:])))


class Perceiver:
    def __init__(
        self,
        read_menus: Callable[[str], list[Target]] = ax_menus,
        read_controls: Callable[[str], list[Target]] = ax_controls,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = MENU_TTL,
        embed: Embedder | None = None,
    ) -> None:
        self._menus = read_menus
        self._controls = read_controls
        self._clock = clock
        self._ttl = ttl
        self._cache: dict[str, tuple[float, list[Target]]] = {}
        self.last_controls: list[Target] = []
        if embed is None:
            from yapp.semantic import default_embedder

            embed = default_embedder()
        self.embeddings = EmbeddingCache(embed) if embed is not None else None

    def menus(self, app: str) -> list[Target]:
        hit = self._cache.get(app)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        items = self._menus(app)
        self._cache[app] = (self._clock(), items)
        return items

    def targets(self, app: str, words: str, limit: int = 40) -> list[Target]:
        controls = self._controls(app)
        self.last_controls = controls
        return narrow(self.menus(app) + controls, words, limit, self.embeddings)

    def snapshot(self, app: str) -> set[str]:
        """Fingerprint of what is on screen now: control labels, roles and values."""
        return {f"{t.role}|{t.label}" for t in self._controls(app)}


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
    status: str = "continue"  # continue | done | blocked
    status_confidence: float = 0.0


def fits(operation: str, target: Target | None) -> bool:
    if target is None or operation == "none":
        return False
    if operation == "press":
        return target.role in PRESSABLE
    if operation == "type":
        return target.typeable
    return False


def decide(
    words: str,
    targets: list[Target],
    jev: JevLike,
    history: list[str] | None = None,
    screen: str = "",
) -> ScreenDecision:
    """One step: given the goal, the screen, and what was done so far, what next (or done)?"""
    criteria: dict[str, Any] = {t.key: t.criteria() for t in targets}
    criteria["none"] = {
        "what": "None of the listed targets is the right next step",
    }
    candidates = spans(words)
    text_criteria = {f"s{i}": s for i, s in enumerate(candidates)}
    state = {
        "goal": words,
        "screen_now": screen,
        "steps_done_so_far": history or [],
        "available_targets": [t.describe() for t in targets],
    }
    resp = jev.ask(
        state,
        {
            "status": Choice(
                instructions=(
                    "Looking at steps_done_so_far and screen_now, is the goal already achieved, "
                    "still in progress, or impossible from here?"
                ),
                criteria={
                    "continue": "More steps are needed; a next step is available",
                    "done": "The goal is already achieved; nothing more should be done",
                    "blocked": "The goal cannot be achieved from this screen",
                },
            ),
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
                    "After typing, the user wants it submitted with Return: a search, an "
                    "address, a query, 'go'. Typing prose into a document or a note is not."
                ),
                criteria={
                    "true": {
                        "what": "The typed words are a query or destination to run",
                        "examples": [
                            "search for cats",
                            "search for weather in toronto",
                            "go to youtube",
                            "look up the weather",
                            "google fable five",
                            "find on page login",
                        ],
                    },
                    "false": {
                        "what": "The typed words are content that stays in the field",
                        "examples": ["type hello there", "write dear sam", "enter my address"],
                    },
                },
            ),
        },
    )
    tgt = resp.choice("target")
    op = resp.choice("operation").key
    text_key = resp.choice("text").key
    status = resp.choice("status")
    by = {t.key: t for t in targets}
    target = by.get(tgt.key)
    confidence = tgt.confidence
    if op == "type" and target is not None and not target.typeable:
        # A menu entry that merely contains the words (History › "weather in toronto")
        # cannot be typed into; take Jev's best-ranked field instead of giving up.
        ranked = sorted(tgt.probabilities.items(), key=lambda kv: -kv[1])
        for key, prob in ranked:
            cand = by.get(key)
            if cand is not None and cand.typeable:
                target, confidence = cand, max(prob, confidence * 0.8)
                break
    return ScreenDecision(
        target=target,
        operation=op,
        text=text_criteria.get(text_key, candidates[-1] if candidates else ""),
        submit=resp.noul("submit"),
        confidence=confidence,
        probabilities=tgt.probabilities,
        latency_ms=resp.latency_ms,
        status=status.key,
        status_confidence=status.confidence,
    )


# ---------------------------------------------------------------- execution


class Screen:
    """Goal in; a loop of typed steps until Jev says done (or blocked, or the budget runs out)."""

    def __init__(
        self,
        jev: JevLike,
        perceiver: Perceiver | None = None,
        *,
        frontmost: Callable[[], str] = frontmost_app_name,
        summary: Callable[[str], str] = ax_summary,
        press: Callable[[Target], bool] = ax_press,
        focus: Callable[[Target], bool] = ax_focus,
        type_text: Callable[[str], Result] | None = None,
        press_key: Callable[[str], Result] | None = None,
        threshold: float = 0.60,
        max_steps: int = 6,
        settle: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda s: None,
        guard: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.jev = jev
        self.guard = guard  # (action, screen) -> may act? see guard.py
        self.perceiver = perceiver or Perceiver()
        self.frontmost = frontmost
        self.summary = summary
        self.press = press
        self.focus = focus
        self.type_text = type_text
        self.press_key = press_key
        self.threshold = threshold
        self.max_steps = max_steps
        self.settle = settle
        self.log = log
        self.last: ScreenDecision | None = None
        self.history: list[str] = []

    def run(self, words: str) -> Result:
        self.history = []
        acted = 0
        unchanged = 0
        last_action: tuple[str, str, str] | None = None
        last_changed = False
        for step in range(1, self.max_steps + 1):
            app = self.frontmost()
            before = self.summary(app)
            t0 = time.perf_counter()
            targets = self.perceiver.targets(app, words)
            shot_before = {f"{t.role}|{t.label}" for t in self.perceiver.last_controls}
            ms = (time.perf_counter() - t0) * 1000
            self.log(f"screen step {step}: {before}; {len(targets)} candidates in {ms:.0f} ms")
            if not targets:
                return Result(False, "I don't see anything to act on here")
            d = decide(words, targets, self.jev, self.history, before)
            self.last = d
            top = sorted(d.probabilities.items(), key=lambda kv: -kv[1])[:3]
            by = {t.key: t.describe() for t in targets}
            self.log(
                f"screen step {step}: jev {d.latency_ms} ms → status {d.status} "
                f"({d.status_confidence:.2f}); {d.operation} "
                f"{d.target.describe() if d.target else 'none'} conf {d.confidence:.2f}; "
                + ", ".join(f"{by.get(k, k)} {p:.2f}" for k, p in top)
            )
            if d.status == "done" and d.status_confidence >= self.threshold:
                return Result(True, f"done after {acted} step(s)" if acted else "already done")
            if d.status == "blocked" and d.status_confidence >= self.threshold:
                return Result(False, "I can't do that from here")
            if d.target is None or d.confidence < self.threshold or not fits(d.operation, d.target):
                return Result(
                    acted > 0, f"done after {acted} step(s)" if acted else "I don't see that here"
                )
            action = (d.target.key, d.operation, d.text)
            if action == last_action and last_changed and d.status_confidence < self.threshold:
                # Repeating the exact action that just visibly worked needs a confident
                # "continue" ("make it much bigger"); an unsure one would flip toggles back.
                self.log(f"screen step {step}: unsure repeat of the last action → done")
                return Result(True, f"done after {acted} step(s)")
            if self.guard is not None and not self.guard(self._describe(d, app), before):
                return Result(acted > 0, "not approved")
            r = self._act(d)
            if not r.ok:
                return Result(acted > 0, r.message)
            acted += 1
            last_action = action
            self.settle(0.35)
            app_after = self.frontmost()
            after = self.summary(app_after)
            shot_after = self.perceiver.snapshot(app_after)
            delta = len(shot_before ^ shot_after)
            if after != before:
                change = f"now {after}" + (f"; {delta} controls changed" if delta else "")
            elif delta:
                change = f"{delta} on-screen controls changed"
            else:
                change = "no visible change"
            self.history.append(f"{r.message} → {change}")
            self.log(f"screen step {step}: {self.history[-1]}")
            last_changed = after != before or bool(delta)
            unchanged = 0 if last_changed else unchanged + 1
            if unchanged >= 2:
                return Result(True, f"done after {acted} step(s)")
        return Result(acted > 0, f"stopped after {acted} step(s)")

    @staticmethod
    def _describe(d: ScreenDecision, app: str) -> str:
        """The action as the guard should judge it: operation, target, text, app."""
        assert d.target is not None
        label = d.target.path if d.target.kind == "menu" else d.target.label
        if d.operation == "type":
            tail = " and submit" if d.submit >= 0.5 else ""
            return f"type '{d.text}' into {label} in {app}{tail}"
        return f"press {label} in {app}"

    def _act(self, d: ScreenDecision) -> Result:
        assert d.target is not None
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
            cands = narrow(menus + controls, ph, 40, perceiver.embeddings)
            p(f'\ncandidates for "{ph}": ' + " | ".join(t.label for t in cands))
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
