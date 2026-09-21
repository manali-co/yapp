# Yapp: voice-narrated computer use, design spec

Date: 2026-09-21
Status: draft for review
Repo: `manali-co/yapp` (open source, MIT)

## 1. What Yapp is

Yapp is a macOS command-line app. You hold a key, say what you want done on the Mac,
release the key, and it happens. Speech is transcribed locally with Whisper. The
transcript is turned into a typed decision by TypeSafe AI's Jev model. Code executes the
decision natively (launch apps, type text, open files) and shows every intermediate
result in the terminal so the pipeline is legible.

Yapp is also a learning project. Each module is small, has one job, and is explained and
run in isolation before it is wired to the next one.

### Goals

- Hold-to-talk narration that reliably opens apps, types text into the focused app,
  opens files found by Spotlight, and presses a small set of keys.
- Jev is the only model in v1. Free text is never requested from a model; code extracts it.
- Yapp acts or stays quiet. It never asks a question. Every action is gated by Jev's
  confidence with per-action thresholds; below threshold nothing happens.
- Wrong actions are cheap: a spoken "undo" reverses the last action, and that signal
  teaches the app (section 4.9).
- The intent layer is testable with plain strings, no microphone.
- The design leaves a clean slot for a text-generating LLM (compound commands,
  screen understanding) without a rewrite.

### Non-goals for v1

- Always-on listening, wake words, confirmation prompts of any kind.
- Reading the screen, clicking coordinates, or anything Jev cannot do from text.
- A menu-bar app or web dashboard. v1 has one small floating window (section 10).
- Multi-step commands ("open Notes and write a grocery list"). v1 detects them and asks
  for one thing at a time.
- Windows or Linux.

## 2. How Jev works (the model this design is built around)

Jev is a "System One" decision model, not a text generator. One request carries a
`state` (a string, JSON object, or array of text) and a set of named questions. Every
question is evaluated in parallel against the same state and the response returns typed
answers with probabilities. Three primitives exist:

| Primitive | Input | Output |
|---|---|---|
| `choice` | instructions and a dict of `key: description` (max 255) | chosen key, per-option probabilities, confidence |
| `score` | instructions and 2 to 10 ordered level descriptions | level (may be fractional), probabilities, confidence |
| `noul` | a yes/no statement | probability 0 to 1 |

Facts that drive the design:

- Latency 70 to 500 ms per call. Output tokens are free. This is what makes one call per
  utterance affordable in a realtime loop.
- Jev cannot return a value outside the schema, but it can return the wrong valid one.
  `confidence` (0 to 1, derived from how concentrated the probabilities are) is the
  safety lever. Vendor guidance: high acts, medium confirms, low does nothing, and
  thresholds differ per action by consequence.
- Jev cannot extract free text, count, do arithmetic, or reason about dates. Those are
  done in code.
- Accuracy drops when state carries irrelevant material. Code retrieves and filters first.
- Option order affects results; catalogs must be built deterministically.
- Endpoint `POST https://api.typesafe.ai/v1/systemone`, header
  `Authorization: Bearer $TYPESAFE_API_KEY`, body `{state, model, questions}`.
  Python SDK `typesafe-sdk` (`TypeSafeClient().system_one(state=..., questions=...)`).
  Model pinned to a version string in config (`jev-1.13.0` at time of writing) so
  tuned thresholds do not drift when `jev-latest` moves.

## 3. Architecture

Single Python process, a linear pipeline of modules that communicate through plain
dataclasses. No server, no threads except the audio callback.

```
hold key ──► audio.py ──► stt.py ──► intent.py ──► policy.py ──► executor.py
             (samples)    (text)     (Decision)    (Verdict)     (Result)
                                        │
                                   catalog.py (installed apps, Spotlight)
                                        │
                                     jev.py (HTTP client wrapper)
```

`app.py` owns the loop and the terminal display. Each stage emits an event to the display
so the user sees the transcript, Jev's full probability table, the policy verdict, and the
executed action for every utterance.

### 3.1 Package layout

