from yapp.stream import Stream


def test_tail_grows_and_consume_advances() -> None:
    s = Stream(lookahead=2)
    assert s.set_committed(["open"]) is True
    assert s.set_committed(["open"]) is False
    s.set_committed(["open", "notes", "and", "switch"])
    assert s.tail() == "open notes and switch"
    s.consume(2)
    assert s.tail() == "and switch"


def test_fired_dedup() -> None:
    s = Stream(lookahead=2)
    s.set_committed(["open", "notes"])
    assert s.already_fired(2) is False
    s.mark_fired(2)
    assert s.already_fired(2) is True
    s.consume(2)
    s.set_committed(["open", "notes", "open", "safari"])
    assert s.already_fired(2) is False  # different cursor


def test_dictation_holds_back_lookahead() -> None:
    s = Stream(lookahead=2)
    s.set_committed(["type", "hello", "there", "my", "friend"])
    s.consume(1)  # verb consumed by policy
    s.enter_dictation()
    assert s.dictation_words() == ["hello", "there"]  # last 2 held back
    assert s.dictation_words() == []  # not typed twice
    assert s.dictation_words(flush=True) == ["my", "friend"]
    assert s.tail() == ""  # everything typed; nothing left for Jev
    s.exit_dictation()
    assert s.dictating is False


def test_dictation_tail_is_untyped_words() -> None:
    s = Stream(lookahead=2)
    s.set_committed(["type", "hello", "there", "switch", "to"])
    s.consume(1)
    s.enter_dictation()
    assert s.dictation_words() == ["hello", "there"]
    assert s.tail() == "switch to"  # held-back words are what Jev judges


def test_reset() -> None:
    s = Stream(lookahead=2)
    s.set_committed(["a", "b"])
    s.consume(1)
    s.mark_fired(1)
    s.reset()
    assert s.committed == [] and s.cursor == 0 and s.dictating is False
