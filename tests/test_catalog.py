from pathlib import Path

from yapp.catalog import installed_apps, narrow, search_files, slug
from yapp.types import App

MDFIND = (
    "/Applications/Notes.app\n/System/Applications/Notes.app\n"
    "/Applications/Google Chrome.app\n/Applications/Visual Studio Code.app\n"
)


def fake_run(argv: list[str]) -> str:
    if argv[0] == "mdfind" and "Application" in argv[1]:
        return MDFIND
    if argv[0] == "mdfind":
        return "/Users/a/Documents/resume.pdf\n/Users/a/Desktop/resume-old.pdf\n"
    if argv[0] == "stat":
        return "1700000000\n1600000000\n"
    raise AssertionError(argv)


def test_slug() -> None:
    assert slug("Google Chrome") == "google_chrome"
    assert slug("Visual Studio Code") == "visual_studio_code"


def test_installed_apps_dedupes_and_sorts() -> None:
    apps = installed_apps(fake_run)
    # Finder lives outside the app folders but every Mac has it
    assert [a.name for a in apps] == ["Finder", "Google Chrome", "Notes", "Visual Studio Code"]
    assert apps[2] == App("notes", "Notes", "Launch Notes")


def test_narrow_keeps_exact_and_limits() -> None:
    names = ["Notes", "Numbers", "Safari", "Slack", "Zoom"]
    apps = [App(slug(n), n, f"Launch {n}") for n in names]
    out = narrow(apps, "open notes please", limit=2)
    assert [a.name for a in out] == ["Notes", "Numbers"]  # sorted by name, Notes exact


def test_narrow_output_is_sorted_by_name() -> None:
    apps = [App(slug(n), n, "") for n in ["Zoom", "Safari", "Slack"]]
    assert [a.name for a in narrow(apps, "slack", limit=10)] == ["Safari", "Slack", "Zoom"]


def test_search_files_orders_by_mtime() -> None:
    hits = search_files("resume", fake_run, limit=5)
    assert hits == [Path("/Users/a/Documents/resume.pdf"), Path("/Users/a/Desktop/resume-old.pdf")]
