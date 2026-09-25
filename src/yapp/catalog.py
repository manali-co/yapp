"""The native index: macOS already knows what is installed and where files are."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from yapp.types import App

ShellRunner = Callable[[list[str]], str]


class ShellError(RuntimeError):
    """A shell command exited non-zero; the message is its stderr."""


def run_capture(argv: list[str]) -> str:
    r = subprocess.run(argv, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise ShellError(r.stderr.strip() or f"{argv[0]} exited {r.returncode}")
    return r.stdout


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


APP_ROOTS = ("/Applications/", "/System/Applications/", str(Path.home() / "Applications") + "/")


def installed_apps(run: ShellRunner = run_capture) -> list[App]:
    try:
        out = run(["mdfind", "kMDItemKind == 'Application'"])
    except ShellError:
        out = ""
    seen: dict[str, App] = {"Finder": App("finder", "Finder", "Launch Finder")}
    for line in out.splitlines():
        p = Path(line.strip())
        if p.suffix != ".app" or not str(p).startswith(APP_ROOTS):
            continue
        name = p.stem
        if name not in seen:
            seen[name] = App(slug(name), name, f"Launch {name}")
    return sorted(seen.values(), key=lambda a: a.name)


@lru_cache(maxsize=1)
def cached_apps() -> list[App]:
    return installed_apps()


def narrow(apps: list[App], text: str, limit: int) -> list[App]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]
    if not words:
        return sorted(apps, key=lambda a: a.name)[:limit]

    def score(app: App) -> float:
        parts = app.name.lower().split()
        return max(float(fuzz.ratio(w, part)) for w in words for part in parts)

    ranked = sorted(apps, key=lambda a: (-score(a), a.name))[:limit]
    return sorted(ranked, key=lambda a: a.name)


def search_files(query: str, run: ShellRunner = run_capture, limit: int = 8) -> list[Path]:
    home = str(Path.home())
    try:
        out = run(["mdfind", "-onlyin", home, "-name", query])
    except ShellError:
        return []
    paths = [Path(line) for line in out.splitlines() if line.strip()][: limit * 3]
    if not paths:
        return []
    try:
        stats = run(["stat", "-f", "%m", *map(str, paths)]).split()
    except ShellError:
        stats = []
    mtimes = {p: int(m) for p, m in zip(paths, stats, strict=False)}
    return sorted(paths, key=lambda p: -mtimes.get(p, 0))[:limit]
