"""Write a minimal Yapp.app whose executable execs the project's venv Python."""

from __future__ import annotations

import hashlib
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from yapp.config import Config
from yapp.display import Terminal

BUNDLE_ID = "co.manali.yapp"

PLIST = {
    "CFBundleName": "Yapp",
    "CFBundleDisplayName": "Yapp",
    "CFBundleIdentifier": BUNDLE_ID,
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
    """Put the tiny native main executable at `dest`. Returns False when no compiler exists.

    Every clang build gets a different code-directory hash, and an ad-hoc signature's
    designated requirement is exactly that hash, so a rebuilt launcher would orphan the user's
    Accessibility and Input Monitoring grants. The binary is therefore compiled once per
    launcher.c revision, cached under ~/.yapp/launcher/, and reused byte-for-byte.
    """
    digest = hashlib.sha256(LAUNCHER_C.read_bytes()).hexdigest()[:16]
    cache = Path.home() / ".yapp" / "launcher" / f"yapp-{digest}"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["clang", "-O2", "-Wall", "-o", str(cache), str(LAUNCHER_C)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return False
    shutil.copy2(cache, dest)
    dest.chmod(0o755)
    return True


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
        'mkdir -p "$HOME/.yapp"\n'
        f'exec "{python}" -m yapp ${{=YAPP_ARGS:-app}} "$@" '
        '1>>"$HOME/.yapp/once.log" 2>>"$HOME/.yapp/app.err"\n'
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
    # An identifier-based designated requirement keeps the user's permission grants valid
    # across reinstalls, even when the launcher or bundle resources change.
    subprocess.run(
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "-i",
            BUNDLE_ID,
            "-r",
            f'=designated => identifier "{BUNDLE_ID}"',
            str(dest),
        ],
        check=False,
    )
    display.status(f"installed {dest}")
    display.status(
        "open it once from Finder; grant Microphone, Input Monitoring, Accessibility to Yapp"
    )
    return 0
