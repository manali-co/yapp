import numpy as np

from yapp.stt import StreamingTranscriber, Transcript, agree, normalize


def test_normalize_strips_punctuation_and_case() -> None:
    assert normalize("Open Notes, and then... Safari!") == [
        "open",
        "notes",
        "and",
        "then",
        "safari",
    ]


def test_agree_is_common_prefix_length() -> None:
    assert agree(["open", "notes"], ["open", "notes", "and"]) == 2
    assert agree(["open", "nodes"], ["open", "notes"]) == 1
    assert agree([], ["open"]) == 0


def test_commits_only_on_two_pass_agreement() -> None:
    outputs = iter(
        [
            "open",
            "open notes",
            "open notes and",
            "open notes and switch",
            "open notes and switch to",
        ]
    )
    st = StreamingTranscriber("x", decode=lambda samples: next(outputs))
    a = np.zeros(16000, dtype=np.float32)
    assert st.update(a) == Transcript([], ["open"])
    assert st.update(a) == Transcript(["open"], ["notes"])
    assert st.update(a) == Transcript(["open", "notes"], ["and"])
    assert st.update(a) == Transcript(["open", "notes", "and"], ["switch"])


def test_committed_never_shrinks_on_revision() -> None:
    outputs = iter(["open notes", "open notes", "open nodes please"])
    st = StreamingTranscriber("x", decode=lambda samples: next(outputs))
    a = np.zeros(16000, dtype=np.float32)
    st.update(a)
    st.update(a)
    t = st.update(a)
    assert t.committed == ["open", "notes"]
    assert t.pending == []


def test_short_audio_is_skipped() -> None:
    st = StreamingTranscriber("x", decode=lambda samples: "should not run")
    assert st.update(np.zeros(100, dtype=np.float32)) == Transcript([], [])
