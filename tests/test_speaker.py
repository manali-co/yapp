from pathlib import Path

import numpy as np

from yapp.speaker import Verifier, cosine, fbank, windows


def tone(hz: float, seconds: float = 2.0) -> np.ndarray:
    t = np.arange(int(16_000 * seconds)) / 16_000
    return (0.1 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_fbank_shape_and_normalisation() -> None:
    f = fbank(tone(440.0, 1.0))
    assert f.shape == (98, 80)  # 1 s at 10 ms hop with 25 ms frames
    assert abs(float(f.mean())) < 1e-3
    assert fbank(np.zeros(100, dtype=np.float32)).shape == (0, 80)


def test_windows_cover_the_clip() -> None:
    w = windows(tone(440.0, 6.0))
    assert len(w) == 3 and all(x.size == 48_000 for x in w)
    assert len(windows(tone(440.0, 2.0))) == 1


def fake_embed(samples: np.ndarray) -> np.ndarray | None:
    """Pitch-shaped embedding: a clip of the same tone lands on the same vector."""
    spec = np.abs(np.fft.rfft(samples[:16_000]))
    return spec[:64] / (np.linalg.norm(spec[:64]) or 1.0)


def test_verifier_enrols_and_matches_same_voice_only(tmp_path: Path) -> None:
    path = tmp_path / "voice.npy"
    v = Verifier(fake_embed, path=path, threshold=0.9)
    assert not v.enrolled and v.matches(tone(440.0)) == (True, 1.0)  # nothing enrolled yet
    lo, mean = v.enroll(tone(440.0, 6.0))
    assert v.enrolled and lo > 0.99 and mean > 0.99 and path.exists()
    ok, sim = v.matches(tone(440.0))
    assert ok and sim > 0.99
    ok, sim = v.matches(tone(1200.0))
    assert not ok and sim < 0.9
    assert v.matches(tone(440.0, 0.5)) == (False, 0.0)  # too short to judge
    again = Verifier(fake_embed, path=path)
    assert again.enrolled and again.voiceprint is not None and v.voiceprint is not None
    assert cosine(again.voiceprint, v.voiceprint) > 0.999
