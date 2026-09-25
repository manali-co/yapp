from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yapp.ax import (
    Perceiver,
    Screen,
    ScreenDecision,
    Target,
    decide,
    fits,
    merge_equivalents,
    narrow,
    normalize_label,
    spans,
)
from yapp.semantic import EmbeddingCache, rank_fusion
from yapp.types import Result

MENU = [
    Target("m0", "menu", "AXMenuItem", "New Tab", "File › New Tab", "⌘T"),
    Target("m1", "menu", "AXMenuItem", "Find", "Edit › Find › Find", "⌘F"),
    Target("m2", "menu", "AXMenuItem", "Find Next", "Edit › Find › Find Next", "⌘G"),
    Target("m3", "menu", "AXMenuItem", "Zoom In", "View › Zoom In", "⌘+"),
]
CTRL = [
    Target("c0", "control", "AXButton", "New Tab", "Chrome"),
    Target("c1", "control", "AXTextField", "Address and search bar", "Chrome"),
]


def test_normalize_label() -> None:
    assert normalize_label("Find…") == "Find"
    assert normalize_label("  New   Tab ") == "New Tab"


def test_criteria_are_structured_and_generic() -> None:
    c = MENU[0].criteria()
    assert c["what"].startswith("Menu command File › New Tab") and "⌘T" in c["what"]
    assert c["examples"] == ["new tab"]
    assert "typing goes here" in CTRL[1].criteria()["what"]
    assert MENU[0].phrasing() == "New Tab (File menu)"
    assert CTRL[1].phrasing() == "Address and search bar (textfield)"


def test_narrow_scores_by_path_and_label_case_insensitively() -> None:
    junk = Target(
        "m9",
        "menu",
        "AXMenuItem",
        "Show Messages in Finder",
        "Apple › Recent Items › Show Messages in Finder",
    )
    top = narrow(MENU + CTRL + [junk], "find on page", 2)
    assert {t.key for t in top} == {"m1", "m2"}
    top = narrow(MENU + CTRL, "new tab", 2)
    assert top[0].key == "m0" and "c0" not in {t.key for t in top}  # button merged into menu


def test_spans() -> None:
    assert spans("search for fable five") == ["fable five", "search for fable five"]
    assert spans('type "hello there"')[0] == "hello there"
    assert spans("zoom in") == ["zoom in"]


def test_fits() -> None:
    assert fits("press", MENU[0]) and not fits("type", MENU[0])
    assert fits("type", CTRL[1]) and not fits("press", CTRL[1])
    assert not fits("press", None) and not fits("none", CTRL[0])


def test_perceiver_caches_menus_and_walks_controls_each_time() -> None:
    calls = {"menus": 0, "controls": 0}
    now = [0.0]

    def menus(app: str) -> list[Target]:
        calls["menus"] += 1
        return MENU

    def controls(app: str) -> list[Target]:
        calls["controls"] += 1
        return CTRL

    p = Perceiver(menus, controls, clock=lambda: now[0], ttl=300)
    p.targets("Chrome", "new tab")
    p.targets("Chrome", "zoom in")
    assert calls == {"menus": 1, "controls": 2}
    now[0] = 301
    p.targets("Chrome", "zoom in")
    assert calls["menus"] == 2


@dataclass
class FakeChoice:
    key: str
    confidence: float
    probabilities: dict[str, float]


class FakeResp:
    def __init__(
        self,
        target: str,
        conf: float,
        op: str,
        text: str,
        submit: float,
        status: str = "continue",
        status_conf: float = 0.9,
    ) -> None:
        self._t, self._c, self._op, self._text, self._s = target, conf, op, text, submit
        self._status, self._sc = status, status_conf
        self.latency_ms = 200

    def choice(self, name: str) -> FakeChoice:
        if name == "target":
            return FakeChoice(self._t, self._c, {self._t: self._c})
        if name == "operation":
            return FakeChoice(self._op, 0.9, {})
        if name == "status":
            return FakeChoice(self._status, self._sc, {})
        return FakeChoice(self._text, 0.9, {})

    def noul(self, name: str) -> float:
        return self._s


class FakeJev:
    def __init__(self, *resps: FakeResp) -> None:
        self.resps = list(resps)
        self.seen: dict[str, Any] = {}
        self.states: list[Any] = []

    def ask(self, state: Any, questions: Any) -> FakeResp:
        self.seen = {"state": state, "questions": questions}
        self.states.append(state)
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]


