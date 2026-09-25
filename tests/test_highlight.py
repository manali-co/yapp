from typing import Any

from yapp.highlight import Highlight, acting_hue, durations, oklch_to_srgb
from yapp.windows import Rect


class FakeDrawer:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def place(self, frame: Rect) -> None:
        self.calls.append(("place", frame))

    def pulse(self, on: bool) -> None:
        self.calls.append(("pulse", on))

    def fade(self, ms: int) -> None:
        self.calls.append(("fade", ms))

    def hide(self) -> None:
        self.calls.append(("hide", None))

    def cursor(self, point: tuple[float, float] | None) -> None:
        self.calls.append(("cursor", point))


def test_colour_and_timing_come_from_the_design_bundle() -> None:
    js = "acting:    { balls: [], rate: 1, L: .70, C: .060, h: 45,  glow: .25 },"
    assert acting_hue(js) == (0.70, 0.060, 45.0)
    assert acting_hue("nothing here") == (0.70, 0.060, 45.0)
    assert durations("--yapp-dur-pulse: 380ms; --yapp-dur-settle: 1400ms;") == {
        "pulse": 380,
        "settle": 1400,
    }
    r, g, b = oklch_to_srgb(0.70, 0.060, 45.0)
    assert r > g > b and 0.55 < r < 0.9  # a warm amber, not grey, not clipped
    assert all(abs(c - 1.0) < 1e-6 for c in oklch_to_srgb(1.0, 0.0, 0.0))


def test_state_machine_follows_the_window_and_the_avatar() -> None:
    frames = {"w1": Rect(100, 100, 400, 300)}
    d = FakeDrawer()
    h = Highlight(d, lambda w: frames.get(str(w)), settle_ms=1400)
    assert not h.show("missing") and h.state == "hidden"
    assert (
        h.show("w1") and h.state == "acting" and d.calls[-1] == ("place", Rect(100, 100, 400, 300))
    )
    frames["w1"] = Rect(120, 100, 400, 300)
    h.track()
    assert d.calls[-1] == ("place", Rect(120, 100, 400, 300))
    h.attention(True)
    assert h.state == "attention" and d.calls[-1] == ("pulse", True)
    h.show("w1")  # a new window while attention is on keeps pulsing
    assert h.state == "attention"
    h.cursor((150.0, 160.0))
    assert d.calls[-1] == ("cursor", (150.0, 160.0))
    h.attention(False)
    h.done()
    assert h.state == "done" and d.calls[-2:] == [("pulse", False), ("fade", 1400)]
    h.done()  # idempotent
    assert d.calls[-1] == ("fade", 1400)
    frames.pop("w1")
    h.show("w1")
    h.hide()
    assert h.state == "hidden" and h.window is None and d.calls[-1] == ("hide", None)
    h.cursor((1.0, 1.0))  # nothing drawn when hidden
    assert d.calls[-1] == ("hide", None)
    h.attention(True)
    assert h.state == "hidden"


def test_lost_window_hides_on_track() -> None:
    frames = {"w1": Rect(0, 0, 10, 10)}
    d = FakeDrawer()
    h = Highlight(d, lambda w: frames.get(str(w)))
    h.show("w1")
    frames.clear()
    h.track()
    assert h.state == "hidden" and d.calls[-1] == ("hide", None)
