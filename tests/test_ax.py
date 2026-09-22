from dataclasses import dataclass
from typing import Any

from yapp.ax import (
    Perceiver,
    Screen,
    Target,
    decide,
    fits,
    narrow,
    normalize_label,
    spans,
)
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


def test_criteria_are_structured() -> None:
    c = MENU[0].criteria()
    assert c["what"].startswith("Menu command File › New Tab") and "⌘T" in c["what"]
    assert "new tab" in c["examples"]
    assert "type here" in CTRL[1].criteria()["what"]


def test_narrow_scores_by_path_and_label() -> None:
    top = narrow(MENU + CTRL, "find on page", 2)
    assert {t.key for t in top} == {"m1", "m2"}
    top = narrow(MENU + CTRL, "new tab", 2)
    assert {t.key for t in top} == {"m0", "c0"}


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
    def __init__(self, target: str, conf: float, op: str, text: str, submit: float) -> None:
        self._t, self._c, self._op, self._text, self._s = target, conf, op, text, submit
        self.latency_ms = 200

    def choice(self, name: str) -> FakeChoice:
        if name == "target":
            return FakeChoice(self._t, self._c, {self._t: self._c})
        if name == "operation":
            return FakeChoice(self._op, 0.9, {})
        return FakeChoice(self._text, 0.9, {})

    def noul(self, name: str) -> float:
        return self._s


class FakeJev:
    def __init__(self, resp: FakeResp) -> None:
        self.resp = resp
        self.seen: dict[str, Any] = {}

    def ask(self, state: Any, questions: Any) -> FakeResp:
        self.seen = {"state": state, "questions": questions}
        return self.resp


def test_decide_maps_answers() -> None:
    jev = FakeJev(FakeResp("c1", 0.8, "type", "s0", 0.9))
    d = decide("search for fable five", MENU + CTRL, jev)  # type: ignore[arg-type]
    assert d.target is not None and d.target.key == "c1"
    assert d.operation == "type" and d.text == "fable five" and d.submit == 0.9
    assert set(jev.seen["questions"]) == {"target", "operation", "text", "submit"}
    assert "none" in jev.seen["questions"]["target"].criteria


def make_screen(resp: FakeResp) -> tuple[Screen, list[str]]:
    log: list[str] = []

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

    s = Screen(
        FakeJev(resp),  # type: ignore[arg-type]
        Perceiver(lambda a: MENU, lambda a: CTRL, clock=lambda: 0.0),
        frontmost=lambda: "Chrome",
        press=press,
        focus=focus,
        type_text=type_text,
        press_key=press_key,
    )
    return s, log


def test_screen_presses_menu_item() -> None:
    s, log = make_screen(FakeResp("m3", 0.95, "press", "s0", 0.1))
    r = s.run("zoom in")
    assert r.ok and log == ["press:m3"]


def test_screen_types_and_submits() -> None:
    s, log = make_screen(FakeResp("c1", 0.8, "type", "s0", 0.9))
    r = s.run("search for fable five")
    assert r.ok and log == ["focus:c1", "key:cmd+a", "type:fable five", "key:enter"]


def test_screen_stays_quiet_below_threshold_or_on_mismatch() -> None:
    s, log = make_screen(FakeResp("c1", 0.4, "type", "s0", 0.9))
    assert not s.run("search for fable five").ok and log == []
    s, log = make_screen(FakeResp("m0", 0.9, "type", "s0", 0.1))  # type on a menu item
    assert not s.run("new tab").ok and log == []