```
yapp/
  pyproject.toml            uv project, ruff, mypy --strict, pytest
  LICENSE                   MIT
  README.md
  src/yapp/
    __init__.py
    app.py                  CLI entry (`yapp`), main loop, terminal UI (rich)
    config.py               settings: model id, thresholds, hotkey, whisper model
    audio.py                hold-to-talk recorder
    stt.py                  local whisper transcription
    catalog.py              installed apps + Spotlight search
    jev.py                  thin wrapper over typesafe-sdk with typed results
    intent.py               builds state + questions, calls jev, returns Decision
    policy.py               confidence gates -> Verdict
    executor.py             macOS actions
    types.py                dataclasses shared across modules
  tests/
    test_intent.py          transcript -> Decision, hits the real API (cheap)
    test_policy.py          pure
    test_executor.py        fake shell
    test_catalog.py         fake mdfind output
  ui/                       avatar + window bundle ported from Claude Design (section 10)
  docs/design/              avatar-brief.md, the brief given to Claude Design
  docs/superpowers/specs/   this file
  docs/superpowers/plans/   implementation plan
  CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, .github/   governance (section 11)
```

### 3.2 Shared types (`types.py`)

```python
class Intent(StrEnum):
    OPEN_APP = "open_app"
    TYPE_TEXT = "type_text"
    OPEN_FILE = "open_file"
    PRESS_KEY = "press_key"
    UNDO = "undo"
    NONE = "none"

@dataclass(frozen=True)
class App:
    key: str            # stable slug, e.g. "notes"
    name: str           # display name passed to `open -a`, e.g. "Notes"
    description: str    # one line shown to Jev

@dataclass(frozen=True)
class Decision:
    transcript: str
    intent: Intent
    intent_confidence: float
    intent_probabilities: dict[str, float]
    app: App | None                  # for OPEN_APP
    app_confidence: float | None
    text: str | None                 # for TYPE_TEXT, extracted in code
    key_combo: str | None            # for PRESS_KEY, e.g. "cmd+s"
    file_query: str | None           # for OPEN_FILE, extracted in code
    is_compound: float               # noul
    is_destructive: float            # noul
    raw: dict[str, Any]              # full Jev response, for the display

class Outcome(StrEnum):
    EXECUTE = "execute"
    IGNORE = "ignore"     # below threshold or intent none: quiet
    REFUSE = "refuse"     # destructive or compound: quiet, with a reason shown

@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str          # human-readable, shown in the terminal

@dataclass(frozen=True)
class Result:
    ok: bool
    message: str
```

## 4. Module contracts

### 4.1 `audio.py`: hold-to-talk recorder

- Depends on `sounddevice` (PortAudio) and `pynput` for the global hotkey.
- `record_while_held(key: Key) -> np.ndarray` blocks until the hotkey is pressed, records
  16 kHz mono float32 while held, returns the buffer on release. Buffers shorter than
  0.3 s are discarded (accidental taps).
- Default hotkey: right Option. Configurable.
- macOS requires Input Monitoring permission for the terminal to observe the global key,
  and Microphone permission. The app checks for a captured buffer of all zeros and prints
  a pointer to the System Settings pane if so.

### 4.2 `stt.py`: local transcription

- `transcribe(samples: np.ndarray) -> str` using `mlx-whisper` with the
  `mlx-community/whisper-small-mlx` model by default (configurable; `base` for speed,
  `large-v3-turbo` for accuracy). Passing the numpy array directly avoids ffmpeg.
- First call downloads the model; the app prints progress. Model is loaded once at
  startup and held in memory.
- Returns stripped text; empty string when whisper returns nothing.

### 4.3 `catalog.py`: the native index

- `installed_apps() -> list[App]`: union of `mdfind "kMDItemKind == 'Application'"` and the
  contents of `/Applications`, `/System/Applications`, `~/Applications`. Deduplicated by
  name, sorted by name so option order is deterministic across runs. Description is the
  app name plus its bundle-level `kMDItemDescription` when present, else the name alone.
  Cached for the process lifetime.
- `narrow(apps, transcript, limit=60) -> list[App]`: cheap fuzzy match (`rapidfuzz`) of
  the transcript's words against app names. Returns the top `limit` apps, always including
  exact and prefix matches. This keeps the `choice` well under 255 options and removes
  irrelevant material from the state, which the vendor docs say improves accuracy.
- `search_files(query: str, limit=8) -> list[Path]`: `mdfind -name <query>` restricted to
  the user's home, most recently modified first.

### 4.4 `jev.py`: typed client wrapper

- Wraps `typesafe_sdk.TypeSafeClient` (async variant not needed in v1).
- `ask(state: dict, questions: dict) -> JevResponse` where `JevResponse` exposes
  `.choice(name) -> (key, confidence, probabilities)` and `.noul(name) -> float`, plus
  `.raw`.
- Reads `TYPESAFE_API_KEY` from the environment. Fails fast at startup with a clear
  message if it is unset.
