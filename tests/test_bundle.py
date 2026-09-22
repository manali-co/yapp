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
    script = (app / "Contents" / "Resources" / "launch.sh").read_text()
    assert script.startswith("#!/bin/zsh")
    assert 'exec "/venv/bin/python" -m yapp ${=YAPP_ARGS:-app}' in script
    assert "app.err" in script
    launcher = app / "Contents" / "MacOS" / "yapp"
    assert launcher.stat().st_mode & 0o111
    head = launcher.read_bytes()[:4]
    assert head in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or head.startswith(b"#!")
    assert (app / "Contents" / "Resources" / "yapp.icns").exists()
