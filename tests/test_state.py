from pathlib import Path

from yapp.state import AppState


def test_state_round_trips_and_hint_flips(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = AppState(p)
    assert s.sessions == 0 and s.show_hint
    for _ in range(5):
        s.bump_sessions()
    assert AppState(p).sessions == 5
    assert not AppState(p).show_hint


def test_corrupt_state_starts_over(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert AppState(p).sessions == 0