- Retries once on network error; any API error surfaces as a `JevError` that the loop
  reports and continues from. A failed call never executes anything.

### 4.5 `intent.py`: transcript to Decision (the only module that designs Jev questions)

State sent to Jev, as a JSON object with descriptive field names:

```json
{
  "utterance": "open notes",
  "frontmost_app": "Safari",
  "recent_utterances": ["open safari", "go to youtube"]
}
```

`frontmost_app` comes from `executor.frontmost_app()` (an AppleScript one-liner).
`recent_utterances` is the last three transcripts. Both are context only.

Questions, all in one request (speculative fan-out):

| Name | Type | Instructions | Options |
|---|---|---|---|
| `intent` | choice | "What does the user want the computer to do?" | `open_app`: "Launch or switch to an application"; `type_text`: "Type words into the app that is currently focused"; `open_file`: "Open a document, note, or file by name"; `press_key`: "Press a keyboard shortcut such as save, copy, or paste"; `undo`: "Reverse or cancel what Yapp just did ('undo', 'no', 'not that')"; `none`: "Not an instruction to the computer, or unclear" |
| `app` | choice | "Which application does the user mean?" | the narrowed catalog from `catalog.narrow`, plus `unsure`: "None of these" |
| `key_combo` | choice | "Which keyboard shortcut does the user mean?" | `cmd+s`: "Save"; `cmd+c`: "Copy"; `cmd+v`: "Paste"; `cmd+a`: "Select all"; `enter`: "Press enter or return"; `escape`: "Escape or cancel"; `unsure` |
| `is_compound` | noul | "The user asks for more than one separate action" | |
| `is_destructive` | noul | "Carrying this out could delete data, send a message, or spend money" | |

Rules:

- Every choice has an explicit "none/unsure" option so Jev is never forced to pick.
- `app` and `key_combo` are asked on every utterance even when intent turns out to be
  something else. Answers for the unselected intent are ignored. This costs nothing and
  saves a round trip.
- Free-text extraction happens in code after Jev answers:
  - `type_text`: strip a leading verb phrase matching `^(type|write|enter|say)\b[:,]?\s*`
    from the utterance; the remainder is `text`. If the remainder is empty, the decision
    degrades to `NONE` with reason "nothing to type".
  - `open_file`: strip `^(open|find|show)\b\s*(my|the)?\s*` and trailing filler like
    "file", "document"; the remainder is `file_query`.
  - These regexes live in `intent.py` and are unit-tested.
- `intent.py` never calls the OS beyond `frontmost_app()`. Tests pass a fake catalog and
  a fake frontmost app.

### 4.6 `policy.py`: confidence gates

Pure function `decide(d: Decision, cfg: Thresholds) -> Verdict`. Two outcomes only:
execute, or stay quiet. Yapp never asks.

| Action | Execute if | Otherwise |
|---|---|---|
| `open_app` | intent conf ≥ 0.60 and app ≠ unsure | ignore |
| `type_text` | intent conf ≥ 0.70 and text non-empty | ignore |
| `open_file` | intent conf ≥ 0.60 and Spotlight returned ≥ 1 hit; opens Jev's top pick | ignore |
| `press_key` | intent conf ≥ 0.70 and combo ≠ unsure | ignore |
| `undo` | intent conf ≥ 0.60 and there is a last action | ignore |
| any | `is_destructive` ≥ 0.50 → refuse, window shows "won't do that: could delete/send/spend" | |
| any | `is_compound` ≥ 0.70 → refuse, window shows "one thing at a time" | |
| `none` | | ignore |

Thresholds start low on purpose: a wrong action costs one "undo", a missed action costs
a repeat. They are named constants in `config.py` and only change with an eval table
(section 6) in the PR. The window shows which threshold fired.

### 4.7 `executor.py`: macOS actions

- `open_app(app: App) -> Result`: `open -a <name>`.
- `type_text(text: str) -> Result`: `osascript -e 'tell application "System Events" to
  keystroke <escaped text>'`. Requires Accessibility permission for the terminal; on
  the first `osascript` failure the app prints the exact System Settings path.
- `press_key(combo: str) -> Result`: maps `cmd+s` style strings to System Events
  `keystroke "s" using command down`.
- `open_file(path: Path) -> Result`: `open <path>`.
- `undo(last: Executed) -> Result`: reverses the last action: quits the app that was
  opened (`osascript -e 'quit app "X"'`), sends cmd+z for typed text, closes the window
  of an opened file (cmd+w in the frontmost app). Best effort; failures are reported.