def test_decide_maps_answers() -> None:
    jev = FakeJev(FakeResp("c1", 0.8, "type", "s0", 0.9))
    d = decide("search for fable five", MENU + CTRL, jev)  # type: ignore[arg-type]
    assert d.target is not None and d.target.key == "c1"
    assert d.operation == "type" and d.text == "fable five" and d.submit == 0.9
    assert set(jev.seen["questions"]) == {"status", "target", "operation", "text", "submit"}
    assert "none" in jev.seen["questions"]["target"].criteria


def make_screen(
    *resps: FakeResp,
    summaries: list[str] | None = None,
    guard: Callable[[str, str], bool] | None = None,
) -> tuple[Screen, list[str]]:
    log: list[str] = []
    seq = list(summaries or ["app Chrome"])

    def press(t: Target) -> bool:
        log.append(f"press:{t.key}")
        return True

    def focus(t: Target) -> bool:
        log.append(f"focus:{t.key}")
        return True

    def type_text(text: str) -> Result:
        log.append(f"type:{text}")
        return Result(True, "ok")

    def press_key(k: str) -> Result:
        log.append(f"key:{k}")
        return Result(True, k)

    def summary(app: str) -> str:
        return seq.pop(0) if len(seq) > 1 else seq[0]

    s = Screen(
        FakeJev(*resps),  # type: ignore[arg-type]
        Perceiver(lambda a: MENU, lambda a: CTRL, clock=lambda: 0.0, embed=lambda s: None),
        frontmost=lambda: "Chrome",
        summary=summary,
        press=press,
        focus=focus,
        type_text=type_text,
        press_key=press_key,
        settle=lambda s: None,
        guard=guard,
    )
    return s, log


def test_screen_presses_menu_item_then_stops_when_done() -> None:
    s, log = make_screen(
        FakeResp("m3", 0.95, "press", "s0", 0.1),
        FakeResp("none", 0.1, "none", "s0", 0.1, status="done"),
        summaries=["app Chrome window 'a'", "app Chrome window 'a' zoomed"],
    )
    r = s.run("zoom in")
    assert r.ok and log == ["press:m3"] and r.message == "done after 1 step(s)"
    assert s.history == ["pressed menu: View › Zoom In (⌘+) → now app Chrome window 'a' zoomed"]


def test_screen_loops_until_done_and_sends_history() -> None:
    s, log = make_screen(
        FakeResp("m3", 0.95, "press", "s0", 0.1),
        FakeResp("m3", 0.95, "press", "s0", 0.1),
        FakeResp("none", 0.1, "none", "s0", 0.1, status="done"),
        summaries=["a", "b", "c", "d"],
    )
    r = s.run("make it much bigger")
    assert r.ok and log == ["press:m3", "press:m3"] and "2 step" in r.message
    assert s.jev.states[2]["steps_done_so_far"] == s.history  # type: ignore[attr-defined]
    assert len(s.history) == 2


def test_snapshot_diff_counts_as_change() -> None:
    seq = [CTRL, CTRL + [Target("c9", "control", "AXButton", "Undo zoom", "Chrome")]]
    calls = {"n": 0}

    def controls(app: str) -> list[Target]:
        out = seq[min(calls["n"], 1)]
        calls["n"] += 1
        return out

    log: list[str] = []

    def press(t: Target) -> bool:
        log.append(t.key)
        return True

    s = Screen(
        FakeJev(
            FakeResp("m3", 0.95, "press", "s0", 0.1),
            FakeResp("none", 0.1, "none", "s0", 0.1, status="done"),
        ),  # type: ignore[arg-type]
        Perceiver(lambda a: MENU, controls, clock=lambda: 0.0, embed=lambda s: None),
        frontmost=lambda: "Chrome",
        summary=lambda app: "same",
        press=press,
        settle=lambda s: None,
    )
    r = s.run("zoom in")
    assert r.ok and s.history == [
        "pressed menu: View › Zoom In (⌘+) → 1 on-screen controls changed"
    ]


def test_screen_stops_after_two_unchanged_steps_and_on_budget() -> None:
    s, log = make_screen(FakeResp("m3", 0.95, "press", "s0", 0.1), summaries=["same"])
    r = s.run("zoom in")
    assert r.ok and log == ["press:m3", "press:m3"]  # second unchanged step ends it
    s, log = make_screen(
        FakeResp("m3", 0.95, "press", "s0", 0.1), summaries=[str(i) for i in range(20)]
    )
    s.max_steps = 3
    r = s.run("zoom in")
    assert log == ["press:m3"] * 3 and "stopped after 3" in r.message


