"""Streaming on top of a non-streaming model: re-decode, commit on two-pass agreement."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

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


def mlx_decoder(model: str) -> Decoder:
    import mlx_whisper

    def decode(samples: np.ndarray) -> str:
        out = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=model,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            fp16=True,
            language="en",
        )
        return str(out["text"])

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
        cur = normalize(self._decode(samples))
        stable = agree(self._prev, cur)
        consistent = cur[: len(self._committed)] == self._committed
        if consistent and stable > len(self._committed):
            self._committed = cur[:stable]
        self._prev = cur
        pending = cur[len(self._committed) :] if consistent else []
        return Transcript(list(self._committed), pending)
