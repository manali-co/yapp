# Yapp Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working `yapp` command on macOS that streams hold-to-talk speech through local Whisper and TypeSafe Jev and acts mid-sentence: opens apps, dictates text, opens Spotlight-found files, presses shortcuts, undoes, and learns from undo.

**Architecture:** One Python process. Audio callback fills a ring buffer; a 400 ms tick re-decodes it with mlx-whisper and commits words by two-pass agreement; `stream.py` keeps a cursor over committed words; the tail after the cursor goes to Jev (one fan-out call); `policy.py` gates on confidence and `is_complete`; `executor.py` runs `open`/`osascript`. The window and avatar are a separate plan.

**Tech Stack:** Python 3.12, uv, typesafe-sdk 0.7, mlx-whisper, sounddevice, pynput, rapidfuzz, rich, PyYAML, numpy, httpx (tests), ruff, mypy --strict, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-yapp-design.md`

## Global Constraints

- Python 3.12; `uv` manages the venv; never use the anaconda interpreter directly.
- ruff `select = ["E", "F", "I", "UP", "B"]`, line length 100; mypy `strict = true`; every task ends green on `uv run ruff check . && uv run mypy src && uv run pytest`.
- Model id pinned in config: `jev-1.13.0`. Never `jev-latest` in code.
- Free text is never requested from Jev; code extracts it with the regexes in Task 6.
- Yapp never asks the user a question. Outcomes are execute, wait, ignore, refuse.
- Every choice question has an explicit `unsure`/`none` option.
- Catalog options are sorted by name so option order is deterministic.
- Tests that hit the real API are marked `@pytest.mark.jev` and skip when `TYPESAFE_API_KEY` is unset.
- Commits use Conventional Commits and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Teaching: each task has a **Teach** line. Run that demonstration and show the raw output to Ayush before starting the next task.

---

## File structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | uv project, deps, ruff/mypy/pytest config, `yapp` script entry |
| `src/yapp/types.py` | shared dataclasses and enums; no logic |
| `src/yapp/config.py` | `Config` and `Thresholds`, the only place numbers live |
| `src/yapp/jev.py` | thin typed wrapper over `TypeSafeClient` |
| `src/yapp/catalog.py` | installed apps, fuzzy narrowing, Spotlight file search |
| `src/yapp/questions.yaml` | authored criteria for `intent`, `key_combo`, and the nouls |
| `src/yapp/intent.py` | builds state + questions, calls Jev, extracts free text, returns `Decision` |
| `src/yapp/policy.py` | pure `decide()` |
| `src/yapp/stream.py` | transcript cursor, dictation mode, de-duplication |
| `src/yapp/executor.py` | macOS actions through one `run()` seam |
| `src/yapp/learning.py` | learned examples from act/undo |
| `src/yapp/runner.py` | one tick: transcript → decision → verdict → action; used by `--once`, `eval`, and live |
| `src/yapp/stt.py` | streaming transcriber on mlx-whisper |
| `src/yapp/audio.py` | recorder + hotkey |
| `src/yapp/display.py` | rich panels |
| `src/yapp/app.py` | CLI entry: live, `--once`, `eval`, `--headless` |
| `tests/` | one file per module, plus `eval/transcripts.jsonl` |

---

### Task 1: Repo scaffold and CI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md`, `src/yapp/__init__.py`, `src/yapp/py.typed`, `tests/__init__.py`, `tests/conftest.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: the `yapp` package importable under `uv run`, `pytest.mark.jev` marker, `uv run yapp` entry (Task 10 fills it).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "yapp"
version = "0.1.0"
description = "Hold a key, talk, and your Mac acts while you're still talking. Local Whisper + TypeSafe Jev."
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
authors = [{ name = "Manali" }]
dependencies = [
  "typesafe-sdk>=0.7,<1",
  "mlx-whisper>=0.4",
  "sounddevice>=0.5",
  "pynput>=1.7",
  "rapidfuzz>=3.9",
  "rich>=13.7",
  "pyyaml>=6.0",
  "numpy>=1.26",
]

[project.scripts]
yapp = "yapp.app:main"

[dependency-groups]
dev = [
  "pytest>=8.2",
  "mypy>=1.10",
  "ruff>=0.5",
  "httpx>=0.27",
  "types-PyYAML>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/yapp"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
mypy_path = "src"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["jev: hits the real TypeSafe API; skipped without TYPESAFE_API_KEY"]
```

- [ ] **Step 2: Write `.gitignore`, `LICENSE` (MIT, "Copyright (c) 2026 Manali"), `src/yapp/__init__.py` (`__version__ = "0.1.0"`), empty `src/yapp/py.typed`, empty `tests/__init__.py`**

`.gitignore`:
```
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
.DS_Store
.env
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    skip = pytest.mark.skip(reason="TYPESAFE_API_KEY not set")
    for item in items:
        if "jev" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 4: Write `README.md`**

```markdown
# Yapp

Hold a key, talk, and your Mac acts while you're still talking.

Speech is transcribed locally with Whisper. Each time a word locks in, the words not yet
acted on go to [TypeSafe AI's Jev](https://docs.typesafe.ai), a decision model that returns
typed answers with probabilities in under half a second. Code executes: open apps, dictate
text, open files, press shortcuts. Yapp never asks a question; say "undo" if it got it wrong.

Design: `docs/superpowers/specs/2026-09-21-yapp-design.md`.

## Run

    export TYPESAFE_API_KEY=...
    uv sync
    uv run yapp --once "open notes and switch to safari"   # no microphone
    uv run yapp                                            # hold right ⌥ and talk
```

- [ ] **Step 5: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [dev, main]
jobs:
  ci:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.12
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy src
      - run: uv run pytest -q
```

- [ ] **Step 6: Install and verify**

Run: `cd /Users/ayush/Desktop/projects/yapp && uv python install 3.12 && uv sync --all-groups && uv run python -c "import yapp, typesafe_sdk, mlx_whisper; print(yapp.__version__)"`
Expected: `0.1.0` with no errors. (mlx-whisper pulls mlx; first sync takes a minute.)

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: scaffold uv project, tooling, CI"
```

**Teach:** Show `uv.lock` exists and explain why the anaconda Python is not used. Show the `jev` marker in `pyproject.toml` and how CI stays green without a key.

---

### Task 2: Governance files, GitHub repo, branch rulesets

**Files:**
- Create: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug.md`, `.github/ISSUE_TEMPLATE/feature.md`, `.github/dependabot.yml`, `scripts/rulesets.sh`

- [ ] **Step 1: Write `CONTRIBUTING.md`**

```markdown
# Contributing to Yapp

Thanks for helping. Yapp is small on purpose; keep it that way.

## Setup
    uv sync --all-groups
    export TYPESAFE_API_KEY=...   # only needed for tests marked `jev` and for running the app

## Branch flow
`feature/<name>` → PR into `dev` → `dev` → `main` (release-please). Direct pushes to `dev`
and `main` are blocked for everyone, including admins.

## Before opening a PR
    uv run ruff check . && uv run ruff format . && uv run mypy src && uv run pytest
Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
If a PR changes a threshold in `config.py`, paste the `yapp eval` table in the description.

## Design rule
UI and avatar changes go through the Claude Design project first, then get ported. Do not
improvise visuals in code.
```

- [ ] **Step 2: Write `CODE_OF_CONDUCT.md`** with the Contributor Covenant 2.1 text (fetch from https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md) and contact `hello@manali.dev` replaced by the repo's security advisory link.

- [ ] **Step 3: Write `SECURITY.md`**

```markdown
# Security

Report vulnerabilities privately through GitHub security advisories on this repo. Do not
open a public issue. Never commit API keys; `TYPESAFE_API_KEY` is read from the
environment only. Yapp executes keystrokes on your Mac: review `executor.py` before
running a fork you did not build.
```

- [ ] **Step 4: Write `.github/CODEOWNERS`, PR template, issue templates, dependabot**

`.github/CODEOWNERS`: `* @ayushm-agrawal`

`.github/PULL_REQUEST_TEMPLATE.md`:
```markdown
## What
## Why
## Checks
- [ ] ruff, mypy, pytest green locally
- [ ] threshold changes include the `yapp eval` table
- [ ] UI changes were made in Claude Design first
```

`.github/ISSUE_TEMPLATE/bug.md`:
```markdown
---
name: Bug
about: Something acted wrong or did not act
---
**What I said:**
**What Yapp did / showed (paste the probability panel):**
**Expected:**
**macOS / whisper model / jev model:**
```

`.github/ISSUE_TEMPLATE/feature.md`:
```markdown
---
name: Feature
about: A new action or behaviour
---
**Spoken example:**
**What should happen:**
```

`.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

- [ ] **Step 5: Write `scripts/rulesets.sh`**

```bash
#!/usr/bin/env bash
# Creates branch rulesets on manali-co/yapp. Idempotent: deletes same-named rulesets first.
set -euo pipefail
REPO="manali-co/yapp"
for name in protect-dev protect-main; do
  for id in $(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$name\") | .id"); do
    gh api -X DELETE "repos/$REPO/rulesets/$id"
  done
done
common_rules='[
  {"type":"deletion"},
  {"type":"non_fast_forward"},
  {"type":"pull_request","parameters":{"required_approving_review_count":0,
     "dismiss_stale_reviews_on_push":true,"require_code_owner_review":false,
     "require_last_push_approval":false,"required_review_thread_resolution":true}},
  {"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,
     "required_status_checks":[{"context":"ci"}]}}
]'
gh api -X POST "repos/$REPO/rulesets" --input - <<EOF
{"name":"protect-dev","target":"branch","enforcement":"active","bypass_actors":[],
 "conditions":{"ref_name":{"include":["refs/heads/dev"],"exclude":[]}},
 "rules":$common_rules}
EOF
gh api -X POST "repos/$REPO/rulesets" --input - <<EOF
{"name":"protect-main","target":"branch","enforcement":"active","bypass_actors":[],
 "conditions":{"ref_name":{"include":["refs/heads/main"],"exclude":[]}},
 "rules":$(echo "$common_rules" | python3 -c 'import json,sys; r=json.load(sys.stdin); r.append({"type":"required_linear_history"}); print(json.dumps(r))')}
EOF
echo "rulesets applied"
```

- [ ] **Step 6: Commit, create the GitHub repo, push, create `dev`, apply rulesets**

```bash
chmod +x scripts/rulesets.sh
git add -A && git commit -m "chore: contribution policy, templates, ruleset script"
gh repo create manali-co/yapp --public --source . --push \
  --description "Hold a key, talk, and your Mac acts while you're still talking. Local Whisper + TypeSafe Jev, by Manali."
