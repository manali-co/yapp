from yapp.bar import BRIDGE_JS, Bar, Events, grants_for_page, pill_size
from yapp.permissions import Grant, Permissions


class FakeWindow:
    def __init__(self) -> None:
        self.js: list[str] = []
        self.shown = False
        self.pos = (0, 0)

    def evaluate_js(self, js: str) -> object:
        self.js.append(js)
        return None

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.shown = False

    def move(self, x: int, y: int) -> None:
        self.pos = (x, y)


def test_show_centres_on_screen() -> None:
    w = FakeWindow()
    b = Bar(w)
    b.show_at_top(screen_w=1440, screen_h=900)
    assert w.shown and b.visible
    assert w.pos == ((1440 - 400) // 2, int(900 * 0.12))


def test_state_and_transcript_become_js() -> None:
    w = FakeWindow()
    b = Bar(w)
    b.set_state("listening", level=0.5, confidence=0.9)
    b.transcript("open notes", "and sw")
    b.decision("Opening Notes")
    b.commit()
    g = "window.yapp && window.yapp.{f} && window.yapp.{f}"
    assert w.js[0] == g.format(f="setState") + '("listening", {"level": 0.5, "confidence": 0.9})'
    assert w.js[1] == g.format(f="setTranscript") + '("open notes", "and sw", true)'
    assert w.js[2] == g.format(f="setDecision") + '("Opening Notes", {"muted": false})'
    assert w.js[3] == g.format(f="commit") + "()"


def test_strings_are_json_escaped() -> None:
    w = FakeWindow()
    Bar(w).decision('say "hi" </script>')
    assert '\\"hi\\"' in w.js[0] and "</script>" not in w.js[0]


def test_countdown_hint_permissions_appearance() -> None:
    w = FakeWindow()
    b = Bar(w)
    b.countdown(2.34, total=4.0)
    b.countdown(None)
    b.hint(True)
    b.hint(2)
    b.hint("say undo")
    b.permissions(Permissions(Grant.GRANTED, Grant.MISSING, Grant.UNKNOWN))
    b.appearance("dark")
    b.appearance(None)
    assert w.js[0].endswith("setCountdown(2.3, 4.0)")
    assert w.js[1].endswith("setCountdown(null)")
    assert w.js[2].endswith("setHint(true)") and w.js[3].endswith("setHint(2)")
    assert w.js[4].endswith('setHint("say undo")')
    assert w.js[5].endswith('setPermissions({"mic": true, "input": false, "accessibility": null})')
    assert w.js[6].endswith('setAppearance("dark")') and w.js[7].endswith("setAppearance(null)")


def test_grants_for_page() -> None:
    p = Permissions(Grant.MISSING, Grant.GRANTED, Grant.UNKNOWN)
    assert grants_for_page(p) == {"mic": False, "input": True, "accessibility": None}


def test_events_forward_name_and_detail() -> None:
    got: list[tuple[str, dict[str, object]]] = []
    Events(lambda n, d: got.append((n, d))).event("action", {"id": "fix", "permission": "mic"})
    Events(lambda n, d: got.append((n, d))).event("escape")
    assert got == [("action", {"id": "fix", "permission": "mic"}), ("escape", {})]


def test_bridge_js_subscribes_every_event() -> None:
    for name in ["action", "escape", "open-settings", "later", "permissions-complete"]:
        assert f'"{name}"' in BRIDGE_JS
    assert "pywebview.api.event" in BRIDGE_JS


def test_pill_size_from_tokens() -> None:
    assert pill_size(":root{--yapp-pill-w: 400px;--yapp-pill-h: 96px;}") == (400, 96)
    assert pill_size("nothing here") == (400, 96)
