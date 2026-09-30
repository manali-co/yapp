from yapp.guard import Guard, GuardVerdict, Mode
from yapp.jev import JevError


def scorer(scores: dict[str, float]):  # type: ignore[no-untyped-def]
    def harm(action: str, context: str) -> tuple[float, int]:
        if action == "boom":
            raise JevError("down")
        return scores.get(action, 0.0), 7

    return harm


def test_default_mode_asks_at_thirty_percent() -> None:
    asked: list[str] = []

    def ask(action: str) -> bool:
        asked.append(action)
        return action.startswith("press Send")

    g = Guard(scorer({"open Notes": 0.05, "press Send in Mail": 0.31, "press Delete": 0.9}), ask)
    assert g.check("open Notes").allowed and asked == []
    v = g.check("press Send in Mail", "app Mail")
    assert v.asked and v.approved and v.allowed and asked == ["press Send in Mail"]
    v = g.check("press Delete")
    assert v.asked and not v.approved and not v.allowed
    assert [h.action for h in g.history] == ["open Notes", "press Send in Mail", "press Delete"]


def test_auto_mode_only_asks_near_certain_harm() -> None:
    g = Guard(scorer({"a": 0.5, "b": 0.85}), lambda action: False, mode=Mode.AUTO)
    assert g.check("a").allowed and not g.check("a").asked
    v = g.check("b")
    assert v.asked and not v.allowed and v.threshold == 0.85


def test_jev_failure_counts_as_harmful() -> None:
    log: list[str] = []
    g = Guard(scorer({}), lambda action: False, log=log.append)
    v = g.check("boom")
    assert v.harm == 1.0 and v.asked and not v.allowed
    assert any("jev error" in line for line in log)


def test_verdict_describe() -> None:
    assert GuardVerdict("x", 0.1, 0.3, False, False).describe() == "harm 0.10 < 0.30: go"
    assert "approved" in GuardVerdict("x", 0.9, 0.3, True, True).describe()


def test_an_approved_instruction_clears_its_ordinary_steps_but_not_near_certain_ones() -> None:
    asked: list[str] = []

    def ask(action: str) -> bool:
        asked.append(action)
        return True

    scores = {
        "delete this note in Notes": 0.6,
        "press Delete in Notes": 0.5,
        "press Delete All": 0.9,
    }
    g = Guard(scorer(scores), ask)
    v = g.check_instruction("delete this note in Notes", "Notes")
    assert v.asked and v.approved and asked == ["delete this note in Notes"]
    assert g.check("press Delete in Notes").allowed  # covered by the yes: not asked again
    assert asked == ["delete this note in Notes"]
    assert g.check("press Delete All").asked  # near-certain harm on its own: asked anyway
    g.steps_done()
    assert g.check("press Delete in Notes").asked  # the instruction is over: judged alone


def test_a_denied_instruction_clears_nothing() -> None:
    g = Guard(scorer({"wipe it": 0.7, "press Wipe": 0.5}), lambda action: False)
    assert not g.check_instruction("wipe it").allowed
    assert g.check("press Wipe").asked