- `frontmost_app() -> str`: System Events `name of first application process whose
  frontmost is true`.
- All shell calls go through one `run(argv) -> CompletedProcess` seam so tests inject a
  fake. Text passed to AppleScript is escaped for quotes and backslashes; that escaping
  is unit-tested since it is the one place a transcript touches a script.

### 4.8 `app.py`: loop and display

```
load config, check TYPESAFE_API_KEY
load whisper model (print timing)
build app catalog (print count)
loop:
    print "hold <key> to talk"
    samples = audio.record_while_held()
    transcript = stt.transcribe(samples)          -> panel: transcript, seconds
    decision = intent.classify(transcript, ...)   -> panel: probability table, nouls, latency, tokens
    verdict = policy.decide(decision)             -> panel: outcome + reason
    if EXECUTE: executor.run(decision)            -> panel: result; remember as last action
    learning.record(decision, verdict)            -> section 4.9
```

The display uses `rich`. `yapp --once "open notes"` skips audio and runs the rest of the
pipeline on a typed string; this is the primary development and demo mode.

### 4.9 `learning.py`: examples from acting, not asking

Jev has no memory; criteria are JSON built per request. Yapp populates the `examples`
of each option from three sources, merged by a builder before every call:

1. Authored examples for the fixed questions (`intent`, `key_combo`), versioned in
   `questions.yaml`, changed only through the eval loop.
2. Generated examples for catalog options: derived deterministically from app names,
   a small alias table (`chrome` → "browser"), and Spotlight metadata for files.
