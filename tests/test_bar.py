from yapp.bar import Bar


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
    assert w.pos == ((1440 - 360) // 2, int(900 * 0.12))


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
    assert w.js[2] == g.format(f="setDecision") + '("Opening Notes", false)'
    assert w.js[3] == g.format(f="commit") + "()"


def test_countdown_hint_permissions() -> None:
    w = FakeWindow()
    b = Bar(w)
    b.countdown(2.34)
    b.countdown(None)
    b.hint(True)
    b.permissions({"mic": "granted", "input": "missing", "accessibility": "unknown"})
    assert w.js[0].endswith("setCountdown(2.3)")
    assert w.js[1].endswith("setCountdown(0)")
    assert w.js[2].endswith("setHint(true)")
    assert w.js[3].endswith(
        'setPermissions({"mic": "granted", "input": "missing", "accessibility": "unknown"})'
    )


def test_strings_are_json_escaped() -> None:
    w = FakeWindow()
    Bar(w).decision('say "hi" </script>')
    assert '\\"hi\\"' in w.js[0] and "</script>" not in w.js[0]
