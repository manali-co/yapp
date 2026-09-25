import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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


def test_expect_ask_tasks_never_get_a_yes(monkeypatch: object) -> None:
    """--approve applies to ordinary tasks only; an expect_ask task only proves the ask."""
    import yapp.tasks as tasks_mod
    from yapp.config import Config
    from yapp.display import Terminal
    from yapp.guard import Mode
    from yapp.tasks import Task

    seen: list[bool] = []

    class FakeRunner:
        def tick(self, committed: list[str], pending: list[str]) -> list[object]:
            return []

        def finish(self) -> list[object]:
            return []

    def fake_build_runner(
        cfg: object, display: object, *, ask: Callable[[str], bool], **kw: object
    ) -> FakeRunner:
        seen.append(ask("open Terminal"))
        return FakeRunner()

    mp = cast(Any, monkeypatch)
    mp.setattr(tasks_mod, "build_runner", fake_build_runner)
    mp.setattr(tasks_mod, "Jev", lambda model: object())
    mp.setattr(time, "sleep", lambda s: None)
    t = Task("t", "open terminal", [], expect_ask=True, settle_seconds=0)
    o = tasks_mod.run_task(t, Config(), Terminal(), Mode.ASK, approve=True)
    assert seen == [False] and o.asked == ["open Terminal"] and o.passed
    plain = Task("u", "open notes", [], expect_ask=False, settle_seconds=0)
    o = tasks_mod.run_task(plain, Config(), Terminal(), Mode.ASK, approve=True)
    assert seen == [False, True] and not o.passed  # asked when it should not have


def test_ownership_by_content() -> None:
    from yapp.tasks import owned_by_task

    instr = "open reminders and then new reminder and then type buy stamps"
    assert owned_by_task("Buy stamps lonenta", instr)
    assert owned_by_task("And then new reminder buy stamps", instr)
    assert owned_by_task("", instr)  # an empty item from a misfire
    assert not owned_by_task("Call the dentist", instr)  # the user's own new reminder
    assert not owned_by_task("stamps", instr)  # one word is not enough
    assert not owned_by_task("New reminder", instr)  # a generic phrase, not task content
    assert not owned_by_task("", "open reminders and then new reminder")  # nothing dictated


def test_osascript_timeout_is_a_failure(monkeypatch: object) -> None:
    import subprocess
    from typing import Any, cast

    import yapp.tasks as tasks_mod

    def hang(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=k.get("timeout", 0))  # type: ignore[arg-type]

    cast(Any, monkeypatch).setattr(subprocess, "run", hang)
    ok, text = tasks_mod._osascript('tell application "Notes" to get id of every note')
    assert not ok and "timed out" in text
