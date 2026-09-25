from typing import Any

from yapp.placement import HAND_OVER, PARALLEL, decide_placement


class FakeChoice:
    def __init__(self, key: str, conf: float) -> None:
        self.key, self.confidence, self.probabilities = key, conf, {key: conf}


class FakeResp:
    def __init__(self, key: str, conf: float) -> None:
        self._r = FakeChoice(key, conf)
        self.latency_ms = 5

    def choice(self, name: str) -> FakeChoice:
        return self._r


class FakeJev:
    def __init__(self, key: str, conf: float) -> None:
        self.key, self.conf = key, conf
        self.states: list[dict[str, Any]] = []

    def ask(self, state: Any, questions: Any) -> FakeResp:
        self.states.append(dict(state))
        assert "placement" in questions
        return FakeResp(self.key, self.conf)


def run(key: str, conf: float) -> tuple[str, FakeJev]:
    jev = FakeJev(key, conf)
    p = decide_placement(
        jev,  # type: ignore[arg-type]
        "open text edit and type hi",
        front_app="Slack",
        target_app="TextEdit",
        idle_seconds=1.2,
        display_count=1,
    )
    return p.mode, jev


def test_parallel_needs_confidence() -> None:
    assert run(PARALLEL, 0.9)[0] == PARALLEL
    assert run(PARALLEL, 0.5)[0] == HAND_OVER
    assert run(HAND_OVER, 0.2)[0] == HAND_OVER


def test_state_carries_the_signals() -> None:
    _, jev = run(PARALLEL, 0.9)
    s = jev.states[0]
    assert s["app_in_front_when_spoken"] == "Slack" and s["instruction_target_app"] == "TextEdit"
    assert s["seconds_since_user_typed_or_clicked"] == 1.2 and s["displays"] == 1
