import plistlib
from pathlib import Path

from yapp.bundle import write_bundle


def test_bundle_layout_and_plist(tmp_path: Path) -> None:
    app = write_bundle(
        tmp_path / "Yapp.app",
        python=Path("/venv/bin/python"),
        project=Path("/proj"),
        icon_png=Path(__file__),
    )
    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == "co.manali.yapp"
    assert plist["LSUIElement"] is True
    assert "NSMicrophoneUsageDescription" in plist
    launcher = (app / "Contents" / "MacOS" / "yapp").read_text()
    assert launcher.startswith("#!/bin/zsh")
    assert 'exec "/venv/bin/python" -m yapp app' in launcher
    assert (app / "Contents" / "MacOS" / "yapp").stat().st_mode & 0o111
    assert (app / "Contents" / "Resources" / "yapp.icns").exists()
