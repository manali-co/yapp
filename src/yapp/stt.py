"""Streaming on top of a non-streaming model: re-decode, commit on two-pass agreement."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

Decoder = Callable[[np.ndarray], str]
WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class Transcript:
    committed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def normalize(text: str) -> list[str]:
    return WORD.findall(text.lower())


def agree(prev: list[str], cur: list[str]) -> int:
    n = 0
    for a, b in zip(prev, cur, strict=False):
        if a != b:
            break
        n += 1
    return n


SILENCE_RMS = 0.004  # below this over the whole buffer nobody has spoken yet
NO_SPEECH = 0.6
COMPRESSION = 2.4


def silent(samples: np.ndarray, floor: float = SILENCE_RMS) -> bool:
    if samples.size == 0:
        return True
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) < floor


def keep_segment(seg: dict[str, Any]) -> bool:
    """Whisper's own hallucination signals: no-speech probability and text compression."""
    no_speech = float(seg.get("no_speech_prob", 0.0))
    ratio = float(seg.get("compression_ratio", 0.0))
    return no_speech <= NO_SPEECH and ratio <= COMPRESSION


def cut_repeats(words: list[str], max_n: int = 4, times: int = 3) -> list[str]:
    """'going to be going to be going to be …' → one copy; Whisper loops like this on noise."""
    for n in range(1, max_n + 1):
        if len(words) < n * times:
            continue
        unit = words[-n:]
        count = 0
        while (
            len(words) >= n * (count + 1)
            and words[-n * (count + 1) : len(words) - n * count] == unit
        ):
            count += 1
        if count >= times:
            return words[: len(words) - n * (count - 1)]
    return words


def mlx_decoder(model: str) -> Decoder:
    import mlx_whisper

    def decode(samples: np.ndarray) -> str:
        if silent(samples):
            return ""
        out = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=model,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=NO_SPEECH,
            fp16=True,
            language="en",
        )
        segments = out.get("segments") or []
        if not segments:
            return str(out["text"])
        return " ".join(str(s["text"]) for s in segments if keep_segment(s))

    return decode


class StreamingTranscriber:
    def __init__(self, model: str, decode: Decoder | None = None) -> None:
        self._decode = decode or mlx_decoder(model)
        self.reset()

    def reset(self) -> None:
        self._prev: list[str] = []
        self._committed: list[str] = []

    def update(self, samples: np.ndarray) -> Transcript:
        if samples.size < 1600:  # under 0.1 s of audio
            return Transcript(list(self._committed), [])
        cur = cut_repeats(normalize(self._decode(samples)))
        stable = agree(self._prev, cur)
        consistent = cur[: len(self._committed)] == self._committed
        if consistent and stable > len(self._committed):
            self._committed = cur[:stable]
        self._prev = cur
        pending = cur[len(self._committed) :] if consistent else []
        return Transcript(list(self._committed), pending)
