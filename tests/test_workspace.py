from typing import Any

from yapp.ledger import Ledger, OpenedWindow
from yapp.placement import HAND_OVER, PARALLEL, Placement
from yapp.windows import Display, Rect, WindowManager
from yapp.workspace import Workspace

MAIN = Display("Built-in", Rect(0, 25, 1800, 1105))


class World:
    """A tiny Mac: which apps run, which is in front, what windows exist."""

    def __init__(self) -> None:
        self.running = {"Notes", "Slack"}
        self.front = "Slack"
        self.wins: dict[str, list[str]] = {"Notes": ["notes-1"], "Slack": ["slack-1"]}
        self.frames: dict[str, Rect] = {"slack-1": Rect(100, 100, 900, 700)}
        self.log: list[str] = []
        self.closed: list[str] = []
        self.quit: list[str] = []
        self.raised: list[str] = []

    def raise_app(self, app: str) -> bool:
        self.raised.append(app)
        self.front = app
        return True

    def quit_app(self, app: str) -> bool:
        self.quit.append(app)
        self.running.discard(app)
        self.wins.pop(app, None)
        return True

    def close(self, win: Any) -> bool:
        self.closed.append(str(win))
        return True


def make(world: World, decision: str = PARALLEL, force: str | None = None) -> Workspace:
    def focused(app: str) -> Any:
        wins = world.wins.get(app)
        return wins[0] if wins else None

    def set_frame(w: Any, r: Rect) -> bool:
        world.frames[str(w)] = r
        return True

    wm = WindowManager(
        displays_fn=lambda: [MAIN],
        focused=focused,
        frame_of=lambda w: world.frames.get(str(w)),
        set_frame=set_frame,
        windows_of=lambda app: list(world.wins.get(app, [])),
        log=world.log.append,
    )
    return Workspace(
        lambda instr, front, target: Placement(decision, 0.9, 3),
        wm,
        frontmost=lambda: world.front,
        raise_app=world.raise_app,
        is_running=lambda app: app in world.running,
        quit_app=world.quit_app,
        close_window=world.close,
        windows_of=lambda app: list(world.wins.get(app, [])),
        window_title=lambda w: str(w),
        attention=lambda s: world.log.append(f"attention: {s}"),
        attention_done=lambda: world.log.append("attention done"),
        force=force,
        log=world.log.append,
        sleep=lambda s: None,
    )


def test_parallel_splits_keeps_user_in_front_and_places_the_new_app() -> None:
    w = World()
    ws = make(w)
    assert ws.decide("open text edit", "TextEdit") == PARALLEL and ws.user_app == "Slack"
    assert w.frames["slack-1"] == MAIN.frame.left_half()
    assert ws.before_open("TextEdit") is False  # do not activate
    w.running.add("TextEdit")
    w.wins["TextEdit"] = ["te-1"]
    w.frames["te-1"] = Rect(0, 0, 500, 500)
    ws.after_open("TextEdit")
    assert w.frames["te-1"] == MAIN.frame.right_half() and w.front == "Slack"
    assert ws.ledger.launched_apps == ["TextEdit"] and ws.work_app == "TextEdit"
    assert ws.decide("something else") == PARALLEL  # decided once per session


def test_hand_over_activates_and_moves_nothing() -> None:
    w = World()
    ws = make(w, decision=HAND_OVER)
    assert ws.decide("zoom in") == HAND_OVER
    assert ws.before_open("TextEdit") is True and w.frames["slack-1"] == Rect(100, 100, 900, 700)
    ws.after_open("TextEdit")
    assert w.raised == []


def test_force_overrides_jev() -> None:
    w = World()
    assert make(w, decision=HAND_OVER, force=PARALLEL).decide("x") == PARALLEL


def test_borrow_focus_raises_target_then_gives_the_user_back() -> None:
    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    out = ws.borrow_focus("TextEdit", lambda: "typed")
    assert out == "typed" and w.raised[-2:] == ["TextEdit", "Slack"] and w.front == "Slack"
    assert (
        w.log[-3] == "attention: Borrowing your keyboard for a moment" and "attention done" in w.log
    )


