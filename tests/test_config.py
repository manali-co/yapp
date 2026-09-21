from yapp.config import Config, Thresholds
from yapp.types import Intent, Outcome


def test_defaults_are_pinned() -> None:
    cfg = Config()
    assert cfg.model == "jev-1.13.0"
    assert cfg.thresholds == Thresholds()
    assert 0 < cfg.thresholds.complete <= 1


def test_enums_are_strings() -> None:
    assert Intent.OPEN_APP == "open_app"
    assert Outcome.WAIT == "wait"
