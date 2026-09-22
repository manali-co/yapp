from importlib import resources

from yapp.theme import YAPP_THEME

UI = resources.files("yapp.ui")


def test_bundle_files_present() -> None:
    for name in [
        "window.html",
        "permissions.html",
        "avatar.html",
        "yapp-avatar.js",
        "tokens.css",
        "menubar-glyph.svg",
        "menubar-glyph-listening.svg",
        "menubar-glyph-paused.svg",
        "menubar-glyph-attention.svg",
        "icon.svg",
        "icon-1024.png",
        "icon-16.png",
        "icon-32.png",
    ]:
        assert UI.joinpath(name).is_file(), name
    assert not UI.joinpath("fonts.css").is_file()


def test_window_api_and_no_hold_copy() -> None:
    html = UI.joinpath("window.html").read_text()
    for fn in ["setCountdown", "setPermissions", "setHint", "setAppearance", "'yapp:' + name"]:
        assert fn in html, fn
    assert "Never merged in embed mode" in html
    assert "fonts.googleapis.com" not in html
    assert "let go of" not in html and "hold " not in html.lower()


def test_permissions_api() -> None:
    html = UI.joinpath("permissions.html").read_text()
    assert "window.yappPermissions = {" in html
    assert "emit('open-settings'" in html
    assert "Privacy_Accessibility" in html


def test_tokens_follow_system_appearance() -> None:
    css = UI.joinpath("tokens.css").read_text()
    assert "@media (prefers-color-scheme: dark)" in css
    assert "-apple-system" in css
    assert "--yapp-pill-w: 400px" in css and "--yapp-pill-h: 96px" in css


def test_theme_is_ansi() -> None:
    assert all("#" not in str(v) for v in YAPP_THEME.styles.values())
