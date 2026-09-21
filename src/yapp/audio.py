"""Microphone ring buffer and the hold-to-talk hotkey."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np


class Recorder:
    def __init__(self, sample_rate: int, max_seconds: int) -> None:
        self.sample_rate = sample_rate
        self._cap = sample_rate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._armed = False
        self._lock = threading.Lock()
        self._stream: Any = None

    def push(self, chunk: np.ndarray) -> None:
        with self._lock:
            if not self._armed:
                return
            self._chunks.append(chunk.astype(np.float32, copy=False).ravel())
            total = sum(c.size for c in self._chunks)
            # Drop whole leading chunks only while the remainder still covers the cap.
            while len(self._chunks) > 1 and total - self._chunks[0].size >= self._cap:
                total -= self._chunks[0].size
                self._chunks.pop(0)

    def arm(self) -> None:
        with self._lock:
            self._chunks = []
            self._armed = True

    def disarm(self) -> None:
        with self._lock:
            self._armed = False
            self._chunks = []

    def snapshot(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)[-self._cap :]

    def level(self) -> float:
        s = self.snapshot()[-(self.sample_rate // 10) :]
        if s.size == 0:
            return 0.0
        return float(min(1.0, np.sqrt(np.mean(s * s))))

    def start(self) -> None:
        import sounddevice as sd

        def cb(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            self.push(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=1600,
            callback=cb,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class Hotkey:
    def __init__(self, name: str) -> None:
        from pynput import keyboard

        self._key = getattr(keyboard.Key, name)
        self._down = threading.Event()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def _press(self, key: Any) -> None:
        if key == self._key:
            self._down.set()

    def _release(self, key: Any) -> None:
        if key == self._key:
            self._down.clear()

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def wait_down(self) -> None:
        self._down.wait()

    def is_down(self) -> bool:
        return self._down.is_set()
