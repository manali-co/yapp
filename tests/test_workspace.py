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
    assert not ws.type_on_side("hello ", lambda app, text: False, 1)
    assert not ws.type_on_side("there ", lambda app, text: True, 1)  # once held, stay held
    assert ws.held_text == "hello there " and w.raised.count("TextEdit") == 0
    flushed, _ = ws.flush_held(typed.append)
    assert typed == ["hello there "] and w.raised[-2:] == ["TextEdit", "Slack"]
    assert [h.text for h in flushed] == ["hello there "]
    assert ws.held_text == "" and ws.flush_held(typed.append) == ([], None)


def test_held_words_follow_their_app_and_survive_a_failed_borrow() -> None:
    from yapp.types import Result

    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")
    w.running.add("TextEdit")
    ws.after_open("TextEdit")
    assert not ws.type_on_side("draft ", lambda app, text: False, 1)
    ws.work_app = "Safari"  # a later command moved on
    ws.raise_app = lambda app: False
    _, out = ws.flush_held(lambda text: Result(True, "ok"))
    assert out is not None and not out.ok and ws.held_text == "draft "
    assert ws.held[0].app == "TextEdit"
    ws.raise_app = w.raise_app
    typed: list[str] = []

    def keystrokes(text: str) -> Result:
        typed.append(text)
        return Result(True, "ok")

    ws.flush_held(keystrokes)
    assert typed == ["draft "] and w.raised[-2:] == ["TextEdit", "Slack"] and ws.held_text == ""
    assert ws.drop_held(1) == 0


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


def test_held_words_stay_separate_per_app_and_flush_in_order() -> None:
    from yapp.types import Result

    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    ws.work_app = "TextEdit"
    assert not ws.type_on_side("one ", lambda app, text: False, 1)
    ws.work_app = "Safari"
    assert not ws.type_on_side("two ", lambda app, text: False, 2)
    ws.work_app = "TextEdit"
    # AX would accept, but older TextEdit words are still held: queue behind them
    assert not ws.type_on_side("three ", lambda app, text: True, 3)
    assert [(h.app, h.text, h.action) for h in ws.held] == [
        ("TextEdit", "one ", 1),
        ("Safari", "two ", 2),
        ("TextEdit", "three ", 3),
    ]
    typed: list[tuple[str, str]] = []

    def keystrokes(text: str) -> Result:
        typed.append((w.front, text))
        return Result(True, "ok")

    flushed, _ = ws.flush_held(keystrokes)
    assert typed == [("TextEdit", "one "), ("Safari", "two "), ("TextEdit", "three ")]
    assert [h.action for h in flushed] == [1, 2, 3] and ws.held == []
    ws.type_on_side("x", lambda app, text: False, 4)
    ws.type_on_side("y", lambda app, text: False, 5)
    assert ws.drop_held(9) == 0 and ws.drop_held(4) == 1 and [h.action for h in ws.held] == [5]


def test_borrow_gives_back_the_app_the_user_is_in_now() -> None:
    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")  # user_app = Slack at that time
    w.front = "Mail"  # the user moved on before a retried flush
    ws.borrow_focus("TextEdit", lambda: None)
    assert w.raised[-2:] == ["TextEdit", "Mail"] and w.front == "Mail"


def test_glow_follows_the_work_window_and_the_pointer_borrow_is_announced() -> None:
    w = World()
    ws = make(w)
    shown: list[str] = []

    class FakeHighlight:
        def show(self, win: Any) -> bool:
            shown.append(str(win))
            return True

        def done(self) -> None:
            shown.append("done")

        def hide(self) -> None:
            shown.append("hide")

    ws.highlight = FakeHighlight()

    def focused(app: str) -> Any:
        wins = w.wins.get(app)
        return wins[0] if wins else None

    ws.focused = focused
    ws.decide("open notes", "Notes")
    ws.before_open("Notes")  # Notes was already running: its window is the user's
    ws.after_open("Notes")
    assert shown == []  # never marked, even though Yapp acts in it
    ws.reset()
    assert shown[-1] == "done"  # nothing of Yapp's: whatever glowed fades at session end
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")  # launched by Yapp: stays marked until clean-up
    w.running.add("TextEdit")
    w.wins["TextEdit"] = ["te-1"]
    ws.after_open("TextEdit")
    ws.reset()
    assert shown[-1] == "te-1"
    ws.cleanup()
    assert shown[-1] == "hide" and w.quit == ["TextEdit"]


