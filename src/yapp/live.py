"""Hold the key, talk, act."""

from __future__ import annotations

import time

import numpy as np

from yapp.audio import Hotkey, Recorder
from yapp.config import Config
from yapp.display import Display
from yapp.runner import build_runner
from yapp.stt import StreamingTranscriber


def run_live(cfg: Config, display: Display) -> int:
    display.status(f"loading whisper {cfg.whisper_model} …")
    t0 = time.perf_counter()
    stt = StreamingTranscriber(cfg.whisper_model)
    stt.update(np.zeros(cfg.sample_rate, dtype=np.float32))  # warm the model
    stt.reset()
    display.status(f"whisper ready in {time.perf_counter() - t0:.1f}s")
    runner = build_runner(cfg, display)
    rec = Recorder(cfg.sample_rate, cfg.max_hold_seconds)
    key = Hotkey(cfg.hotkey)
    rec.start()
    key.start()
    try:
        while True:
            display.status(f"hold {cfg.hotkey} to talk")
            key.wait_down()
            rec.arm()
            stt.reset()
            while key.is_down():
                tick_start = time.perf_counter()
                t = stt.update(rec.snapshot())
                runner.tick(t.committed, t.pending)
                elapsed = time.perf_counter() - tick_start
                time.sleep(max(0.0, cfg.tick_seconds - elapsed))
            t = stt.update(rec.snapshot())
            runner.tick(t.committed, [])
            runner.finish()
            rec.disarm()
    except KeyboardInterrupt:
        return 0
    finally:
        key.stop()
        rec.stop()
