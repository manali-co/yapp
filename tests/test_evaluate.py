from pathlib import Path

from rich.console import Console

from yapp.config import Config
from yapp.display import Terminal
from yapp.evaluate import run_eval


def test_missing_eval_file_is_reported(tmp_path: Path) -> None:
    console = Console(record=True, width=100)
    rc = run_eval(Config(), Terminal(console), tmp_path / "nope.jsonl")
    assert rc == 2 and "not found" in console.export_text()
