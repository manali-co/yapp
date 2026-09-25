from yapp.permissions import Grant, Permissions, settings_url, snapshot


def test_settings_urls() -> None:
    assert settings_url("accessibility").endswith("Privacy_Accessibility")
    assert settings_url("input").endswith("Privacy_ListenEvent")
    assert settings_url("mic").endswith("Privacy_Microphone")


def test_snapshot_uses_probes() -> None:
    p = snapshot(mic=lambda: Grant.GRANTED, input_=lambda: Grant.MISSING, ax=lambda: Grant.UNKNOWN)
    assert p == Permissions(mic=Grant.GRANTED, input=Grant.MISSING, accessibility=Grant.UNKNOWN)
    assert not p.all_granted
    assert p.missing == ["input"]
    assert p.as_dict() == {"mic": "granted", "input": "missing", "accessibility": "unknown"}


def test_live_probes_return_a_grant() -> None:
    # Real probes on this Mac: values vary, but they must be well-formed and never raise.
    p = snapshot()
    assert all(isinstance(g, Grant) for g in (p.mic, p.input, p.accessibility))


def test_watcher_reports_changes_only() -> None:
    from yapp.permissions import Watcher

    states = iter(
        [
            Permissions(Grant.GRANTED, Grant.MISSING, Grant.MISSING),
            Permissions(Grant.GRANTED, Grant.MISSING, Grant.MISSING),
            Permissions(Grant.GRANTED, Grant.GRANTED, Grant.MISSING),
            Permissions(Grant.GRANTED, Grant.GRANTED, Grant.GRANTED),
        ]
    )
    seen: list[Permissions] = []
    w = Watcher(probe=lambda: next(states), on_change=seen.append)
    for _ in range(4):
        w.poll()
    assert [p.missing for p in seen] == [["input", "accessibility"], ["accessibility"], []]
    assert w.current is not None and w.current.all_granted
