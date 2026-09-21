from importlib import resources

from yapp.theme import YAPP_THEME


def test_bundle_files_present() -> None:
    ui = resources.files("yapp.ui")
    for name in ["window.html", "yapp-avatar.js", "tokens.css", "fonts.css", "icon.svg"]:
        assert ui.joinpath(name).is_file(), name
    assert ui.joinpath("fonts/Figtree.woff2").is_file()
    assert ui.joinpath("icon-1024.png").is_file()


def test_window_html_uses_local_fonts_and_new_hint() -> None:
    html = resources.files("yapp.ui").joinpath("window.html").read_text()
    assert "fonts.googleapis.com" not in html
    assert 'href="fonts.css"' in html
    assert "press <kbd>⌥</kbd> <kbd>Space</kbd> to talk" in html
    assert "window.yapp = {" in html


def test_theme_has_verdict_styles() -> None:
    for key in ["yapp.verdict.act", "yapp.verdict.refuse", "yapp.transcript.pending"]:
        assert key in YAPP_THEME.styles