def test_glow_is_hidden_before_anything_closes() -> None:
    w = World()
    ws = make(w)
    trace: list[str] = []

    class FakeHighlight:
        def show(self, win: Any) -> bool:
            return True

        def done(self) -> None:
            pass

        def hide(self) -> None:
            trace.append("hide")

    ws.highlight = FakeHighlight()
    ws.decide("open text edit", "TextEdit")
    ws.before_open("TextEdit")
    w.running.add("TextEdit")
    ws.after_open("TextEdit")
    orig_quit = ws.quit_app

    def quit_app(app: str) -> bool:
        trace.append(f"quit {app}")
        return orig_quit(app)

    ws.quit_app = quit_app
    ws.cleanup()
    assert trace == ["hide", "quit TextEdit"]
    clicks: list[tuple[float, float]] = []

    def real_click(x: float, y: float) -> bool:
        clicks.append((x, y))
        return True

    ws.real_click = real_click
    assert ws.borrow_pointer(5.0, 6.0) and clicks == [(5.0, 6.0)]
    assert w.log[-2:] == ["attention: Borrowing your mouse for a moment", "attention done"]
    ws.real_click = lambda x, y: False
    assert not ws.borrow_pointer(1.0, 1.0)


def test_typing_now_forces_parallel_and_blocks_raising_and_borrowing() -> None:
    w = World()
    ws = make(w, decision="hand_over")
    typing = [True]
    ws.typing_now = lambda: typing[0]
    assert ws.decide("open text edit", "TextEdit") == "parallel"  # Jev said hand over
    assert any("typing right now" in line for line in w.log)
    ws2 = make(w, decision="hand_over", force="hand_over")
    ws2.typing_now = lambda: typing[0]
    ws2.decide("open text edit", "TextEdit")
    assert ws2.before_open("TextEdit") is False  # pinned hand-over still never raises mid-typing
    out = ws2.borrow_focus("TextEdit", lambda: "typed")
    assert not out.ok and "typing" in out.message and "TextEdit" not in w.raised
    typing[0] = False
    assert ws2.before_open("TextEdit") is True
    assert ws2.borrow_focus("TextEdit", lambda: "typed") == "typed"


def test_glow_never_marks_the_users_own_window_in_parallel_mode() -> None:
    w = World()
    ws = make(w)
    shown: list[str] = []

    class FakeHighlight:
        def show(self, win: Any) -> bool:
            shown.append(str(win))
            return True

        def done(self) -> None:
            pass

        def hide(self) -> None:
            pass

    ws.highlight = FakeHighlight()

    def focused(app: str) -> Any:
        wins = w.wins.get(app)
        return wins[0] if wins else None

    ws.focused = focused
    ws.decide("open notes", "Notes")  # parallel; the user is in Slack (slack-1)
    ws.glow("Slack")
    assert shown == []
    ws.glow("Notes")  # Notes was already running: not Yapp's window either
    assert shown == []
    before = ws.snapshot_windows("Notes")
    w.wins["Notes"].append("notes-2")
    ws.note_new_windows("Notes", before)  # a window Yapp created: marked
    assert shown == ["notes-2"]


def test_focus_is_given_back_when_the_work_app_takes_the_front() -> None:
    w = World()
    ws = make(w)
    clock = [100.0]
    ws.now = lambda: clock[0]
    ws.decide("open text edit", "TextEdit")  # parallel; user in Slack
    w.front = "TextEdit"  # a new window made TextEdit activate itself as the step finished
    assert ws.after_step() and w.front == "Slack" and w.raised[-1] == "Slack"
    assert not ws.guard_focus()  # nothing to do now
    w.front = "Mail"
    ws.typing_now = lambda: True  # the user switched to Mail themselves
    assert not ws.guard_focus() and ws.user_app == "Mail" and w.front == "Mail"
    clock[0] += 10.0  # long after Yapp's last step: a switch to the work app is the user's
    ws.typing_now = lambda: False
    w.front = "TextEdit"
    assert not ws.guard_focus() and ws.user_app == "TextEdit" and w.front == "TextEdit"


def test_steps_wait_for_a_pause_in_typing() -> None:
    w = World()
    ws = make(w)
    ws.decide("x", "TextEdit")
    ticks = [True, True, False]
    ws.typing_now = lambda: ticks.pop(0) if ticks else False
    assert ws.wait_for_typing_pause() and any("waited" in line for line in w.log)
    ws.typing_now = lambda: True
    assert not ws.wait_for_typing_pause(max_seconds=0.3)  # gave up after the cap
    ws2 = make(w, decision="hand_over")
    ws2.decide("x", "TextEdit")
    assert ws2.wait_for_typing_pause()  # hand-over mode: nothing to wait for


def test_work_app_activating_itself_right_after_a_step_is_given_back() -> None:
    w = World()
    ws = make(w)
    ws.decide("open text edit", "TextEdit")
    ws.work_app = "TextEdit"
    ws.typing_now = lambda: True
    w.front = "TextEdit"  # a sheet made the work app activate itself while the user types
    assert ws.after_step() and w.front == "Slack" and ws.user_app == "Slack"
