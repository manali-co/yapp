"""Microphone ring buffer and the hold-to-talk hotkey."""

from __future__ import annotations

import threading
from collections.abc import Callable
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


def debug_keys(display: Any, seconds: int) -> int:
    """Print every key pynput reports, so the hotkey name can be confirmed."""
    import time

    from pynput import keyboard

    seen: list[str] = []

    def on_press(key: Any) -> None:
        name = getattr(key, "name", None) or getattr(key, "char", None) or repr(key)
        seen.append(str(name))
        display.status(f"press   {name!s:12} vk={getattr(key, 'vk', '?')}")

    def on_release(key: Any) -> None:
        name = getattr(key, "name", None) or getattr(key, "char", None) or repr(key)
        display.status(f"release {name!s:12}")

    display.status(f"press keys for {seconds}s; the right Option key should show as alt_r")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    time.sleep(seconds)
    listener.stop()
    if not seen:
        display.status(
            "no keys seen: grant Input Monitoring to this terminal app in "
            "System Settings → Privacy & Security → Input Monitoring, then restart it"
        )
        return 1
    return 0


VK_SPACE = 49
VK_ESCAPE = 53
VK_RETURN = 36


def _vk(key: Any) -> int | None:
    """Virtual key code of a pynput key, whether it is a Key enum or a KeyCode."""
    value = getattr(key, "value", key)  # Key.space.value is a KeyCode
    return getattr(value, "vk", None)


def _is_option(key: Any) -> bool:
    name = getattr(key, "name", "")
    return name in ("alt", "alt_l", "alt_r", "alt_gr")


class _FakeKey:
    """Just enough of a pynput key for HotkeyMatcher: a virtual key code."""

    def __init__(self, vk: int) -> None:
        self.vk = vk
        self.name = ""


class HotkeyMatcher:
    """Pure key-event logic: ⌥ Space -> "toggle", Escape -> "escape", else None.

    Matches on virtual key codes because macOS reports Option+Space as a non-breaking-space
    character, which never equals the plain space key pynput's hotkey parser expects.
    """

    def __init__(self) -> None:
        self.option_down = False

    def press(self, key: Any) -> str | None:
        if _is_option(key):
            self.option_down = True
            return None
        vk = _vk(key)
        if vk == VK_ESCAPE:
            return "escape"
        if vk == VK_RETURN and not self.option_down:
            return "approve"  # only means something while the bar is asking
        if vk == VK_SPACE and self.option_down:
            return "toggle"
        return None

    def release(self, key: Any) -> None:
        if _is_option(key):
            self.option_down = False


def swallow(action: str | None, bar_up: bool) -> bool:
    """Which handled keys never reach the app in front: ⌥ Space always (in Finder it would
    also open full-screen Quick Look), Escape and Return only while the bar is up."""
    if action == "toggle":
        return True
    return action in ("escape", "approve") and bar_up


class Hotkeys:
    """Global ⌥ Space / Escape / Return listener built on pynput's raw listener. Keys Yapp
    handles are consumed (see `swallow`); everything else passes through untouched."""

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_escape: Callable[[], None],
        on_approve: Callable[[], None] = lambda: None,
        bar_up: Callable[[], bool] = lambda: False,
    ) -> None:
        from pynput import keyboard

        self._matcher = HotkeyMatcher()
        self._peek = HotkeyMatcher()  # a second matcher, for the intercept decision only
        self._space_consumed = False  # a consumed ⌥ Space key-down owes a consumed key-up
        self._on = {"toggle": on_toggle, "escape": on_escape, "approve": on_approve}
        self._bar_up = bar_up
        self._listener = keyboard.Listener(
            on_press=self._press, on_release=self._release, darwin_intercept=self._intercept
        )

    def _intercept(self, event_type: Any, event: Any) -> Any:
        """Runs in the event tap before the app in front sees the key. Returning None drops
        the event; returning it lets it through."""
        try:
            import Quartz

            vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            flags = Quartz.CGEventGetFlags(event)
            option = bool(flags & Quartz.kCGEventFlagMaskAlternate)
            if event_type == Quartz.kCGEventKeyDown:
                self._peek.option_down = option
                action = self._peek.press(_FakeKey(vk))
                if swallow(action, self._bar_up()):
                    if vk == VK_SPACE:
                        self._space_consumed = True
                    return None
            elif event_type == Quartz.kCGEventKeyUp and vk == VK_SPACE:
                if self._space_consumed:  # only the key-up of a key-down we swallowed
                    self._space_consumed = False
                    return None
        except Exception:  # noqa: BLE001 - never break the user's keyboard over a bug here
            return event
        return event

    def _press(self, key: Any) -> None:
        action = self._matcher.press(key)
        if action:
            self._on[action]()

    def _release(self, key: Any) -> None:
        self._matcher.release(key)

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def is_alive(self) -> bool:
        return bool(self._listener.is_alive())
