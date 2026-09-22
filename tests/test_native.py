from yapp.native import CAN_JOIN_ALL_SPACES, FULL_SCREEN_AUXILIARY, OVERLAY_LEVEL, STATIONARY


def test_overlay_constants_match_appkit() -> None:
    from AppKit import (
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorStationary,
    )

    assert CAN_JOIN_ALL_SPACES == NSWindowCollectionBehaviorCanJoinAllSpaces
    assert FULL_SCREEN_AUXILIARY == NSWindowCollectionBehaviorFullScreenAuxiliary
    assert STATIONARY == NSWindowCollectionBehaviorStationary
    assert OVERLAY_LEVEL == 1000


def test_embed_css_centres_and_stays_transparent() -> None:
    from yapp.native import EMBED_CSS, INJECT_CSS_JS, MARGIN

    assert "place-items:center" in EMBED_CSS and "background:transparent" in EMBED_CSS
    assert EMBED_CSS in INJECT_CSS_JS.replace("\\'", "'")
    assert MARGIN >= 16