def test_cleanup_closes_windows_quits_launched_apps_and_restores() -> None:
    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")
    w.running.add("TextEdit")
    w.wins["TextEdit"] = ["te-1"]
    ws.after_open("TextEdit")
    # a second window opened in an app that was already running (Notes)
    before = ws.snapshot_windows("Notes")
    w.wins["Notes"].append("notes-2")
    ws.note_new_windows("Notes", before)
    assert [x.title for x in ws.ledger.windows] == ["notes-2"]
    done = ws.cleanup()
    assert w.closed == ["notes-2"] and w.quit == ["TextEdit"]
    assert w.frames["slack-1"] == Rect(100, 100, 900, 700) and "put your window back" in done
    assert ws.ledger.empty and ws.mode is None


def test_cleanup_discards_a_save_sheet_only_with_the_guards_yes() -> None:
    w = World()
    asked: list[str] = []
    pressed: list[str] = []
    ws = make(w)

    def may(action: str) -> bool:
        asked.append(action)
        return action.endswith("created")

    def press(el: Any) -> bool:
        pressed.append(str(el))
        return True

    ws.may = may
    ws.sheet_buttons = lambda win: [("Cancel", "c"), ("Delete", "d")] if str(win) == "te-1" else []
    ws.press = press
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")
    w.running.add("TextEdit")
    w.wins["TextEdit"] = []
    before = ws.snapshot_windows("TextEdit")
    w.wins["TextEdit"] = ["te-1"]
    ws.note_new_windows("TextEdit", before)
    done = ws.cleanup()
    assert w.closed == ["te-1"] and pressed == ["d"] and "pressed Delete in TextEdit" in done
    assert asked == ["press Delete in TextEdit for the untitled document Yapp created"]
    assert w.quit == ["TextEdit"]


def test_ledger_closes_windows_then_quits_launched_apps() -> None:
    led = Ledger(launched_apps=["TextEdit"], windows=[OpenedWindow("TextEdit", "Untitled", "w1")])
    closed: list[Any] = []

    def close(w: Any) -> bool:
        closed.append(w)
        return True

    done = led.cleanup(close=close, quit_app=lambda a: True, restore=lambda: False)
    assert closed == ["w1"] and done == ["closed TextEdit window 'Untitled'", "quit TextEdit"]
    assert led.empty


def test_refused_dictation_is_held_and_typed_with_one_borrow() -> None:
    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")
    w.running.add("TextEdit")
    ws.after_open("TextEdit")
    typed: list[str] = []
    assert not ws.type_on_side("hello ", lambda app, text: False)
    assert not ws.type_on_side("there ", lambda app, text: True)  # once held, stay held (order)
    assert ws.held_text == "hello there " and w.raised.count("TextEdit") == 0
    ws.flush_held(typed.append)
    assert typed == ["hello there "] and w.raised[-2:] == ["TextEdit", "Slack"]
    assert ws.held_text == "" and ws.flush_held(typed.append) is None


def test_borrow_refuses_to_type_when_the_app_will_not_come_forward() -> None:
    w = World()
    ws = make(w)
    ws.decide("x", "TextEdit")
    ws.raise_app = lambda app: False
    ran: list[str] = []
    out = ws.borrow_focus("TextEdit", lambda: ran.append("typed"))
    assert ran == [] and not out.ok and "front" in out.message


def test_already_running_app_keeps_its_own_window_where_it_was() -> None:
    w = World()
    ws = make(w)
    ws.decide("open notes", "Notes")
    ws.before_open("Notes")  # Notes was running: the user's document must not move
    w.frames["notes-1"] = Rect(50, 50, 400, 400)
    ws.after_open("Notes")
    assert w.frames["notes-1"] == Rect(50, 50, 400, 400)


def test_second_parallel_session_keeps_the_first_frame_for_restore() -> None:
    w = World()
    ws = make(w)
    ws.decide("one", "TextEdit")
    ws.reset()
    ws.decide("two", "TextEdit")  # Slack is already at the left half now
    assert ws.windows.user_frame == Rect(100, 100, 900, 700)
    assert ws.windows.restore() and w.frames["slack-1"] == Rect(100, 100, 900, 700)
