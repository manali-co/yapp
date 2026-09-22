"""Write a minimal Yapp.app whose executable execs the project's venv Python."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from yapp.config import Config
from yapp.display import Terminal

PLIST = {
    "CFBundleName": "Yapp",
    "CFBundleDisplayName": "Yapp",
    "CFBundleIdentifier": "co.manali.yapp",
    "CFBundleVersion": "0.1.0",
    "CFBundleShortVersionString": "0.1.0",
    "CFBundlePackageType": "APPL",
    "CFBundleExecutable": "yapp",
    "CFBundleIconFile": "yapp",
    "LSUIElement": True,
    "LSMinimumSystemVersion": "14.0",
    "NSMicrophoneUsageDescription": (
        "Yapp listens while the bar is open so it can act on what you say."
    ),
    "NSInputMonitoringUsageDescription": "Yapp watches for its hotkey (⌥ Space) and Escape.",
    "NSAppleEventsUsageDescription": "Yapp types and presses keys in the app you are using.",
    "NSHighResolutionCapable": True,
}


def _icns(icon_png: Path, dest: Path) -> None:
    """Build an .icns from the 1024 png with iconutil when available, else copy the png."""
    iconset = dest.parent / "yapp.iconset"
    iconset.mkdir(exist_ok=True)
    ok = True
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            argv = ["sips", "-z", str(px), str(px), str(icon_png), "--out", str(iconset / name)]
            r = subprocess.run(argv, capture_output=True, check=False)
            ok = ok and r.returncode == 0
    r = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], capture_output=True, check=False
    )
    if not (ok and r.returncode == 0):
        shutil.copy(icon_png, dest)
    shutil.rmtree(iconset, ignore_errors=True)


LAUNCHER_C = Path(__file__).with_name("launcher.c")


def _compile_launcher(dest: Path) -> bool:
    """Build the tiny native main executable. Returns False when no compiler is available.

    -Wl,-no_uuid keeps the binary's code-directory hash identical across rebuilds, so the
    ad-hoc signature's designated requirement (cdhash) and therefore the user's Accessibility
    and Input Monitoring grants survive `yapp install-app` runs.
    """
    r = subprocess.run(
        ["clang", "-O2", "-Wall", "-Wl,-no_uuid", "-o", str(dest), str(LAUNCHER_C)],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def write_bundle(dest: Path, python: Path, project: Path, icon_png: Path) -> Path:
    macos = dest / "Contents" / "MacOS"
    res = dest / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    (dest / "Contents" / "Info.plist").write_bytes(plistlib.dumps(PLIST))
    script = res / "launch.sh"
    script.write_text(
        "#!/bin/zsh\n"
        'source "$HOME/.zshenv" 2>/dev/null\n'
        f'cd "{project}"\n'
        f'exec "{python}" -m yapp app "$@"\n'
    )
    script.chmod(0o755)
    launcher = macos / "yapp"
    if not _compile_launcher(launcher):
        # No compiler: fall back to the script itself (permissions then attach to Python).
        launcher.write_text(script.read_text())
        launcher.chmod(0o755)
    _icns(icon_png, res / "yapp.icns")
    return dest


def install_app(cfg: Config, display: Terminal) -> int:
    from importlib import resources

    dest = Path.home() / "Applications" / "Yapp.app"
    if dest.exists():
        shutil.rmtree(dest)
    project = Path(__file__).resolve().parents[2]
    icon = Path(str(resources.files("yapp.ui").joinpath("icon-1024.png")))
    write_bundle(dest, Path(sys.executable), project, icon)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", "-i", "co.manali.yapp", str(dest)],
        check=False,
    )
    display.status(f"installed {dest}")
    display.status(
        "open it once from Finder; grant Microphone, Input Monitoring, Accessibility to Yapp"
    )
    return 0