3. Learned examples from use, labeled implicitly:
   - an executed action with no `undo` within 10 s writes the transcript as a positive
     example under the chosen option;
   - an `undo` writes it as a negative example (goes into that option's `not_for`) and
     reverses the action.
   Stored in `~/.yapp/learned.jsonl`. The builder merges the five most recent positives
   per option, capped at eight examples total per option, so state stays small.

Whisper mishearings ("open node" for Notes) are exactly what accumulates here.

## 5. Error handling

- Missing API key, missing permissions, and model download failures stop the app at
  startup with one actionable line each.
- Jev network or API error: report in the display, skip the utterance, keep listening.
- Whisper returns empty text: display "heard nothing", keep listening.
- Executor failure (app not found, AppleScript denied): display the stderr, keep
  listening. Nothing retries an action automatically.
- Ctrl-C exits cleanly and releases the audio stream.

## 6. Testing

- `test_intent.py`: table of `(transcript, expected intent, expected app or None)` run
  against the real API with a fixed fake catalog of 20 apps and a pinned model version.
  Marked with a `jev` marker; skipped when `TYPESAFE_API_KEY` is unset so CI without a
  key still passes. Also asserts the free-text regexes on ten phrasings each.
- `test_policy.py`: every row of the threshold table, including boundary values and the
  destructive and compound overrides.
- `test_executor.py`: argv produced for each action via the fake `run`, and the
  AppleScript escaping function.
- `test_catalog.py`: parsing of fake `mdfind` output, dedupe, deterministic order, and
  `narrow` keeping exact matches.
- `tests/eval/transcripts.jsonl`: labeled transcripts (transcript, intent, app), grown
  from real use. `yapp eval` runs them and prints accuracy per confidence bucket
  (≥ 0.85, 0.60 to 0.85, < 0.60) per action. Thresholds in `config.py` change only
  with that table in the PR description.
- Audio and whisper are verified by hand; `yapp --once` covers everything else end to end.
- CI (GitHub Actions): ruff, mypy --strict, pytest on macOS runner (needed for the
  `open`/`osascript` argv tests only in shape, they use the fake shell).

## 7. Hybrid extension points (not built in v1)

- `intent.py` exposes `classify(transcript, catalog, context) -> Decision`. A future
  `splitter.py` (LLM) runs only when `is_compound` is high, returns a list of atomic
  utterances, and calls `classify` on each. No other module changes.
- `Decision.text` is the only free-text field. A future LLM "composer" can fill it for
  intents like `draft_text` without touching policy or executor.
- A future web dashboard subscribes to the same display events `app.py` already emits.

## 8. Teaching cadence

Built in this order. Each step is run and its raw output shown before the next begins:

1. One raw `curl` to Jev and one SDK call from a REPL; read the probability table.
2. `catalog.py`: see your own app list, watch `narrow` cut it down.
3. `intent.py` with tests: watch decisions change as question wording changes.
4. `policy.py`: tune thresholds against the test table.
5. `executor.py`: grant Accessibility, open Notes from `yapp --once`.
6. `stt.py`: transcribe a recorded clip, compare whisper sizes.
7. `audio.py` and the loop: hold the key, say "open notes".

## 9. Repo conventions

Mirrors `manali-co/what-should-we-watch`: `uv` project, Python 3.12, ruff
(E F I UP B, line length 100), mypy strict, pytest, release-please for versioning,
Conventional Commits. Feature branches into `dev`, `dev` into `main`. MIT license,
README explains the Jev model and the pipeline for other people who find the repo.

## 10. UI and avatar

Yapp has a face. It lives in one small, frameless, always-on-top window (a pill near the
top of the screen, roughly 360 by 120 px) that shows the avatar, the live transcript, and
the decision. The terminal keeps the developer view (full probability tables, latency,
tokens); `yapp --headless` runs without the window.

### 10.1 Design source of truth

All visuals come from a Claude Design project first and are ported to code second; UI is
never improvised in code (same rule as What Should We Watch). The brief for the design
project is in `docs/design/avatar-brief.md`. Claude Design outputs HTML/CSS/JS, so the
window renders web content: this makes the port 1:1 rather than a translation.

### 10.2 Avatar

- An abstract face on a fluid body: no literal eyes-nose-mouth, no limbs. A soft form that
  breathes, stretches, and settles, with a minimal expression read from shape and motion.
- States, each a distinct motion and silhouette, driven by pipeline events:

| State | Trigger | Motion idea |
|---|---|---|
| idle | waiting for the hotkey | slow breathing, occasional drift |
| listening | hotkey held | leans in, body ripples with mic amplitude |
| thinking | Jev request in flight | tightens, slow internal swirl |
| acting | executor running | quick decisive pulse toward the action |
| done | Result ok | settles, brief glow |
| unsure | policy Ignore/Refuse or empty transcript | softens, shrugs, fades back to idle |
| error | Jev/executor error | short shiver, dims |

- Motion is continuous between states (no cuts); implemented as CSS/JS or canvas with
  spring easing. The window is transparent outside the pill.

### 10.3 Window integration

- `pywebview` hosts the bundle in a native macOS window (frameless, always on top,
  transparent background, no dock icon). Python pushes state with
  `window.evaluate_js("yapp.setState({...})")`. The confirm prompt is therefore answered by keyboard in the window
  (Enter / Escape) or in the terminal, whichever comes first.
- `ui/` in the repo holds the ported bundle (`index.html`, `avatar.js`, `styles.css`),
  packaged as data files of the Python package.
- Mic amplitude for the listening state is sampled from the audio callback at ~20 Hz and
  forwarded as a 0 to 1 float.

### 10.4 Order of work

The pipeline (sections 3 to 8) is built and working in the terminal first. The window and
avatar are the last step of v1, once the design project has produced the avatar. Until
then `app.py` runs headless by default.

## 11. Governance and contribution policy

Open source under `manali-co/yapp`, MIT. Ayush (`@ayushm-agrawal`) is the sole admin
and maintainer for now.

### 11.1 Files at the repo root

- `LICENSE` (MIT), `CONTRIBUTING.md` (setup, branch flow, Conventional Commits, PR
  checklist, how to run tests without an API key), `CODE_OF_CONDUCT.md` (Contributor
  Covenant 2.1), `SECURITY.md` (report privately via GitHub security advisories; never
  commit keys), `.github/CODEOWNERS` (`* @ayushm-agrawal`), `.github/PULL_REQUEST_TEMPLATE.md`,
  `.github/ISSUE_TEMPLATE/` (bug, feature), `.github/dependabot.yml` (uv/pip and actions).

### 11.2 Branch rules (GitHub rulesets)

Applied to both `dev` and `main` via `gh api`:

- Pull request required before merging; direct pushes blocked for everyone, admins
  included (no bypass actors). Discipline over convenience; a bypass can be added later.
- Required status check: the `ci` workflow (ruff, mypy, pytest) must pass.
- Block force pushes and branch deletion.
- Require all review conversations resolved.
- Required approvals: 0 while there is one maintainer (a required approval would block
  the sole maintainer from merging their own PRs). Raise to 1 and enable "dismiss stale
  reviews" when a second maintainer joins. CODEOWNERS is in place so that switch is one
  setting.
- `main` additionally requires linear history (squash merges from `dev`).

Releases flow `feature/* → dev → main`; release-please opens the version PR on `main`.
