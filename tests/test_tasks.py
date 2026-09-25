from pathlib import Path

from yapp.tasks import Outcome, load_tasks, run_check


def test_load_tasks_reads_yaml(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "name: a\ninstruction: open notes\ncheck:\n  - frontmost: Notes\nexpect_ask: true\n"
    )
    (tmp_path / "b.yaml").write_text("instruction: open safari\ncheck: {frontmost: Safari}\n")
    ts = load_tasks(tmp_path)
    assert [t.name for t in ts] == ["a", "b"] and ts[0].expect_ask and not ts[1].expect_ask
    assert ts[1].checks == [{"frontmost": "Safari"}]
    assert [t.name for t in load_tasks(tmp_path, only="b")] == ["b"]


def test_file_checks(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("Hello Yapp")
    assert run_check({"file_exists": str(p)}, {}) == (True, str(p))
    ok, _ = run_check({"file_contains": {"path": str(p), "text": "yapp"}}, {})
    assert ok
    ok, _ = run_check({"shell_contains": {"cmd": "echo hi", "text": "HI"}}, {})
    assert ok
    assert run_check({"nope": 1}, {})[0] is False


def test_outcome_row_and_ask_expectation() -> None:
    o = Outcome("t", True, [("c", True, "d")], ["open Terminal"], True, 3.2, 4, 800, ["a"])
    assert o.ask_ok and o.row()["asked"] == ["open Terminal"] and o.row()["seconds"] == 3.2
    quiet = Outcome("t", False, [], [], True, 1.0, 1, 100, [])
    assert not quiet.ask_ok
