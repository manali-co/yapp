from typing import Any

from yapp.windows import Display, Layout, Rect, WindowManager, display_of, plan_layout, tile

MAIN = Display("Built-in", Rect(0, 25, 1800, 1105))
SIDE = Display("Studio", Rect(1800, 0, 2560, 1440))
WIN = Rect(100, 100, 900, 700)


def test_rect_overlap_and_halves() -> None:
    assert Rect(0, 0, 10, 10).overlap(Rect(5, 5, 10, 10)) == 25
    assert Rect(0, 0, 10, 10).overlap(Rect(20, 20, 5, 5)) == 0
    assert MAIN.frame.left_half() == Rect(0, 25, 900, 1105)
    assert MAIN.frame.right_half() == Rect(900, 25, 900, 1105)
    assert MAIN.frame.contains_centre(WIN)


def test_one_display_splits_and_keeps_the_user_on_the_left() -> None:
    lay = plan_layout(WIN, [MAIN])
    assert lay == Layout(work=MAIN.frame.right_half(), user=MAIN.frame.left_half(), kind="split")


def test_two_displays_use_the_other_one_and_leave_the_user_alone() -> None:
    lay = plan_layout(WIN, [MAIN, SIDE])
    assert lay.kind == "display" and lay.work == SIDE.frame and lay.user is None
    on_side = Rect(2000, 100, 800, 600)
    assert display_of(on_side, [MAIN, SIDE]) is SIDE
    assert plan_layout(on_side, [MAIN, SIDE]).work == MAIN.frame


def test_no_user_window_uses_the_first_display() -> None:
    assert plan_layout(None, [MAIN]).kind == "split"
    assert plan_layout(None, [MAIN, SIDE]).work == SIDE.frame


def test_tile_cascades_but_never_collapses() -> None:
    work = Rect(900, 25, 900, 1105)
    assert tile(work, 0) == work
    assert tile(work, 1) == Rect(928, 53, 872, 1077)
    assert tile(work, 100).w >= work.w * 0.7


class FakeAX:
    def __init__(self) -> None:
        self.frames: dict[str, Rect] = {"Notes": WIN, "TextEdit": Rect(300, 300, 600, 400)}
        self.calls: list[tuple[str, Rect]] = []

    def focused(self, app: str) -> Any:
        return app if app in self.frames else None

    def frame_of(self, win: Any) -> Rect | None:
        return self.frames.get(str(win))

    def set_frame(self, win: Any, rect: Rect) -> bool:
        self.frames[str(win)] = rect
        self.calls.append((str(win), rect))
        return True


def make(displays: list[Display]) -> tuple[WindowManager, FakeAX, list[str]]:
    ax = FakeAX()
    log: list[str] = []
    wm = WindowManager(
        displays_fn=lambda: displays,
        focused=ax.focused,
        frame_of=ax.frame_of,
        set_frame=ax.set_frame,
        windows_of=lambda app: [],
        log=log.append,
    )
    return wm, ax, log


def test_manager_splits_places_and_restores() -> None:
    wm, ax, log = make([MAIN])
    lay = wm.begin_parallel("Notes")
    assert lay.kind == "split" and ax.frames["Notes"] == MAIN.frame.left_half()
    assert wm.place("TextEdit") and ax.frames["TextEdit"] == MAIN.frame.right_half()
    assert wm.place("TextEdit") and ax.frames["TextEdit"] == tile(MAIN.frame.right_half(), 1)
    assert wm.restore() and ax.frames["Notes"] == WIN and wm.layout is None
    assert any("left half" in line for line in log)


def test_manager_on_two_displays_moves_nothing_of_the_users() -> None:
    wm, ax, log = make([MAIN, SIDE])
    wm.begin_parallel("Notes")
    assert ax.frames["Notes"] == WIN and wm.place("TextEdit")
    assert ax.frames["TextEdit"] == SIDE.frame and not wm.restore()
    assert not WindowManager(displays_fn=lambda: [MAIN]).place("TextEdit")  # no layout yet


def test_discard_button_recognises_the_throw_away_choices() -> None:
    from yapp.windows import discard_button

    assert discard_button([("Cancel", 1), ("Don’t Save", 2)]) == ("Don’t Save", 2)
    assert discard_button([("Cancel", 1), ("Delete", 2), ("Save", 3)]) == ("Delete", 2)
    assert discard_button([("Cancel", 1), ("Save", 3)]) is None


def test_restore_tries_every_window_and_keeps_the_failures() -> None:
    wm, ax, log = make([MAIN])
    wm.begin_parallel("Notes")
    orig_set = ax.set_frame
    ax.frames["te-1"] = Rect(0, 0, 10, 10)
    wm.moved.append(("te-1", Rect(5, 5, 20, 20)))  # a second moved window

    def flaky(win: object, rect: Rect) -> bool:
        return False if str(win) == "te-1" else orig_set(win, rect)

    wm._set_frame = flaky
    assert not wm.restore() and ax.frames["Notes"] == WIN  # Notes still went back
    assert [str(w) for w, _ in wm.moved] == ["te-1"]  # kept for a retry
    wm._set_frame = orig_set
    assert wm.restore() and wm.moved == []