def test_screen_blocked_stops_without_acting() -> None:
    s, log = make_screen(FakeResp("none", 0.1, "none", "s0", 0.1, status="blocked"))
    r = s.run("fly to the moon")
    assert not r.ok and log == []


def test_screen_types_and_submits() -> None:
    s, log = make_screen(
        FakeResp("c1", 0.8, "type", "s0", 0.9),
        FakeResp("none", 0.1, "none", "s0", 0.1, status="done"),
        summaries=["a", "b"],
    )
    r = s.run("search for fable five")
    assert r.ok and log == ["focus:c1", "key:cmd+a", "type:fable five", "key:enter"]


def test_screen_stays_quiet_below_threshold_or_on_mismatch() -> None:
    s, log = make_screen(FakeResp("c1", 0.4, "type", "s0", 0.9))
    assert not s.run("search for fable five").ok and log == []
    s, log = make_screen(FakeResp("m0", 0.9, "type", "s0", 0.1))  # type on a menu item
    assert not s.run("new tab").ok and log == []


def test_rank_fusion_prefers_items_good_under_any_signal() -> None:
    assert rank_fusion([["a", "b", "c"], ["c", "a", "b"]])[0] == "a"
    assert rank_fusion([["x", "y"], ["y", "x"]]) == ["x", "y"]  # tie broken by key
    assert rank_fusion([["a"], ["z"]])[:2] == ["a", "z"]


def test_narrow_uses_semantic_rank_when_lexical_misses() -> None:
    import numpy as np

    vecs = {
        "get rid of this tab": np.array([1.0, 0.0]),
        MENU[0].phrasing(): np.array([0.0, 1.0]),  # New Tab
        MENU[3].phrasing(): np.array([0.1, 0.9]),  # Zoom In
    }
    close = Target("m7", "menu", "AXMenuItem", "Close Tab", "File › Close Tab", "⌘W")
    vecs[close.phrasing()] = np.array([0.95, 0.05])
    emb = EmbeddingCache(lambda s: vecs.get(s, np.array([0.5, 0.5])))
    top = narrow([MENU[0], MENU[3], close], "get rid of this tab", 1, emb)
    assert [t.key for t in top] == ["m7"]


def test_merge_equivalents_keeps_menu_over_same_named_button() -> None:
    out = merge_equivalents(MENU + CTRL)
    labels = [(t.kind, t.label) for t in out]
    assert ("control", "New Tab") not in labels and ("menu", "New Tab") in labels
    assert ("control", "Address and search bar") in labels  # text fields are never merged


def test_unsure_repeat_of_the_same_action_after_a_change_stops() -> None:
    """A toggle (Full Screen) flips back if pressed twice; an unsure 'continue' must not."""
    titles = iter(["windowed", "full", "windowed", "full", "windowed"])
    log: list[str] = []

    def press(t: Target) -> bool:
        log.append(t.key)
        return True

    s = Screen(
        FakeJev(  # type: ignore[arg-type]
            *[FakeResp("m3", 0.95, "press", "s0", 0.1, status="continue", status_conf=0.4)] * 6
        ),
        Perceiver(lambda a: MENU, lambda a: [], clock=lambda: 0.0, embed=lambda s: None),
        frontmost=lambda: "Chrome",
        summary=lambda app: next(titles),
        press=press,
        settle=lambda s: None,
    )
    r = s.run("enter full screen")
    assert r.ok and log == ["m3"] and r.message == "done after 1 step(s)"


def test_guard_sees_the_concrete_step_and_can_stop_the_loop() -> None:
    judged: list[tuple[str, str]] = []

    def guard(action: str, screen: str) -> bool:
        judged.append((action, screen))
        return "Zoom" not in action

    s, log = make_screen(
        FakeResp("m3", 0.95, "press", "s0", 0.1),
        summaries=["app Chrome window 'a'"],
        guard=guard,
    )
    r = s.run("zoom in")
    assert not r.ok and r.message == "not approved" and log == []
    assert judged == [("press View › Zoom In in Chrome", "app Chrome window 'a'")]


def test_describe_typing_step_names_field_text_and_submit() -> None:
    t = Target("c1", "control", "AXTextField", "Address and search bar", "Address and search bar")
    d = ScreenDecision(t, "type", "cats", 0.9, 0.9, {}, 1)
    assert Screen._describe(d, "Google Chrome") == (
        "type 'cats' into Address and search bar in Google Chrome and submit"
    )
