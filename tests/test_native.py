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