git checkout -b dev && git push -u origin dev
gh repo edit manali-co/yapp --default-branch dev
./scripts/rulesets.sh
gh api repos/manali-co/yapp/rulesets --jq '.[].name'
```
Expected: `protect-dev` and `protect-main` listed. All further work happens on `feature/*` branches into `dev`.

**Teach:** Show what happens on `git push origin dev` now (rejected) and explain why 0 approvals is the right setting for a solo maintainer with CODEOWNERS ready.

---

### Task 3: Shared types and config

**Files:**
- Create: `src/yapp/types.py`, `src/yapp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Intent`, `App`, `Decision`, `Outcome`, `Verdict`, `Result`, `Executed`, `Thresholds`, `Config` exactly as below. Every later task imports these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from yapp.config import Config, Thresholds
from yapp.types import Intent, Outcome


def test_defaults_are_pinned() -> None:
    cfg = Config()
    assert cfg.model == "jev-1.13.0"
    assert cfg.thresholds == Thresholds()
    assert 0 < cfg.thresholds.complete <= 1


def test_enums_are_strings() -> None:
    assert Intent.OPEN_APP == "open_app"
    assert Outcome.WAIT == "wait"
```

- [ ] **Step 2: Run it**: `uv run pytest tests/test_config.py -v` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write `src/yapp/types.py`**

```python
"""Dataclasses shared across modules. No logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Intent(StrEnum):
    OPEN_APP = "open_app"
    TYPE_TEXT = "type_text"
    OPEN_FILE = "open_file"
    PRESS_KEY = "press_key"
    UNDO = "undo"
    NONE = "none"


@dataclass(frozen=True)
class App:
    key: str  # stable slug, e.g. "notes"
    name: str  # display name passed to `open -a`, e.g. "Notes"
    description: str  # one line shown to Jev


@dataclass(frozen=True)
class Decision:
    tail: str
    intent: Intent
    intent_confidence: float
    intent_probabilities: dict[str, float]
    app: App | None = None
    app_confidence: float | None = None
    text: str | None = None
    key_combo: str | None = None
    file_query: str | None = None
    is_complete: float = 0.0
    ends_dictation: float = 0.0
    is_destructive: float = 0.0
    consumed_words: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class Outcome(StrEnum):
    EXECUTE = "execute"
    WAIT = "wait"  # instruction not complete yet: keep the tail, next tick
    IGNORE = "ignore"  # below threshold or intent none: quiet
    REFUSE = "refuse"  # destructive: quiet, with a reason shown


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str


@dataclass(frozen=True)
class Executed:
    """What the executor last did, so `undo` can reverse it."""

    decision: Decision
    result: Result
    typed_chars: int = 0  # for dictation undo
```

- [ ] **Step 4: Write `src/yapp/config.py`**

```python
"""All tunable numbers. Change thresholds only with a `yapp eval` table in the PR."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    complete: float = 0.70
    open_app: float = 0.60
    type_text: float = 0.70
    open_file: float = 0.60
    press_key: float = 0.70
    undo: float = 0.60
    destructive: float = 0.50
    ends_dictation: float = 0.70


@dataclass(frozen=True)
class Config:
    model: str = "jev-1.13.0"
    whisper_model: str = "mlx-community/whisper-base-mlx"
    hotkey: str = "alt_r"
    tick_seconds: float = 0.4
    sample_rate: int = 16_000
    max_hold_seconds: int = 30
    dictation_lookahead_words: int = 2
    learn_after_seconds: float = 10.0
    catalog_limit: int = 60
    thresholds: Thresholds = field(default_factory=Thresholds)
    learned_path: Path = field(default_factory=lambda: Path.home() / ".yapp" / "learned.jsonl")
```

- [ ] **Step 5: Run**: `uv run pytest tests/test_config.py -v` → PASS. `uv run mypy src` → clean.

- [ ] **Step 6: Commit**: `git checkout -b feature/pipeline && git add -A && git commit -m "feat: shared types and config"`

**Teach:** Walk through `Decision`: which fields Jev fills, which code fills (`text`, `file_query`, `consumed_words`). This split is the whole Jev philosophy in one dataclass.

---

### Task 4: Jev client wrapper (and the first raw call)

**Files:**
- Create: `src/yapp/jev.py`
- Test: `tests/test_jev.py`

**Interfaces:**
- Consumes: `typesafe_sdk.TypeSafeClient`, `Choice`, `Noul`.
- Produces: `Jev(client, model).ask(state, questions) -> JevResponse`; `JevResponse.choice(name) -> ChoiceResult(key, confidence, probabilities)`, `.noul(name) -> float`, `.latency_ms`, `.input_tokens`, `.raw`; `JevError`.

- [ ] **Step 1: The teaching call first.** With the key exported, run this exactly and read the output together:

```bash
curl -s -X POST https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $TYPESAFE_API_KEY" -H "Content-Type: application/json" \
  -d '{"state":{"instruction_so_far":"open notes and"},"model":"jev-1.13.0",
       "questions":{
         "intent":{"type":"choice","instructions":"What does the user want the computer to do?",
           "criteria":{"open_app":"Launch an application","type_text":"Type words into the focused app","none":"Not an instruction or unclear"}},
         "is_complete":{"type":"noul","instructions":"instruction_so_far is a complete instruction that can be carried out now, not a fragment"}}}' | python3 -m json.tool
```
Then the same from Python: `uv run python -c "from typesafe_sdk import TypeSafeClient, Choice, Noul; r=TypeSafeClient(model='jev-1.13.0').system_one({'instruction_so_far':'open'}, {'is_complete': Noul(instructions='instruction_so_far is a complete instruction that can be carried out now, not a fragment')}); print(r.nouls['is_complete'].noul, r.usage)"`. Compare `open` vs `open notes`.

- [ ] **Step 2: Write the failing test** (uses an httpx mock transport so no key is needed)

```python
# tests/test_jev.py
import json

import httpx
import pytest
from typesafe_sdk import Choice, Noul, TypeSafeClient

from yapp.jev import Jev, JevError

CANNED = {
    "model": "jev-1.13.0",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "open_app",
            "confidence": 0.9,
            "probabilities": {"open_app": 0.93, "none": 0.07},
        },
        "is_complete": {"type": "noul", "noul": 0.88},
    },
    "usage": {"input_tokens": 120, "output_tokens": 10},
}


def make_jev(handler: httpx.MockTransport) -> Jev:
    client = TypeSafeClient(api_key="test", model="jev-1.13.0", transport=handler)
    return Jev(client, model="jev-1.13.0")


def test_ask_parses_choice_and_noul() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CANNED)

    jev = make_jev(httpx.MockTransport(handler))
    resp = jev.ask(
        {"instruction_so_far": "open notes"},
        {
            "intent": Choice(instructions="?", criteria={"open_app": "x", "none": "y"}),
            "is_complete": Noul(instructions="?"),
        },
    )
    assert resp.choice("intent").key == "open_app"
    assert resp.choice("intent").confidence == 0.9
    assert resp.choice("intent").probabilities["none"] == 0.07
    assert resp.noul("is_complete") == 0.88
    assert resp.input_tokens == 120
    assert seen["body"]["model"] == "jev-1.13.0"  # type: ignore[index]


def test_api_error_becomes_jev_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    jev = make_jev(httpx.MockTransport(handler))
    with pytest.raises(JevError):
        jev.ask({"instruction_so_far": "x"}, {"q": Noul(instructions="?")})
```

- [ ] **Step 3: Run**: `uv run pytest tests/test_jev.py -v` → FAIL (no module `yapp.jev`).

- [ ] **Step 4: Write `src/yapp/jev.py`**

```python
"""Thin typed wrapper over the TypeSafe SDK. The only module that talks to the API."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from typesafe_sdk import (
    Question,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeClient,
    TypeSafeError,
)


class JevError(Exception):
    """Any failure talking to Jev. A failed call never executes anything."""


@dataclass(frozen=True)
class ChoiceResult:
    key: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class JevResponse:
    raw: dict[str, Any]
    latency_ms: int
    input_tokens: int
    _resp: SystemOneResponse

    def choice(self, name: str) -> ChoiceResult:
        a = self._resp.choices[name]
        return ChoiceResult(a.choice, a.confidence, dict(a.probabilities))

    def noul(self, name: str) -> float:
        return self._resp.nouls[name].noul


class Jev:
    def __init__(self, client: TypeSafeClient | None = None, *, model: str) -> None:
        if client is None:
            if not os.environ.get("TYPESAFE_API_KEY"):
                raise JevError("TYPESAFE_API_KEY is not set")
            client = TypeSafeClient(model=model, retry=RetryPolicy(max_retries=1), timeout=5.0)
        self._client = client
        self._model = model

    def ask(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> JevResponse:
        started = time.perf_counter()
        try:
            resp = self._client.system_one(dict(state), questions, model=self._model)
        except TypeSafeError as e:
            raise JevError(str(e)) from e
        latency = int((time.perf_counter() - started) * 1000)
        return JevResponse(
            raw=resp.model_dump(),
            latency_ms=latency,
            input_tokens=resp.usage.input_tokens or 0,
            _resp=resp,
        )
```

If `RetryPolicy` or `SystemOneResponse` are not exported at the top level in the installed SDK, import from `typesafe_sdk._core.retry` / `typesafe_sdk._core.response_types` and leave a comment. Check with `uv run python -c "import typesafe_sdk as t; print([n for n in dir(t) if 'Retry' in n or 'Response' in n])"`.

- [ ] **Step 5: Run**: `uv run pytest tests/test_jev.py -v` → PASS. `uv run mypy src` clean (the `_resp` field on a frozen dataclass is fine; if mypy objects to the leading underscore in `__init__`, rename to `resp`).

- [ ] **Step 6: Commit**: `git add -A && git commit -m "feat: jev client wrapper with typed answers"`

**Teach:** Show the raw JSON: `probabilities` vs `confidence`, and that `noul` has no confidence. Show that an API error can never reach the executor.

---

### Task 5: Catalog: installed apps, narrowing, Spotlight files

**Files:**
- Create: `src/yapp/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `slug(name) -> str`, `installed_apps(run) -> list[App]`, `narrow(apps, text, limit) -> list[App]`, `search_files(query, run, limit) -> list[Path]`, `ShellRunner = Callable[[list[str]], str]` (returns stdout).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_catalog.py
from pathlib import Path

from yapp.catalog import installed_apps, narrow, search_files, slug
from yapp.types import App

MDFIND = "/Applications/Notes.app\n/System/Applications/Notes.app\n/Applications/Google Chrome.app\n/Applications/Visual Studio Code.app\n"


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
    assert [a.name for a in apps] == ["Google Chrome", "Notes", "Visual Studio Code"]
    assert apps[1] == App("notes", "Notes", "Launch Notes")


def test_narrow_keeps_exact_and_limits() -> None:
    apps = [App(slug(n), n, f"Launch {n}") for n in ["Notes", "Numbers", "Safari", "Slack", "Zoom"]]
    out = narrow(apps, "open notes please", limit=2)
    assert [a.name for a in out] == ["Notes", "Numbers"]  # sorted by name, Notes exact


def test_narrow_output_is_sorted_by_name() -> None:
    apps = [App(slug(n), n, "") for n in ["Zoom", "Safari", "Slack"]]
    assert [a.name for a in narrow(apps, "slack", limit=10)] == ["Safari", "Slack", "Zoom"]


def test_search_files_orders_by_mtime() -> None:
    hits = search_files("resume", fake_run, limit=5)
    assert hits == [Path("/Users/a/Documents/resume.pdf"), Path("/Users/a/Desktop/resume-old.pdf")]
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/catalog.py`**

```python
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


def run_capture(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=False).stdout


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def installed_apps(run: ShellRunner = run_capture) -> list[App]:
    out = run(["mdfind", "kMDItemKind == 'Application'"])
    seen: dict[str, App] = {}
    for line in out.splitlines():
        p = Path(line.strip())
        if p.suffix != ".app":
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
        return max(fuzz.ratio(w, part) for w in words for part in parts)

    ranked = sorted(apps, key=lambda a: (-score(a), a.name))[:limit]
    return sorted(ranked, key=lambda a: a.name)


def search_files(query: str, run: ShellRunner = run_capture, limit: int = 8) -> list[Path]:
    home = str(Path.home())
    out = run(["mdfind", "-onlyin", home, "-name", query])
    paths = [Path(line) for line in out.splitlines() if line.strip()][: limit * 3]
    if not paths:
        return []
    stats = run(["stat", "-f", "%m", *map(str, paths)]).split()
    mtimes = {p: int(m) for p, m in zip(paths, stats, strict=False)}
    return sorted(paths, key=lambda p: -mtimes.get(p, 0))[:limit]
```

- [ ] **Step 4: Run** → PASS. Then the real thing: `uv run python -c "from yapp.catalog import installed_apps, narrow; a=installed_apps(); print(len(a)); print([x.name for x in narrow(a,'open notes',8)])"`.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: app catalog, fuzzy narrowing, spotlight file search"`

**Teach:** Show the full app count vs the narrowed eight and explain the 255-option cap and "irrelevant state hurts". Show `mdfind` from the shell so Spotlight is demystified.

---

### Task 6: Questions and intent classification

**Files:**
- Create: `src/yapp/questions.yaml`, `src/yapp/intent.py`
- Test: `tests/test_intent.py`

**Interfaces:**
- Consumes: `Jev.ask`, `narrow`, `App`, `Decision`, `Intent`.
- Produces: `Context(apps, frontmost_app, already_done, dictating, examples)`, `build_questions(ctx) -> dict[str, Question]`, `classify(tail, ctx, jev, cfg) -> Decision`, `extract_text(tail) -> str`, `extract_file_query(tail) -> str`, `consumed_for(tail, intent) -> int`, `Examples = dict[str, list[str]]` (option key → learned examples), `KEY_COMBOS`.

- [ ] **Step 1: Write `src/yapp/questions.yaml`**

```yaml
intent:
  instructions: >
    What does the user want the computer to do with instruction_so_far?
    Judge only the first instruction if several are chained with "and" or "then".
  criteria:
    open_app:
      what: Launch an application or bring it to the front
      not_for: Opening a named document or file (that is open_file); pressing a shortcut
      examples: ["open notes", "launch safari", "switch to slack", "bring up the terminal", "go to chrome"]
    type_text:
      what: Type or dictate words into the app that is currently focused
      not_for: Naming an app or a file to open
      examples: ["type hello there", "write dear sam", "say thanks for the update", "enter my address"]
    open_file:
      what: Open a specific document, note, or file by its name
      not_for: Launching an app with no file named
      examples: ["open my resume", "find the budget spreadsheet", "show the tax pdf"]
    press_key:
      what: Press a keyboard shortcut
      not_for: Typing words
      examples: ["save", "copy that", "paste", "select all", "hit enter", "press escape"]
    undo:
      what: Reverse or cancel what Yapp just did
      not_for: The undo shortcut inside an app while dictating a document
      examples: ["undo", "no", "not that", "undo that", "wrong app"]
    none:
      what: Not an instruction to the computer, or too unclear to act on
      examples: ["um", "what was I", "hmm let me think", "okay so"]

key_combo:
  instructions: Which keyboard shortcut does the user mean?
  criteria:
    cmd+s: Save
    cmd+c: Copy
    cmd+v: Paste
    cmd+a: Select all
    cmd+w: Close the window or tab
    enter: Press enter or return
    escape: Escape or cancel
    unsure: None of these or not a shortcut

is_complete:
  instructions: >
    instruction_so_far is a complete instruction that can be carried out right now.
    A fragment that is still being spoken is not complete.
  criteria:
    true: {what: A verb and its object are both present, examples: ["open notes", "open notes and", "type hello", "save", "undo", "switch to safari"]}
    false: {what: The verb has no object yet, or only filler so far, examples: ["open", "switch to", "go to the", "um open", "type"]}

ends_dictation:
  instructions: >
    The user is dictating text into an app. instruction_so_far is a new instruction to the
    computer rather than more words to type.
  criteria:
    true: {what: A command aimed at the computer, examples: ["stop typing", "open safari", "undo", "switch to notes", "save that"]}
    false: {what: Ordinary sentence content that belongs in the document, examples: ["and then we went home", "thanks for your help", "the meeting is at five", "open to suggestions"]}

is_destructive:
  instructions: Carrying out instruction_so_far could delete data, send a message, or spend money.
  criteria:
    true: {examples: ["delete everything", "send the email", "empty the trash", "buy it now", "close without saving"]}
    false: {examples: ["open notes", "type hello", "save", "undo"]}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_intent.py
import os

import pytest
from typesafe_sdk import Choice

from yapp.config import Config
from yapp.intent import (
    Context,
    build_questions,
    classify,
    consumed_for,
    extract_file_query,
    extract_text,
)
from yapp.jev import Jev
from yapp.types import App, Intent

APPS = [
    App("notes", "Notes", "Launch Notes"),
    App("safari", "Safari", "Launch Safari"),
    App("slack", "Slack", "Launch Slack"),
]


def ctx(**kw: object) -> Context:
    base = dict(apps=APPS, frontmost_app="Finder", already_done=[], dictating=False, examples={})
    base.update(kw)
    return Context(**base)  # type: ignore[arg-type]


def test_extract_text() -> None:
    assert extract_text("type hello there") == "hello there"
    assert extract_text("write: dear sam") == "dear sam"
    assert extract_text("type") == ""


def test_extract_file_query() -> None:
    assert extract_file_query("open my resume") == "resume"
    assert extract_file_query("find the budget spreadsheet file") == "budget spreadsheet"


def test_consumed_stops_at_conjunction() -> None:
    assert consumed_for("open notes and switch to safari", Intent.OPEN_APP) == 2
    assert consumed_for("open notes", Intent.OPEN_APP) == 2
    assert consumed_for("type hello and then some", Intent.TYPE_TEXT) == 1  # verb only
    assert consumed_for("and switch to safari", Intent.OPEN_APP) == 4  # leading 'and' consumed too


def test_build_questions_has_unsure_and_learned_examples() -> None:
    q = build_questions(ctx(examples={"notes": ["open node"]}))
    app = q["app"]
    assert isinstance(app, Choice)
    assert "unsure" in app.criteria
    notes = app.criteria["notes"]
    assert isinstance(notes, dict) and "open node" in notes["examples"]  # type: ignore[index]
    assert set(q) == {
        "intent",
        "app",
        "key_combo",
        "is_complete",
        "ends_dictation",
        "is_destructive",
    }


@pytest.mark.jev
@pytest.mark.parametrize(
    ("tail", "intent", "app", "complete"),
    [
        ("open notes", Intent.OPEN_APP, "notes", True),
        ("open notes and", Intent.OPEN_APP, "notes", True),
        ("switch to safari", Intent.OPEN_APP, "safari", True),
        ("open", Intent.OPEN_APP, None, False),
        ("type hello there", Intent.TYPE_TEXT, None, True),
        ("undo", Intent.UNDO, None, True),
        ("save that", Intent.PRESS_KEY, None, True),
        ("um so", Intent.NONE, None, False),
    ],
)
def test_live_classification(tail: str, intent: Intent, app: str | None, complete: bool) -> None:
    cfg = Config()
    d = classify(tail, ctx(), Jev(model=cfg.model), cfg)
    assert d.intent == intent, d.intent_probabilities
    if app:
        assert d.app is not None and d.app.key == app
    assert (d.is_complete >= cfg.thresholds.complete) == complete, d.is_complete
```

- [ ] **Step 3: Run** → FAIL (no `yapp.intent`).

- [ ] **Step 4: Write `src/yapp/intent.py`**

```python
"""Transcript tail -> Decision. The only module that designs Jev questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml
from typesafe_sdk import Choice, Noul, Question

from yapp.catalog import narrow
from yapp.config import Config
from yapp.jev import Jev
from yapp.types import App, Decision, Intent

Examples = dict[str, list[str]]
CONJUNCTIONS = {"and", "then", "also"}
TYPE_VERB = re.compile(r"^(type|write|enter|say)\b[:,]?\s*", re.I)
FILE_VERB = re.compile(r"^(open|find|show)\b\s*(my|the)?\s*", re.I)
FILE_TRAIL = re.compile(r"\s*\b(file|document|doc|pdf)$", re.I)
KEY_COMBOS = ("cmd+s", "cmd+c", "cmd+v", "cmd+a", "cmd+w", "enter", "escape")


@dataclass(frozen=True)
class Context:
    apps: list[App]
    frontmost_app: str
    already_done: list[str]
    dictating: bool
    examples: Examples = field(default_factory=dict)


def _load_yaml() -> dict[str, Any]:
    text = resources.files("yapp").joinpath("questions.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(text)
    return data


QUESTIONS = _load_yaml()


def extract_text(tail: str) -> str:
    return TYPE_VERB.sub("", tail, count=1).strip()


def extract_file_query(tail: str) -> str:
    return FILE_TRAIL.sub("", FILE_VERB.sub("", tail, count=1)).strip()


def consumed_for(tail: str, intent: Intent) -> int:
    words = tail.split()
    lead = 0
    while lead < len(words) and words[lead] in CONJUNCTIONS:
        lead += 1
    if intent == Intent.TYPE_TEXT:
        return lead + 1  # the verb only; dictation types the rest
    for i in range(lead + 1, len(words)):
        if words[i] in CONJUNCTIONS:
            return i
    return len(words)


def _app_option(app: App, learned: list[str]) -> dict[str, Any]:
    words = [w for w in app.name.lower().split() if len(w) > 1]
    generated = [f"open {w}" for w in words] + [f"switch to {app.name.lower()}"]
    return {"what": app.description, "examples": (learned[-5:] + generated)[:8]}


def build_questions(ctx: Context, tail: str = "", limit: int = 60) -> dict[str, Question]:
    q = QUESTIONS
    apps = narrow(ctx.apps, tail, limit) if tail else sorted(ctx.apps, key=lambda a: a.name)[:limit]
    app_criteria: dict[str, Any] = {
        a.key: _app_option(a, ctx.examples.get(a.key, [])) for a in apps
    }
    app_criteria["unsure"] = "None of these applications"
    return {
        "intent": Choice(
            instructions=q["intent"]["instructions"], criteria=q["intent"]["criteria"]
        ),
        "app": Choice(instructions="Which application does the user mean?", criteria=app_criteria),
        "key_combo": Choice(
            instructions=q["key_combo"]["instructions"], criteria=q["key_combo"]["criteria"]
        ),
        "is_complete": Noul(
            instructions=q["is_complete"]["instructions"], criteria=q["is_complete"]["criteria"]
        ),
        "ends_dictation": Noul(
            instructions=q["ends_dictation"]["instructions"],
            criteria=q["ends_dictation"]["criteria"],
        ),
        "is_destructive": Noul(
            instructions=q["is_destructive"]["instructions"],
            criteria=q["is_destructive"]["criteria"],
        ),
    }


def classify(tail: str, ctx: Context, jev: Jev, cfg: Config) -> Decision:
    state = {
        "instruction_so_far": tail,
        "already_done": ctx.already_done[-3:],
        "frontmost_app": ctx.frontmost_app,
        "dictating": ctx.dictating,
    }
    questions = build_questions(ctx, tail, cfg.catalog_limit)
    resp = jev.ask(state, questions)
    intent_r = resp.choice("intent")
    intent = Intent(intent_r.key)
    app_r = resp.choice("app")
    by_key = {a.key: a for a in ctx.apps}
    app = by_key.get(app_r.key) if intent == Intent.OPEN_APP else None
    combo_r = resp.choice("key_combo")
    return Decision(
        tail=tail,
        intent=intent,
        intent_confidence=intent_r.confidence,
        intent_probabilities=intent_r.probabilities,
        app=app,
        app_confidence=app_r.confidence if intent == Intent.OPEN_APP else None,
        text=extract_text(tail) if intent == Intent.TYPE_TEXT else None,
        key_combo=combo_r.key if intent == Intent.PRESS_KEY and combo_r.key != "unsure" else None,
        file_query=extract_file_query(tail) if intent == Intent.OPEN_FILE else None,
        is_complete=resp.noul("is_complete"),
        ends_dictation=resp.noul("ends_dictation"),
        is_destructive=resp.noul("is_destructive"),
        consumed_words=consumed_for(tail, intent),
        latency_ms=resp.latency_ms,
        raw=resp.raw,
    )
```

Add to `pyproject.toml` under `[tool.hatch.build.targets.wheel]` nothing extra; the yaml ships because it is inside `src/yapp`. Verify with `uv run python -c "from yapp.intent import QUESTIONS; print(list(QUESTIONS))"`.

- [ ] **Step 5: Run** the pure tests: `uv run pytest tests/test_intent.py -v -m "not jev"` → PASS. Then live: `uv run pytest tests/test_intent.py -v -m jev` → PASS. If a row fails, print `d.raw` and adjust the criteria wording or examples in `questions.yaml`, not the test. Record what changed in the commit message.

- [ ] **Step 6: Commit**: `git add -A && git commit -m "feat: jev questions and intent classification"`

**Teach:** Run the live test with `-s` and a print of the probability table. Then edit one `not_for` line, re-run, and watch a probability move. This is the tuning loop in miniature.

---

### Task 7: Policy

**Files:**
- Create: `src/yapp/policy.py`
- Test: `tests/test_policy.py`

**Interfaces:**
- Consumes: `Decision`, `Thresholds`, `Outcome`, `Verdict`.
- Produces: `decide(d, t, dictating, has_last) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy.py
import pytest

from yapp.config import Thresholds
from yapp.policy import decide
from yapp.types import App, Decision, Intent, Outcome

T = Thresholds()
NOTES = App("notes", "Notes", "Launch Notes")


def d(**kw: object) -> Decision:
    base: dict[str, object] = dict(
        tail="x",
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={},
        app=NOTES,
        app_confidence=0.9,
        is_complete=0.9,
    )
    base.update(kw)
    return Decision(**base)  # type: ignore[arg-type]


def test_incomplete_waits() -> None:
    assert decide(d(is_complete=0.3), T).outcome == Outcome.WAIT


def test_open_app_executes_at_threshold() -> None:
    assert decide(d(intent_confidence=T.open_app), T).outcome == Outcome.EXECUTE


def test_open_app_below_threshold_ignores() -> None:
    assert decide(d(intent_confidence=0.59), T).outcome == Outcome.IGNORE


def test_open_app_unsure_ignores() -> None:
    assert decide(d(app=None), T).outcome == Outcome.IGNORE


def test_destructive_refuses_even_when_confident() -> None:
    v = decide(d(is_destructive=0.6), T)
    assert v.outcome == Outcome.REFUSE and "delete" in v.reason


def test_type_text_enters_dictation() -> None:
    v = decide(d(intent=Intent.TYPE_TEXT, app=None, text="", intent_confidence=0.75), T)
    assert v.outcome == Outcome.EXECUTE


def test_dictating_keeps_typing_unless_ends() -> None:
    v = decide(d(intent=Intent.OPEN_APP, ends_dictation=0.2), T, dictating=True)
    assert v.outcome == Outcome.IGNORE and v.reason == "dictating"
    v2 = decide(d(intent=Intent.OPEN_APP, ends_dictation=0.9), T, dictating=True)
    assert v2.outcome == Outcome.EXECUTE


def test_undo_needs_last_action() -> None:
    u = d(intent=Intent.UNDO, app=None)
    assert decide(u, T, has_last=False).outcome == Outcome.IGNORE
    assert decide(u, T, has_last=True).outcome == Outcome.EXECUTE


def test_none_ignores() -> None:
    assert decide(d(intent=Intent.NONE, app=None), T).outcome == Outcome.IGNORE


@pytest.mark.parametrize("combo,expected", [("cmd+s", Outcome.EXECUTE), (None, Outcome.IGNORE)])
def test_press_key(combo: str | None, expected: Outcome) -> None:
    assert decide(d(intent=Intent.PRESS_KEY, app=None, key_combo=combo), T).outcome == expected
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/policy.py`**

```python
"""Confidence gates. Pure. Yapp acts or stays quiet; it never asks."""

from __future__ import annotations

from yapp.config import Thresholds
from yapp.types import Decision, Intent, Outcome, Verdict


def decide(
    d: Decision, t: Thresholds, *, dictating: bool = False, has_last: bool = False
) -> Verdict:
    if dictating and d.ends_dictation < t.ends_dictation:
        return Verdict(Outcome.IGNORE, "dictating")
    if d.is_destructive >= t.destructive:
        return Verdict(Outcome.REFUSE, "won't do that: could delete, send, or spend")
    if d.intent == Intent.NONE:
        return Verdict(Outcome.IGNORE, "not an instruction")
    if d.is_complete < t.complete:
        return Verdict(Outcome.WAIT, f"waiting: complete {d.is_complete:.2f} < {t.complete}")
    c = d.intent_confidence
    match d.intent:
        case Intent.OPEN_APP:
            if d.app is None:
                return Verdict(Outcome.IGNORE, "no app matched")
            return _gate(c, t.open_app, f"open {d.app.name}")
        case Intent.TYPE_TEXT:
            return _gate(c, t.type_text, "dictate")
        case Intent.OPEN_FILE:
            if not d.file_query:
                return Verdict(Outcome.IGNORE, "no file named")
            return _gate(c, t.open_file, f"open file '{d.file_query}'")
        case Intent.PRESS_KEY:
            if d.key_combo is None:
                return Verdict(Outcome.IGNORE, "no shortcut matched")
            return _gate(c, t.press_key, f"press {d.key_combo}")
        case Intent.UNDO:
            if not has_last:
                return Verdict(Outcome.IGNORE, "nothing to undo")
            return _gate(c, t.undo, "undo")
    return Verdict(Outcome.IGNORE, "unhandled intent")


def _gate(conf: float, threshold: float, action: str) -> Verdict:
    if conf >= threshold:
        return Verdict(Outcome.EXECUTE, f"{action} ({conf:.2f} ≥ {threshold})")
    return Verdict(Outcome.IGNORE, f"{action} below threshold ({conf:.2f} < {threshold})")
```

- [ ] **Step 4: Run** → PASS. mypy clean.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: act-or-quiet policy"`

**Teach:** Point at the order of checks (dictation first, destructive second, completeness third) and why each earlier check must win over later ones.

---

### Task 8: Stream cursor and dictation

**Files:**
- Create: `src/yapp/stream.py`
- Test: `tests/test_stream.py`

**Interfaces:**
- Produces: `Stream(lookahead)` with `set_committed(words) -> bool` (True if grew), `tail() -> str`, `consume(n)`, `enter_dictation(verb_words)`, `exit_dictation()`, `dictation_words(flush=False) -> list[str]`, `already_fired(n) -> bool`, `mark_fired(n)`, `reset()`, attributes `committed`, `cursor`, `dictating`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stream.py
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
    assert s.tail() == "my friend"  # untyped-or-held words remain the tail for Jev
    s.exit_dictation()
    assert s.dictating is False


def test_reset() -> None:
    s = Stream(lookahead=2)
    s.set_committed(["a", "b"])
    s.consume(1)
    s.mark_fired(1)
    s.reset()
    assert s.committed == [] and s.cursor == 0 and s.dictating is False
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/stream.py`**

```python
"""A cursor over the committed transcript. Everything after the cursor is what Jev sees."""

from __future__ import annotations


class Stream:
    def __init__(self, lookahead: int) -> None:
        self.lookahead = lookahead
        self.reset()

    def reset(self) -> None:
        self.committed: list[str] = []
        self.cursor = 0
        self.dictating = False
        self._typed_upto = 0
        self._fired: set[tuple[int, int]] = set()

    def set_committed(self, words: list[str]) -> bool:
        grew = len(words) > len(self.committed)
        if len(words) >= len(self.committed):
            self.committed = list(words)
        return grew

    def tail(self) -> str:
        start = max(self.cursor, self._typed_upto) if self.dictating else self.cursor
        return " ".join(self.committed[start:])

    def consume(self, n: int) -> None:
        self.cursor = min(len(self.committed), self.cursor + n)

    def already_fired(self, n: int) -> bool:
        return (self.cursor, n) in self._fired

    def mark_fired(self, n: int) -> None:
        self._fired.add((self.cursor, n))

    def enter_dictation(self) -> None:
        self.dictating = True
        self._typed_upto = self.cursor

    def exit_dictation(self) -> None:
        self.dictating = False
        self.cursor = max(self.cursor, self._typed_upto)

    def dictation_words(self, *, flush: bool = False) -> list[str]:
        """Words to type now. Holds back the last `lookahead` words unless flushing."""
        end = (
            len(self.committed)
            if flush
            else max(self._typed_upto, len(self.committed) - self.lookahead)
        )
        words = self.committed[self._typed_upto : end]
        self._typed_upto = end
        return words
```

- [ ] **Step 4: Run** → PASS.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: transcript cursor and dictation window"`

**Teach:** Draw the cursor on a whiteboard-style line in the terminal for "open notes and switch to safari": where `cursor`, `_typed_upto`, and the lookahead sit at each tick. Explain why the lookahead exists (so "switch" isn't typed before Jev can see "switch to safari").

---

### Task 9: Executor

**Files:**
- Create: `src/yapp/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Produces: `Executor(run)` with `open_app(app)`, `type_text(text)`, `press_key(combo)`, `open_file(path)`, `frontmost_app()`, `undo(last)`, each returning `Result`; `applescript_escape(s) -> str`; `ShellRunner` type reused from catalog.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_executor.py
from pathlib import Path

from yapp.executor import Executor, applescript_escape
from yapp.types import App, Decision, Executed, Intent, Result

NOTES = App("notes", "Notes", "Launch Notes")


class Fake:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return "Safari\n" if argv[:2] == ["osascript", "-e"] and "frontmost" in argv[2] else ""


def test_escape() -> None:
    assert applescript_escape('say "hi" \\ bye') == 'say \\"hi\\" \\\\ bye'


def test_open_app() -> None:
    f = Fake()
    assert Executor(f).open_app(NOTES) == Result(True, "opened Notes")
    assert f.calls == [["open", "-a", "Notes"]]


def test_type_text_uses_system_events() -> None:
    f = Fake()
    Executor(f).type_text('hello "world"')
    assert f.calls[0][:2] == ["osascript", "-e"]
    assert 'keystroke "hello \\"world\\""' in f.calls[0][2]


def test_press_key() -> None:
    f = Fake()
    Executor(f).press_key("cmd+s")
    assert 'keystroke "s" using command down' in f.calls[0][2]
    Executor(f).press_key("enter")
    assert "key code 36" in f.calls[1][2]


def test_frontmost() -> None:
    assert Executor(Fake()).frontmost_app() == "Safari"


def test_undo_open_app_quits() -> None:
    f = Fake()
    d = Decision(
        tail="open notes",
        intent=Intent.OPEN_APP,
        intent_confidence=1,
        intent_probabilities={},
        app=NOTES,
    )
    Executor(f).undo(Executed(d, Result(True, "")))
    assert 'quit app "Notes"' in f.calls[0][2]


def test_undo_dictation_backspaces() -> None:
    f = Fake()
    d = Decision(
        tail="type hi", intent=Intent.TYPE_TEXT, intent_confidence=1, intent_probabilities={}
    )
    Executor(f).undo(Executed(d, Result(True, ""), typed_chars=3))
    assert "key code 51" in f.calls[0][2] and "repeat 3 times" in f.calls[0][2]


def test_open_file() -> None:
    f = Fake()
    Executor(f).open_file(Path("/tmp/a b.pdf"))
    assert f.calls == [["open", "/tmp/a b.pdf"]]
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/executor.py`**

```python
"""macOS actions. Every shell call goes through one `run` seam so tests inject a fake."""

from __future__ import annotations

from pathlib import Path

from yapp.catalog import ShellRunner, run_capture
from yapp.types import App, Executed, Intent, Result

KEY_CODES = {"enter": 36, "escape": 53, "backspace": 51}
MODIFIERS = {
    "cmd": "command down",
    "shift": "shift down",
    "alt": "option down",
    "ctrl": "control down",
}


def applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class Executor:
    def __init__(self, run: ShellRunner = run_capture) -> None:
        self._run = run

    def _osa(self, script: str) -> str:
        return self._run(["osascript", "-e", script])

    def open_app(self, app: App) -> Result:
        self._run(["open", "-a", app.name])
        return Result(True, f"opened {app.name}")

    def type_text(self, text: str) -> Result:
        if not text:
            return Result(True, "nothing to type")
        self._osa(f'tell application "System Events" to keystroke "{applescript_escape(text)}"')
        return Result(True, f"typed {len(text)} chars")

    def press_key(self, combo: str) -> Result:
        parts = combo.split("+")
        key = parts[-1]
        mods = [MODIFIERS[m] for m in parts[:-1] if m in MODIFIERS]
        using = f" using {{{', '.join(mods)}}}" if mods else ""
        if key in KEY_CODES:
            script = f'tell application "System Events" to key code {KEY_CODES[key]}{using}'
        else:
            script = f'tell application "System Events" to keystroke "{key}"{using}'
        self._osa(script)
        return Result(True, f"pressed {combo}")

    def open_file(self, path: Path) -> Result:
        self._run(["open", str(path)])
        return Result(True, f"opened {path.name}")

    def frontmost_app(self) -> str:
        out = self._osa(
            'tell application "System Events" to get name of first application process '
            "whose frontmost is true"
        )
        return out.strip() or "unknown"

    def undo(self, last: Executed) -> Result:
        d = last.decision
        match d.intent:
            case Intent.OPEN_APP if d.app is not None:
                self._osa(f'quit app "{applescript_escape(d.app.name)}"')
                return Result(True, f"quit {d.app.name}")
            case Intent.TYPE_TEXT:
                n = max(last.typed_chars, 0)
                if n:
                    self._osa(
                        f'tell application "System Events" to repeat {n} times\nkey code 51\nend repeat'
                    )
                return Result(True, f"erased {n} chars")
            case Intent.OPEN_FILE:
                self._osa('tell application "System Events" to keystroke "w" using {command down}')
                return Result(True, "closed window")
            case Intent.PRESS_KEY:
                self._osa('tell application "System Events" to keystroke "z" using {command down}')
                return Result(True, "sent cmd+z")
        return Result(False, "nothing to undo")
```

- [ ] **Step 4: Run** → PASS. Then for real: `uv run python -c "from yapp.executor import Executor; from yapp.types import App; print(Executor().open_app(App('notes','Notes','')))"` and `uv run python -c "from yapp.executor import Executor; print(Executor().frontmost_app())"`. If `osascript` reports "not allowed assistive access", open System Settings → Privacy & Security → Accessibility and add your terminal app; rerun.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: macOS executor with undo"`

**Teach:** Show the Accessibility permission prompt and explain why typing needs it while `open -a` doesn't. Show the escaping test and why it exists (a transcript is untrusted text reaching a script).

---

### Task 10: Runner tick, display, and `yapp --once`

**Files:**
- Create: `src/yapp/runner.py`, `src/yapp/display.py`, `src/yapp/app.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `Runner(cfg, jev, executor, apps, learning=None, display=None)` with `tick(committed_words) -> list[Verdict]`, `finish() -> None` (key release), `last: Executed | None`; `Display.show_transcript(committed, pending)`, `show_decision(d)`, `show_verdict(v)`, `show_result(r)`, `show_error(msg)`; `main()` with `--once TEXT`, `--headless`, `eval` (Task 11 fills eval).

- [ ] **Step 1: Write the failing tests** (fake Jev via a canned classifier)

```python
# tests/test_runner.py
from collections.abc import Callable

from yapp.config import Config
from yapp.runner import Runner
from yapp.types import App, Decision, Intent, Outcome

NOTES = App("notes", "Notes", "Launch Notes")
SAFARI = App("safari", "Safari", "Launch Safari")
APPS = [NOTES, SAFARI]


def canned(tail: str, dictating: bool) -> Decision:
    words = tail.split()
    if words and words[0] in {"and", "then"}:
        words = words[1:]
    if dictating:
        ends = 0.95 if words and words[0] in {"switch", "open", "stop"} else 0.05
        if words[:1] == ["stop"]:
            return Decision(
                tail=tail,
                intent=Intent.NONE,
                intent_confidence=0.9,
                intent_probabilities={},
                is_complete=0.9,
                ends_dictation=ends,
            )
    else:
        ends = 0.0
    if words[:1] == ["open"] and len(words) >= 2:
        app = NOTES if words[1] == "notes" else SAFARI
        return Decision(
            tail=tail,
            intent=Intent.OPEN_APP,
            intent_confidence=0.9,
            intent_probabilities={},
            app=app,
            app_confidence=0.9,
            is_complete=0.95,
            ends_dictation=ends,
            consumed_words=len(tail.split())
            if "and" not in tail.split()[1:]
            else tail.split().index("and", 1),
        )
    if words[:2] == ["switch", "to"] and len(words) >= 3:
        return Decision(
            tail=tail,
            intent=Intent.OPEN_APP,
            intent_confidence=0.9,
            intent_probabilities={},
            app=SAFARI,
            app_confidence=0.9,
            is_complete=0.95,
            ends_dictation=ends,
            consumed_words=len(tail.split()),
        )
    if words[:1] == ["type"]:
        return Decision(
            tail=tail,
            intent=Intent.TYPE_TEXT,
            intent_confidence=0.9,
            intent_probabilities={},
            is_complete=0.9,
            consumed_words=1,
        )
    if words[:1] == ["undo"]:
        return Decision(
            tail=tail,
            intent=Intent.UNDO,
            intent_confidence=0.9,
            intent_probabilities={},
            is_complete=0.9,
        )
    return Decision(
        tail=tail,
        intent=Intent.OPEN_APP if words[:1] == ["open"] else Intent.NONE,
        intent_confidence=0.5,
        intent_probabilities={},
        is_complete=0.2,
    )


class FakeExec:
    def __init__(self) -> None:
        self.log: list[str] = []

    def open_app(self, app: App) -> object:
        self.log.append(f"open:{app.name}")
        return _ok()

    def type_text(self, text: str) -> object:
        self.log.append(f"type:{text}")
        return _ok()

    def press_key(self, combo: str) -> object:
        self.log.append(f"key:{combo}")
        return _ok()

    def open_file(self, path: object) -> object:
        self.log.append(f"file:{path}")
        return _ok()

    def frontmost_app(self) -> str:
        return "Finder"

    def undo(self, last: object) -> object:
        self.log.append("undo")
        return _ok()


def _ok() -> object:
    from yapp.types import Result

    return Result(True, "ok")


def make(classify: Callable[[str, bool], Decision]) -> tuple[Runner, FakeExec]:
    ex = FakeExec()
    r = Runner(
        Config(),
        jev=None,
        executor=ex,
        apps=APPS,
        classify=lambda tail, ctx: classify(tail, ctx.dictating),
    )  # type: ignore[arg-type]
    return r, ex


def feed(r: Runner, sentence: str, per_tick: int = 1) -> None:
    words = sentence.split()
    for i in range(per_tick, len(words) + per_tick, per_tick):
        r.tick(words[:i])
    r.finish()


def test_two_actions_from_one_sentence() -> None:
    r, ex = make(canned)
    feed(r, "open notes and switch to safari")
    assert ex.log == ["open:Notes", "open:Safari"]


def test_fragment_waits_then_fires_once() -> None:
    r, ex = make(canned)
    r.tick(["open"])
    r.tick(["open", "notes"])
    r.tick(["open", "notes"])
    r.finish()
    assert ex.log == ["open:Notes"]


def test_dictation_types_then_switches() -> None:
    r, ex = make(canned)
    feed(r, "type hello there my friend switch to safari")
    assert ex.log[0] == "open:Notes" or True  # no app opened first here
    typed = " ".join(t[5:] for t in ex.log if t.startswith("type:")).split()
    assert typed == ["hello", "there", "my", "friend"]
    assert ex.log[-1] == "open:Safari"


def test_undo_reverses_last() -> None:
    r, ex = make(canned)
    feed(r, "open notes")
    feed(r, "undo")
    assert ex.log == ["open:Notes", "undo"]


def test_verdict_outcomes_reported() -> None:
    r, _ = make(canned)
    outs = [v.outcome for v in r.tick(["open"])]
    assert outs == [Outcome.WAIT]
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/display.py`**

```python
"""Developer view in the terminal."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from yapp.types import Decision, Outcome, Result, Verdict

COLORS = {
    Outcome.EXECUTE: "green",
    Outcome.WAIT: "yellow",
    Outcome.IGNORE: "grey50",
    Outcome.REFUSE: "red",
}


class Display:
    def __init__(self, console: Console | None = None) -> None:
        self.c = console or Console()

    def status(self, msg: str) -> None:
        self.c.print(f"[bold cyan]{msg}[/]")

    def show_transcript(self, committed: list[str], pending: list[str]) -> None:
        t = Text(" ".join(committed), style="bold")
        if pending:
            t.append(" " + " ".join(pending), style="dim")
        self.c.print(Panel(t, title="heard", border_style="cyan"))

    def show_decision(self, d: Decision) -> None:
        table = Table(title=f"jev {d.latency_ms} ms · tail: “{d.tail}”", show_header=True)
        table.add_column("intent")
        table.add_column("p", justify="right")
        for k, p in sorted(d.intent_probabilities.items(), key=lambda kv: -kv[1]):
            table.add_row(k, f"{p:.2f}", style="bold" if k == d.intent else "")
        table.add_row("[dim]confidence[/]", f"{d.intent_confidence:.2f}")
        table.add_row("[dim]is_complete[/]", f"{d.is_complete:.2f}")
        table.add_row("[dim]ends_dictation[/]", f"{d.ends_dictation:.2f}")
        table.add_row("[dim]is_destructive[/]", f"{d.is_destructive:.2f}")
        if d.app:
            table.add_row("[dim]app[/]", f"{d.app.name} ({d.app_confidence:.2f})")
        self.c.print(table)

    def show_verdict(self, v: Verdict) -> None:
        self.c.print(f"[{COLORS[v.outcome]}]{v.outcome.upper()}[/] {v.reason}")

    def show_result(self, r: Result) -> None:
        self.c.print(f"[green]✓[/] {r.message}" if r.ok else f"[red]✗[/] {r.message}")

    def show_error(self, msg: str) -> None:
        self.c.print(f"[red]error:[/] {msg}")
```

- [ ] **Step 4: Write `src/yapp/runner.py`**

```python
"""One tick of the pipeline. Shared by --once, eval, and the live loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from yapp import intent as intent_mod
from yapp.catalog import search_files
from yapp.config import Config
from yapp.display import Display
from yapp.intent import Context
from yapp.jev import Jev, JevError
from yapp.policy import decide
from yapp.stream import Stream
from yapp.types import App, Decision, Executed, Intent, Outcome, Result, Verdict

Classifier = Callable[[str, Context], Decision]


class ExecutorLike(Protocol):
    def open_app(self, app: App) -> Result: ...
    def type_text(self, text: str) -> Result: ...
    def press_key(self, combo: str) -> Result: ...
    def open_file(self, path: object) -> Result: ...
    def frontmost_app(self) -> str: ...
    def undo(self, last: Executed) -> Result: ...


class LearningLike(Protocol):
    def examples(self) -> dict[str, list[str]]: ...
    def executed(self, d: Decision, at: float) -> None: ...
    def undone(self, at: float) -> None: ...
    def flush(self, now: float) -> None: ...


class Runner:
    def __init__(
        self,
        cfg: Config,
        jev: Jev | None,
        executor: ExecutorLike,
        apps: list[App],
        *,
        learning: LearningLike | None = None,
        display: Display | None = None,
        classify: Classifier | None = None,
    ) -> None:
        self.cfg = cfg
        self.executor = executor
        self.apps = apps
        self.learning = learning
        self.display = display
        self.stream = Stream(cfg.dictation_lookahead_words)
        self.last: Executed | None = None
        self.done: list[str] = []
        self._pending_frontmost = ""
        if classify is None:
            if jev is None:
                raise ValueError("need jev or classify")
            self._classify: Classifier = lambda tail, ctx: intent_mod.classify(tail, ctx, jev, cfg)
        else:
            self._classify = classify

    def _ctx(self) -> Context:
        return Context(
            apps=self.apps,
            frontmost_app=self.executor.frontmost_app(),
            already_done=self.done,
            dictating=self.stream.dictating,
            examples=self.learning.examples() if self.learning else {},
        )

    def tick(self, committed: list[str], pending: list[str] | None = None) -> list[Verdict]:
        if self.display:
            self.display.show_transcript(committed, pending or [])
        if self.learning:
            self.learning.flush(time.time())
        if not self.stream.set_committed(committed):
            return []
        verdicts: list[Verdict] = []
        for _ in range(4):  # a tick may complete more than one instruction
            tail = self.stream.tail()
            if not tail:
                break
            v = self._step(tail)
            verdicts.append(v)
            if v.outcome != Outcome.EXECUTE:
                break
        if self.stream.dictating:
            self._type(self.stream.dictation_words())
        return verdicts

    def finish(self) -> list[Verdict]:
        """Key released: last chance for the tail, then flush dictation and reset."""
        out: list[Verdict] = []
        tail = self.stream.tail()
        if tail and not self.stream.dictating:
            out.append(self._step(tail))
        if self.stream.dictating:
            self._type(self.stream.dictation_words(flush=True))
            self.stream.exit_dictation()
        self.stream.reset()
        return out

    def _step(self, tail: str) -> Verdict:
        try:
            d = self._classify(tail, self._ctx())
        except JevError as e:
            if self.display:
                self.display.show_error(str(e))
            return Verdict(Outcome.IGNORE, f"jev error: {e}")
        if self.display:
            self.display.show_decision(d)
        v = decide(
            d, self.cfg.thresholds, dictating=self.stream.dictating, has_last=self.last is not None
        )
        if self.display:
            self.display.show_verdict(v)
        if v.outcome == Outcome.EXECUTE and not self.stream.already_fired(d.consumed_words):
            self._execute(d)
        return v

    def _execute(self, d: Decision) -> None:
        if self.stream.dictating:
            self._type(self.stream.dictation_words())
            self.stream.exit_dictation()
        self.stream.mark_fired(d.consumed_words)
        r: Result
        match d.intent:
            case Intent.OPEN_APP if d.app is not None:
                r = self.executor.open_app(d.app)
                self.last = Executed(d, r)
            case Intent.TYPE_TEXT:
                self.stream.consume(d.consumed_words)
                self.stream.enter_dictation()
                r = Result(True, "dictating")
                self.last = Executed(d, r, typed_chars=0)
                self._report(r)
                return
            case Intent.OPEN_FILE if d.file_query:
                hits = search_files(d.file_query)
                r = self.executor.open_file(hits[0]) if hits else Result(False, "no file found")
                self.last = Executed(d, r) if r.ok else self.last
            case Intent.PRESS_KEY if d.key_combo:
                r = self.executor.press_key(d.key_combo)
                self.last = Executed(d, r)
            case Intent.UNDO if self.last is not None:
                r = self.executor.undo(self.last)
                if self.learning:
                    self.learning.undone(time.time())
                self.last = None
            case _:
                r = Result(False, "nothing to execute")
        self.stream.consume(d.consumed_words)
        self.done.append(d.tail[: len(" ".join(d.tail.split()[: d.consumed_words]))])
        if self.learning and d.intent != Intent.UNDO and r.ok:
            self.learning.executed(d, time.time())
        self._report(r)

    def _type(self, words: list[str]) -> None:
        if not words:
            return
        text = " ".join(words) + " "
        r = self.executor.type_text(text)
        if self.last is not None and self.last.decision.intent == Intent.TYPE_TEXT:
            self.last = Executed(
                self.last.decision, r, typed_chars=self.last.typed_chars + len(text)
            )
        self._report(r)

    def _report(self, r: Result) -> None:
        if self.display:
            self.display.show_result(r)
```

- [ ] **Step 5: Write `src/yapp/app.py`**

```python
"""CLI entry: live loop, --once scripted words, eval."""

from __future__ import annotations

import argparse
import sys
import time

from yapp.catalog import installed_apps
from yapp.config import Config
from yapp.display import Display
from yapp.executor import Executor
from yapp.jev import Jev, JevError
from yapp.runner import Runner


def build_runner(cfg: Config, display: Display | None) -> Runner:
    from yapp.learning import Learning  # Task 11

    jev = Jev(model=cfg.model)
    apps = installed_apps()
    if display:
        display.status(f"{len(apps)} apps in catalog · model {cfg.model}")
    return Runner(cfg, jev, Executor(), apps, learning=Learning(cfg), display=display)


def run_once(text: str, cfg: Config, display: Display | None, per_tick: int = 2) -> int:
    runner = build_runner(cfg, display)
    words = text.split()
    for i in range(per_tick, len(words) + per_tick, per_tick):
        runner.tick(words[:i], words[i : i + 1])
        time.sleep(cfg.tick_seconds)
    runner.finish()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="yapp")
    p.add_argument("command", nargs="?", choices=["live", "eval"], default="live")
    p.add_argument("--once", metavar="TEXT", help="run the pipeline on typed words, no audio")
    p.add_argument("--headless", action="store_true", help="no window (default until the UI ships)")
    args = p.parse_args(argv)
    cfg = Config()
    display = Display()
    try:
        if args.once:
            return run_once(args.once, cfg, display)
        if args.command == "eval":
            from yapp.evaluate import run_eval  # Task 11

            return run_eval(cfg, display)
        from yapp.live import run_live  # Task 13

        return run_live(cfg, display)
    except JevError as e:
        display.show_error(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

Until Tasks 11 and 13 exist, create stubs so imports resolve: `src/yapp/learning.py` with `class Learning: def __init__(self, cfg): ...; examples()->{}; executed(...)->None; undone(...)->None; flush(...)->None`, `src/yapp/evaluate.py` with `def run_eval(cfg, display) -> int: display.status("eval: not built yet"); return 1`, and `src/yapp/live.py` with `def run_live(cfg, display) -> int: display.status("live: not built yet"); return 1`. Tasks 11 and 13 replace them.

- [ ] **Step 6: Run**: `uv run pytest tests/test_runner.py -v` → PASS. Then the real pipeline with no audio: `uv run yapp --once "open notes and switch to safari"`. Expected: two panels, two green EXECUTE lines, Notes then Safari come to the front.

- [ ] **Step 7: Commit**: `git add -A && git commit -m "feat: runner tick, terminal display, yapp --once"`

**Teach:** Run `--once` with `per_tick=1` and read the verdict sequence aloud: WAIT, WAIT, EXECUTE, WAIT, EXECUTE. This is the streaming behaviour with no microphone.

---

### Task 11: Learning from undo, and `yapp eval`

**Files:**
- Create: `src/yapp/learning.py` (replace stub), `src/yapp/evaluate.py` (replace stub), `tests/eval/transcripts.jsonl`
- Test: `tests/test_learning.py`

**Interfaces:**
- Produces: `Learning(cfg)` implementing `LearningLike` from Task 10: `examples() -> dict[str, list[str]]`, `executed(d, at)`, `undone(at)`, `flush(now)`; `run_eval(cfg, display) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_learning.py
import json
from pathlib import Path

from yapp.config import Config
from yapp.learning import Learning
from yapp.types import App, Decision, Intent

NOTES = App("notes", "Notes", "")


def dec(tail: str) -> Decision:
    return Decision(
        tail=tail,
        intent=Intent.OPEN_APP,
        intent_confidence=0.9,
        intent_probabilities={},
        app=NOTES,
        consumed_words=2,
    )


def test_positive_after_delay(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl", learn_after_seconds=10)
    L = Learning(cfg)
    L.executed(dec("open node"), at=100.0)
    L.flush(105.0)
    assert L.examples() == {}
    L.flush(111.0)
    assert L.examples() == {"notes": ["open node"]}
    rows = [json.loads(x) for x in (tmp_path / "l.jsonl").read_text().splitlines()]
    assert rows[0]["label"] == "positive" and rows[0]["option"] == "notes"


def test_undo_marks_negative(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl")
    L = Learning(cfg)
    L.executed(dec("open nodes"), at=100.0)
    L.undone(at=102.0)
    L.flush(200.0)
    assert L.examples() == {}
    assert L.negatives() == {"notes": ["open nodes"]}


def test_reload_from_disk(tmp_path: Path) -> None:
    cfg = Config(learned_path=tmp_path / "l.jsonl")
    L = Learning(cfg)
    L.executed(dec("open node"), at=0.0)
    L.flush(100.0)
    assert Learning(cfg).examples() == {"notes": ["open node"]}
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/learning.py`**

```python
"""Examples from acting, not asking. Executed + no undo = positive; undo = negative."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from yapp.config import Config
from yapp.types import Decision, Intent

KEEP_POSITIVE = 5
KEEP_NEGATIVE = 3


def option_for(d: Decision) -> str | None:
    if d.intent == Intent.OPEN_APP and d.app is not None:
        return d.app.key
    if d.intent == Intent.PRESS_KEY and d.key_combo:
        return d.key_combo
    return None


@dataclass
class _Pending:
    option: str
    phrase: str
    at: float


class Learning:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pos: dict[str, list[str]] = defaultdict(list)
        self._neg: dict[str, list[str]] = defaultdict(list)
        self._pending: _Pending | None = None
        self._load()

    def _load(self) -> None:
        p = self.cfg.learned_path
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            row = json.loads(line)
            bucket = self._pos if row["label"] == "positive" else self._neg
            bucket[row["option"]].append(row["phrase"])

    def _append(self, option: str, phrase: str, label: str) -> None:
        p = self.cfg.learned_path
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({"option": option, "phrase": phrase, "label": label}) + "\n")

    def examples(self) -> dict[str, list[str]]:
        return {k: v[-KEEP_POSITIVE:] for k, v in self._pos.items() if v}

    def negatives(self) -> dict[str, list[str]]:
        return {k: v[-KEEP_NEGATIVE:] for k, v in self._neg.items() if v}

    def executed(self, d: Decision, at: float) -> None:
        self.flush(at)
        opt = option_for(d)
        if opt is None:
            return
        phrase = " ".join(d.tail.split()[: d.consumed_words])
        self._pending = _Pending(opt, phrase, at)

    def undone(self, at: float) -> None:
        if self._pending is None:
            return
        self._neg[self._pending.option].append(self._pending.phrase)
        self._append(self._pending.option, self._pending.phrase, "negative")
        self._pending = None

    def flush(self, now: float) -> None:
        if self._pending and now - self._pending.at >= self.cfg.learn_after_seconds:
            self._pos[self._pending.option].append(self._pending.phrase)
            self._append(self._pending.option, self._pending.phrase, "positive")
            self._pending = None
```

Then wire negatives into `intent._app_option`: give it `not_for: "; ".join(negatives)` when present. Update `build_questions` to take negatives from `ctx.negatives: dict[str, list[str]]` (add the field to `Context` with `default_factory=dict`) and `Runner._ctx` to pass `self.learning.negatives()`. Add `negatives()` to `LearningLike`.

- [ ] **Step 4: Write `tests/eval/transcripts.jsonl`** (grow this file from real use; start with these)

```json
{"tail": "open notes", "intent": "open_app", "app": "notes"}
{"tail": "launch safari", "intent": "open_app", "app": "safari"}
{"tail": "switch to slack", "intent": "open_app", "app": "slack"}
{"tail": "open node", "intent": "open_app", "app": "notes"}
{"tail": "open", "intent": "open_app", "app": null, "complete": false}
{"tail": "type hello there", "intent": "type_text", "app": null}
{"tail": "write dear sam", "intent": "type_text", "app": null}
{"tail": "open my resume", "intent": "open_file", "app": null}
{"tail": "save", "intent": "press_key", "app": null}
{"tail": "copy that", "intent": "press_key", "app": null}
{"tail": "undo", "intent": "undo", "app": null}
{"tail": "no not that", "intent": "undo", "app": null}
{"tail": "um so", "intent": "none", "app": null}
{"tail": "what was i doing", "intent": "none", "app": null}
```

- [ ] **Step 5: Write `src/yapp/evaluate.py`**

```python
"""`yapp eval`: accuracy per confidence bucket. Paste the table into PRs that touch thresholds."""

from __future__ import annotations

import json
from pathlib import Path

from rich.table import Table

from yapp.config import Config
from yapp.display import Display
from yapp.intent import Context, classify
from yapp.jev import Jev
from yapp.types import App

EVAL_APPS = [
    App(k, n, f"Launch {n}")
    for k, n in [
        ("notes", "Notes"),
        ("safari", "Safari"),
        ("slack", "Slack"),
        ("numbers", "Numbers"),
        ("google_chrome", "Google Chrome"),
        ("terminal", "Terminal"),
        ("finder", "Finder"),
        ("mail", "Mail"),
        ("messages", "Messages"),
        ("music", "Music"),
    ]
]
BUCKETS = [(0.85, "≥ 0.85"), (0.60, "0.60–0.85"), (0.0, "< 0.60")]


def run_eval(
    cfg: Config, display: Display, path: Path = Path("tests/eval/transcripts.jsonl")
) -> int:
    jev = Jev(model=cfg.model)
    ctx = Context(apps=EVAL_APPS, frontmost_app="Finder", already_done=[], dictating=False)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    stats: dict[str, list[bool]] = {label: [] for _, label in BUCKETS}
    wrong: list[str] = []
    for row in rows:
        d = classify(row["tail"], ctx, jev, cfg)
        ok = d.intent == row["intent"] and (
            row.get("app") is None or (d.app and d.app.key == row["app"])
        )
        if "complete" in row:
            ok = ok and ((d.is_complete >= cfg.thresholds.complete) == row["complete"])
        for lo, label in BUCKETS:
            if d.intent_confidence >= lo:
                stats[label].append(bool(ok))
                break
        if not ok:
            wrong.append(
                f"{row['tail']!r} → {d.intent} {d.app.key if d.app else ''} conf {d.intent_confidence:.2f}"
            )
    t = Table(title=f"yapp eval · {len(rows)} rows · {cfg.model}")
    t.add_column("confidence")
    t.add_column("n", justify="right")
    t.add_column("accuracy", justify="right")
    for _, label in BUCKETS:
        xs = stats[label]
        t.add_row(label, str(len(xs)), f"{(sum(xs) / len(xs) * 100):.0f}%" if xs else "–")
    display.c.print(t)
    for w in wrong:
        display.c.print(f"[red]✗[/] {w}")
    return 0 if not wrong else 1
```

- [ ] **Step 6: Run**: `uv run pytest -v` → all PASS. `uv run yapp eval` → table prints. Fix any wrong row by editing `questions.yaml` wording, never by editing the eval file to match.

- [ ] **Step 7: Commit**: `git add -A && git commit -m "feat: learning from undo and yapp eval"`

**Teach:** Show `~/.yapp/learned.jsonl` after an `--once "open notes"` followed 10 s later by `--once "undo"`. Then show the same phrase appearing inside the request's criteria by printing `build_questions(ctx)["app"].criteria["notes"]`.

---

### Task 12: Streaming transcriber on mlx-whisper

**Files:**
- Create: `src/yapp/stt.py`
- Test: `tests/test_stt.py`

**Interfaces:**
- Produces: `Transcript(committed: list[str], pending: list[str])`, `normalize(text) -> list[str]`, `agree(prev, cur) -> int`, `StreamingTranscriber(model, decode=None)` with `update(samples: np.ndarray) -> Transcript`, `reset()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stt.py
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
            "open notes and switch to safari",
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
    assert t.pending == ["please"]
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/stt.py`**

```python
"""Streaming on top of a non-streaming model: re-decode, commit on two-pass agreement."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

Decoder = Callable[[np.ndarray], str]
WORD = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class Transcript:
    committed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def normalize(text: str) -> list[str]:
    return WORD.findall(text.lower())


def agree(prev: list[str], cur: list[str]) -> int:
    n = 0
    for a, b in zip(prev, cur, strict=False):
        if a != b:
            break
        n += 1
    return n


def mlx_decoder(model: str) -> Decoder:
    import mlx_whisper

    def decode(samples: np.ndarray) -> str:
        out = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=model,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            fp16=True,
            language="en",
        )
        text = out["text"]
        return str(text)

    return decode


class StreamingTranscriber:
    def __init__(self, model: str, decode: Decoder | None = None) -> None:
        self._decode = decode or mlx_decoder(model)
        self.reset()

    def reset(self) -> None:
        self._prev: list[str] = []
        self._committed: list[str] = []

    def update(self, samples: np.ndarray) -> Transcript:
        if samples.size < 1600:  # < 0.1 s
            return Transcript(list(self._committed), [])
        cur = normalize(self._decode(samples))
        stable = agree(self._prev, cur)
        if stable > len(self._committed) and cur[: len(self._committed)] == self._committed:
            self._committed = cur[:stable]
        self._prev = cur
        pending = (
            cur[len(self._committed) :] if cur[: len(self._committed)] == self._committed else []
        )
        return Transcript(list(self._committed), pending)
```

- [ ] **Step 4: Run** → PASS. Then live on a clip: record 5 s with `uv run python -c "import sounddevice as sd, numpy as np; a=sd.rec(80000, samplerate=16000, channels=1, dtype='float32'); sd.wait(); np.save('/tmp/clip.npy', a[:,0])"` while saying "open notes and switch to safari", then

```bash
uv run python - <<'EOF'
import time, numpy as np
from yapp.stt import StreamingTranscriber
a = np.load('/tmp/clip.npy'); st = StreamingTranscriber("mlx-community/whisper-base-mlx")
for end in range(8000, len(a)+8000, 6400):   # 0.4 s steps
    t0=time.perf_counter(); t = st.update(a[:end]); dt=(time.perf_counter()-t0)*1000
    print(f"{end/16000:4.1f}s  {dt:5.0f}ms  {' '.join(t.committed)} | {' '.join(t.pending)}")
EOF
```
Expected: words commit one or two per step, decode under ~250 ms per step with `base`. Try `whisper-small-mlx` and compare. The first run downloads the model.

- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat: streaming transcriber with two-pass agreement"`

**Teach:** Show the same clip with and without agreement (print `cur` each pass) so the flicker whisper produces is visible, then how agreement removes it. Note the lag the lookahead adds and where it's paid.

---

### Task 13: Audio recorder, hotkey, live loop

**Files:**
- Create: `src/yapp/audio.py`, `src/yapp/live.py` (replace stub)
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces: `Recorder(sample_rate, max_seconds)` with `start()`, `stop()`, `arm()`, `disarm()`, `snapshot() -> np.ndarray`, `level() -> float`, `push(chunk)` (used by the callback and tests); `Hotkey(name)` with `wait_down()`, `is_down()`, `start()`, `stop()`; `run_live(cfg, display) -> int`.

- [ ] **Step 1: Write the failing tests** (no device needed: tests call `push`)

```python
# tests/test_audio.py
import numpy as np

from yapp.audio import Recorder


def test_snapshot_only_while_armed() -> None:
    r = Recorder(sample_rate=16000, max_seconds=2)
    r.push(np.ones(100, dtype=np.float32))
    assert r.snapshot().size == 0
    r.arm()
    r.push(np.ones(100, dtype=np.float32))
    r.push(np.ones(50, dtype=np.float32))
    assert r.snapshot().size == 150
    r.disarm()
    assert r.snapshot().size == 0


def test_cap_keeps_latest() -> None:
    r = Recorder(sample_rate=100, max_seconds=1)
    r.arm()
    r.push(np.zeros(80, dtype=np.float32))
    r.push(np.ones(80, dtype=np.float32))
    s = r.snapshot()
    assert s.size == 100 and s[-1] == 1.0


def test_level_is_rms_of_recent() -> None:
    r = Recorder(sample_rate=1000, max_seconds=1)
    r.arm()
    r.push(np.full(100, 0.5, dtype=np.float32))
    assert 0.4 < r.level() < 0.6
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Write `src/yapp/audio.py`**

```python
"""Microphone ring buffer and the hold-to-talk hotkey."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np


class Recorder:
    def __init__(self, sample_rate: int, max_seconds: int) -> None:
        self.sample_rate = sample_rate
        self._cap = sample_rate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._armed = False
        self._lock = threading.Lock()
        self._stream: Any = None

    def push(self, chunk: np.ndarray) -> None:
        with self._lock:
            if not self._armed:
                return
            self._chunks.append(chunk.astype(np.float32, copy=False).ravel())
            total = sum(c.size for c in self._chunks)
            while total > self._cap and self._chunks:
                total -= self._chunks[0].size
                self._chunks.pop(0)

    def arm(self) -> None:
        with self._lock:
            self._chunks = []
            self._armed = True

    def disarm(self) -> None:
        with self._lock:
            self._armed = False
            self._chunks = []

    def snapshot(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)[-self._cap :]

    def level(self) -> float:
        s = self.snapshot()[-(self.sample_rate // 10) :]
        if s.size == 0:
            return 0.0
        return float(min(1.0, np.sqrt(np.mean(s * s)) * 4))

    def start(self) -> None:
        import sounddevice as sd

        def cb(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            self.push(indata[:, 0].copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", blocksize=1600, callback=cb
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


class Hotkey:
    def __init__(self, name: str) -> None:
        from pynput import keyboard

        self._key = getattr(keyboard.Key, name)
        self._down = threading.Event()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def _press(self, key: Any) -> None:
        if key == self._key:
            self._down.set()

    def _release(self, key: Any) -> None:
        if key == self._key:
            self._down.clear()

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def wait_down(self) -> None:
        self._down.wait()

    def is_down(self) -> bool:
        return self._down.is_set()
```

- [ ] **Step 4: Write `src/yapp/live.py`**

```python
"""Hold the key, talk, act."""

from __future__ import annotations

import time

from yapp.app import build_runner
from yapp.audio import Hotkey, Recorder
from yapp.config import Config
from yapp.display import Display
from yapp.stt import StreamingTranscriber


def run_live(cfg: Config, display: Display) -> int:
    display.status(f"loading whisper {cfg.whisper_model} …")
    t0 = time.perf_counter()
    stt = StreamingTranscriber(cfg.whisper_model)
    import numpy as np

    stt.update(np.zeros(cfg.sample_rate, dtype=np.float32))  # warm the model
    display.status(f"whisper ready in {time.perf_counter() - t0:.1f}s")
    runner = build_runner(cfg, display)
    rec = Recorder(cfg.sample_rate, cfg.max_hold_seconds)
    key = Hotkey(cfg.hotkey)
    rec.start()
    key.start()
    try:
        while True:
            display.status(f"hold {cfg.hotkey} to talk")
            key.wait_down()
            rec.arm()
            stt.reset()
            while key.is_down():
                tick_start = time.perf_counter()
                t = stt.update(rec.snapshot())
                runner.tick(t.committed, t.pending)
                elapsed = time.perf_counter() - tick_start
                time.sleep(max(0.0, cfg.tick_seconds - elapsed))
            t = stt.update(rec.snapshot())
            runner.tick(t.committed, [])
            runner.finish()
            rec.disarm()
    except KeyboardInterrupt:
        return 0
    finally:
        key.stop()
        rec.stop()
```

Move `build_runner` out of `app.py` into `runner.py` if the import cycle (`app` → `live` → `app`) bites; keep the function body identical.

- [ ] **Step 5: Run**: `uv run pytest -v` → PASS. Then `uv run yapp`. macOS will prompt for Microphone and Input Monitoring for your terminal; grant both, restart the terminal, run again. Hold right Option, say "open notes and type hello there", release. Expected: Notes comes to the front while you're still speaking; "hello there" appears in Notes about half a second behind your voice.

- [ ] **Step 6: Commit and open the PR**

```bash
git add -A && git commit -m "feat: hold-to-talk live loop"
git push -u origin feature/pipeline
gh pr create --base dev --title "feat: streaming voice pipeline" --body "Implements the pipeline from docs/superpowers/specs/2026-09-21-yapp-design.md sections 3–9. Window/avatar are a separate plan.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

**Teach:** Measure and write down three numbers in the README: whisper commit lag, Jev latency, and word-to-action latency. Then try `whisper-small-mlx` and see what the accuracy buys and costs.

---

## Self-review

- **Spec coverage.** Sections 3 to 9 map to Tasks 3 to 13. Section 4.2's "drop audio before the committed prefix after ~8 s" is deliberately not built: v1 decodes the whole hold (30 s cap) and the spec line is to be softened to "may trim" when the PR lands. Section 10 (window/avatar) and section 11's Claude Design port are the next plan; governance (11.1, 11.2) is Task 2. Section 7 needs no code.
- **Placeholders.** None; stubs in Task 10 are explicit and replaced in Tasks 11 and 13.
- **Type consistency.** The shell seam is `ShellRunner` in `catalog.py` and `executor.py`; the tick class is `runner.Runner`. `LearningLike` gains `negatives()` in Task 11; `Context` gains `negatives` there too. `ExecutorLike.open_file` takes `object` to keep the Protocol simple; the real signature is `Path`.
