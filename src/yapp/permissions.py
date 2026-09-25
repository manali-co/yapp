"""The three macOS grants Yapp needs, probed without prompting, plus Settings deep links."""

from __future__ import annotations

import ctypes
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

_SECURITY = "x-apple.systempreferences:com.apple.preference.security?"
PANES = {
    "accessibility": _SECURITY + "Privacy_Accessibility",
    "input": _SECURITY + "Privacy_ListenEvent",
    "mic": _SECURITY + "Privacy_Microphone",
}


class Grant(StrEnum):
    GRANTED = "granted"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Permissions:
    mic: Grant
    input: Grant
    accessibility: Grant

    @property
    def all_granted(self) -> bool:
        return all(g == Grant.GRANTED for g in (self.mic, self.input, self.accessibility))

    @property
    def missing(self) -> list[str]:
        names = {"mic": self.mic, "input": self.input, "accessibility": self.accessibility}
        return [k for k, g in names.items() if g == Grant.MISSING]

    def as_dict(self) -> dict[str, str]:
        return {
            "mic": self.mic.value,
            "input": self.input.value,
            "accessibility": self.accessibility.value,
        }


def settings_url(name: str) -> str:
    return PANES[name]


def open_settings(name: str) -> None:
    subprocess.run(["open", settings_url(name)], check=False)


def probe_input_monitoring() -> Grant:
    try:
        iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        return {0: Grant.GRANTED, 1: Grant.MISSING}.get(iokit.IOHIDCheckAccess(1), Grant.UNKNOWN)
    except (OSError, AttributeError):
        return Grant.UNKNOWN


def probe_accessibility() -> Grant:
    try:
        ax = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        return Grant.GRANTED if ax.AXIsProcessTrusted() else Grant.MISSING
    except (OSError, AttributeError):
        return Grant.UNKNOWN


def probe_microphone() -> Grant:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        status = int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
        # 0 notDetermined, 1 restricted, 2 denied, 3 authorized
        return {3: Grant.GRANTED, 2: Grant.MISSING, 1: Grant.MISSING}.get(status, Grant.UNKNOWN)
    except Exception:  # noqa: BLE001 - any PyObjC/import failure means "we can't tell"
        return Grant.UNKNOWN


def request_input_monitoring() -> None:
    """Ask macOS for Input Monitoring: shows the system prompt and adds the app's row."""
    try:
        iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess(1)  # kIOHIDRequestTypeListenEvent
    except (OSError, AttributeError):
        pass


def request_accessibility(log: Callable[[str], None] = lambda s: None) -> None:
    """Ask macOS for Accessibility: shows the system prompt and adds the app's row."""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
        )
        from Foundation import NSDictionary

        AXIsProcessTrustedWithOptions(
            NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
        )
    except Exception as e:  # noqa: BLE001 - prompting is best effort
        log(f"accessibility prompt unavailable: {e!r}")


def request_missing(p: Permissions) -> None:
    if p.input == Grant.MISSING:
        request_input_monitoring()
    if p.accessibility == Grant.MISSING:
        request_accessibility()


def snapshot(
    *,
    mic: Callable[[], Grant] = probe_microphone,
    input_: Callable[[], Grant] = probe_input_monitoring,
    ax: Callable[[], Grant] = probe_accessibility,
) -> Permissions:
    return Permissions(mic=mic(), input=input_(), accessibility=ax())


class Watcher:
    """Re-probe on demand (the app calls poll() every couple of seconds) and report changes."""

    def __init__(
        self,
        *,
        probe: Callable[[], Permissions] = snapshot,
        on_change: Callable[[Permissions], None],
    ) -> None:
        self._probe = probe
        self._on_change = on_change
        self.current: Permissions | None = None

    def poll(self) -> Permissions:
        p = self._probe()
        if p != self.current:
            self.current = p
            self._on_change(p)
        return p
