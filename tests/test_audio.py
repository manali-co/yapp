import numpy as np

from yapp.audio import Recorder


def test_snapshot_only_while_armed() -> None:
    r = Recorder(sample_rate=16000, max_seconds=2)
    r.push(np.ones(100, dtype=np.float32))
    assert r.snapshot().size == 0
    r.arm()
    r.push(np.ones(100, dtype=np.float32))
    r.push(np.ones(50, dtype=np.float32))
    assert r.snapshot().size == 150
    r.disarm()
    assert r.snapshot().size == 0


def test_cap_keeps_latest() -> None:
    r = Recorder(sample_rate=100, max_seconds=1)
    r.arm()
    r.push(np.zeros(80, dtype=np.float32))
    r.push(np.ones(80, dtype=np.float32))
    s = r.snapshot()
    assert s.size == 100 and s[-1] == 1.0


def test_level_is_rms_of_recent() -> None:
    r = Recorder(sample_rate=1000, max_seconds=1)
    r.arm()
    r.push(np.full(100, 0.5, dtype=np.float32))
    assert 0.4 < r.level() < 0.6


class K:
    def __init__(self, name: str = "", vk: int | None = None, char: str | None = None) -> None:
        self.name = name
        self.vk = vk
        self.char = char


def test_hotkey_matcher_option_space_and_escape() -> None:
    from yapp.audio import HotkeyMatcher

    m = HotkeyMatcher()
    assert m.press(K(vk=49)) is None  # space alone
    assert m.press(K(name="alt_r")) is None
    assert m.press(K(vk=49, char="\xa0")) == "toggle"  # option-space arrives as nbsp
    m.release(K(name="alt_r"))
    assert m.press(K(vk=49)) is None
    assert m.press(K(vk=53)) == "escape"


def test_hotkey_matcher_handles_key_enums() -> None:
    from pynput import keyboard

    from yapp.audio import HotkeyMatcher

    m = HotkeyMatcher()
    m.press(keyboard.Key.alt)
    assert m.press(keyboard.Key.space) == "toggle"
    assert m.press(keyboard.Key.esc) == "escape"
