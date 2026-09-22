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
