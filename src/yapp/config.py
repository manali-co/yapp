"""All tunable numbers. Change thresholds only with a `yapp eval` table in the PR."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    complete: float = 0.70
    open_app: float = 0.60
    type_text: float = 0.70
    open_file: float = 0.60
    press_key: float = 0.70
    undo: float = 0.60
    destructive: float = 0.50
    ends_dictation: float = 0.70


@dataclass(frozen=True)
class Config:
    model: str = "jev-1.13.0"
    whisper_model: str = "mlx-community/whisper-base-mlx"
    hotkey: str = "alt_r"
    tick_seconds: float = 0.4
    sample_rate: int = 16_000
    max_hold_seconds: int = 30
    dictation_lookahead_words: int = 2
    learn_after_seconds: float = 10.0
    catalog_limit: int = 60
    thresholds: Thresholds = field(default_factory=Thresholds)
    learned_path: Path = field(default_factory=lambda: Path.home() / ".yapp" / "learned.jsonl")
