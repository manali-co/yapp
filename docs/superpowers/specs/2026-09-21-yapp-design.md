# Yapp: voice-narrated computer use, design spec

Date: 2026-09-21
Status: draft for review
Repo: `manali-co/yapp` (open source, MIT)

## 1. What Yapp is

Yapp is a macOS app. You hold a key and talk; the Mac acts while you are still talking.
Speech is transcribed locally with Whisper as a growing stream of committed words. Each
time the stream grows, the words not yet acted on go to TypeSafe AI's Jev model, which
returns a typed decision and whether the instruction is complete enough to carry out.
Code executes natively (launch apps, type text as you dictate it, open files) and shows
every intermediate result in the terminal and a small window so the pipeline is legible.

Yapp is also a learning project. Each module is small, has one job, and is explained and
run in isolation before it is wired to the next one.

### Goals

- Hold-to-talk narration that acts mid-sentence: opens apps, dictates text into the
  focused app word by word, opens files found by Spotlight, presses a small set of keys.
  "Open notes and switch to Safari" is two actions with no pause between them.
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
- Planning. Yapp executes instructions in the order you say them; it never reorders or
  infers steps you did not say.
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

Single Python process. Audio arrives on a callback thread into a ring buffer; everything
else runs on one loop that ticks every ~400 ms while the key is held.

```
hold key ──► audio.py ──► stt.py ──────────► stream.py ──► intent.py ──► policy.py ──► executor.py
             (ring buf)   (committed words)  (cursor,      (Decision)    (Verdict)     (Result)
                                              tail text)       │
                                                          catalog.py (installed apps, Spotlight)
                                                               │
                                                            jev.py (HTTP client wrapper)
```

`stream.py` owns the transcript cursor: the committed transcript minus everything already
acted on is the "tail", and the tail is what Jev sees. When policy says execute, the
cursor advances past the consumed words and the loop continues on the remainder.
`app.py` owns the tick loop and the display; each stage emits an event so the user sees
the growing transcript, Jev's probability table, the verdict, and the action.

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
    stt.py                  streaming whisper: committed-word transcript
    stream.py               transcript cursor, dictation mode, de-duplication
    learning.py             learned examples from act/undo (section 4.9)
    questions.yaml          authored questions and examples for intent/key_combo
    catalog.py              installed apps + Spotlight search
    jev.py                  thin wrapper over typesafe-sdk with typed results
    intent.py               builds state + questions, calls jev, returns Decision
    policy.py               confidence gates -> Verdict
    executor.py             macOS actions
    types.py                dataclasses shared across modules
  tests/
    test_intent.py          transcript -> Decision, hits the real API (cheap)
    test_stream.py          scripted word sequences -> actions fired, cursor positions
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
    key: str  # stable slug, e.g. "notes"
    name: str  # display name passed to `open -a`, e.g. "Notes"
    description: str  # one line shown to Jev


@dataclass(frozen=True)
class Decision:
    transcript: str
    intent: Intent
    intent_confidence: float
    intent_probabilities: dict[str, float]
    app: App | None  # for OPEN_APP
    app_confidence: float | None
    text: str | None  # for TYPE_TEXT, extracted in code
    key_combo: str | None  # for PRESS_KEY, e.g. "cmd+s"
    file_query: str | None  # for OPEN_FILE, extracted in code
    is_complete: float  # noul: instruction can be carried out now
    ends_dictation: float  # noul: tail is a new instruction, not dictated text
    is_destructive: float  # noul
    consumed_words: int  # how many tail words this decision covers
    raw: dict[str, Any]  # full Jev response, for the display


class Outcome(StrEnum):
    EXECUTE = "execute"
    WAIT = "wait"  # instruction not complete yet: keep the tail, next tick
    IGNORE = "ignore"  # below threshold or intent none: quiet
    REFUSE = "refuse"  # destructive or compound: quiet, with a reason shown


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str  # human-readable, shown in the terminal


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str
```

## 4. Module contracts

### 4.1 `audio.py`: hold-to-talk recorder

- Depends on `sounddevice` (PortAudio) and `pynput` for the global hotkey.
- `Recorder` opens a 16 kHz mono float32 input stream once. While the hotkey is held the
  callback appends to a ring buffer holding the last 30 s; `snapshot() -> np.ndarray`
  returns the audio since the key went down (capped at 30 s). `level() -> float` returns
  the RMS of the last 100 ms, 0 to 1, for the avatar. Release clears the buffer.
- Default hotkey: right Option. Configurable.
- macOS requires Input Monitoring permission for the terminal to observe the global key,
  and Microphone permission. The app checks for a captured buffer of all zeros and prints
  a pointer to the System Settings pane if so.

### 4.2 `stt.py`: local transcription

- Whisper is not a streaming model, so streaming is built on top of it with the
  LocalAgreement technique: every tick, decode the audio since key-down (`mlx-whisper`,
  numpy array in, no ffmpeg), then commit the longest word prefix that is identical
  between this pass and the previous pass. Committed words never change; the uncommitted
  suffix is shown in the window in a dimmer colour and may still change.
- `StreamingTranscriber.update(samples) -> Transcript` where
  `Transcript(committed: list[str], pending: list[str])`. `reset()` on key release.
- To bound decode time, once the committed prefix exceeds ~8 s of audio the audio before
  it is dropped from the decode window and the committed words are kept as text.
- Default model `mlx-community/whisper-base-mlx` (decode of 5 s of audio in ~100 ms on
  M-series; `small` is the accuracy step up, configurable). Loaded once at startup.
- Measured target: a word is committed within ~0.5 s of being spoken.

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

`classify(tail: str, ctx: Context) -> Decision` is called once per tick in which the
committed transcript grew. State sent to Jev, as a JSON object:

```json
{
  "instruction_so_far": "and switch to safari",
  "already_done": ["open notes"],
  "frontmost_app": "Notes",
  "dictating": false
}
```

`instruction_so_far` is the tail (committed words after the cursor). `already_done` is the
last three executed instructions, `frontmost_app` comes from `executor.frontmost_app()`,
and `dictating` tells Jev whether Yapp is currently typing what it hears.

Questions, all in one request (speculative fan-out):

| Name | Type | Instructions | Options |
|---|---|---|---|
| `intent` | choice | "What does the user want the computer to do?" | `open_app`: "Launch or switch to an application"; `type_text`: "Type words into the app that is currently focused"; `open_file`: "Open a document, note, or file by name"; `press_key`: "Press a keyboard shortcut such as save, copy, or paste"; `undo`: "Reverse or cancel what Yapp just did ('undo', 'no', 'not that')"; `none`: "Not an instruction to the computer, or unclear" |
| `app` | choice | "Which application does the user mean?" | the narrowed catalog from `catalog.narrow`, plus `unsure`: "None of these" |
| `key_combo` | choice | "Which keyboard shortcut does the user mean?" | `cmd+s`: "Save"; `cmd+c`: "Copy"; `cmd+v`: "Paste"; `cmd+a`: "Select all"; `enter`: "Press enter or return"; `escape`: "Escape or cancel"; `unsure` |
| `is_complete` | noul | "instruction_so_far is a complete instruction that can be carried out now, not a fragment that is still being spoken" | |
| `ends_dictation` | noul | "instruction_so_far is a new instruction to the computer rather than text the user wants typed" (only meaningful when `dictating`) | |
| `is_destructive` | noul | "Carrying this out could delete data, send a message, or spend money" | |

Rules:

- Every choice has an explicit "none/unsure" option so Jev is never forced to pick.
- No compound-command question is needed: streaming acts on the first complete
  instruction and the cursor moves on.
- `app` and `key_combo` are asked on every tick even when intent turns out to be
  something else. Answers for the unselected intent are ignored. This costs nothing and
  saves a round trip.
- `is_complete` is what lets Yapp act mid-sentence: "open" alone is incomplete, "open
  notes" is complete, "open notes and" is complete for the first instruction. Its
  criteria carry examples of fragments versus complete instructions.
- `consumed_words` is computed in code: the tail up to and including the last word that
  matched the intent's verb-object pattern; the remainder stays for the next tick.
- Free-text extraction happens in code after Jev answers:
  - `type_text`: strip a leading verb phrase matching `^(type|write|enter|say)\b[:,]?\s*`
    from the tail; the remainder (possibly empty at this tick) is `text` and is typed
    immediately; dictation mode (section 4.10) then types every later committed word.
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
| any | `is_complete` < 0.70 → wait (keep the tail, act on a later tick) | |
| `open_app` | intent conf ≥ 0.60 and app ≠ unsure | ignore |
| `type_text` | intent conf ≥ 0.70 → enter dictation mode (section 4.10) | ignore |
| `open_file` | intent conf ≥ 0.60 and Spotlight returned ≥ 1 hit; opens Jev's top pick | ignore |
| `press_key` | intent conf ≥ 0.70 and combo ≠ unsure | ignore |
| `undo` | intent conf ≥ 0.60 and there is a last action | ignore |
| in dictation | `ends_dictation` ≥ 0.70 → leave dictation, then evaluate the tail as above | keep typing |
| any | `is_destructive` ≥ 0.50 → refuse, window shows "won't do that: could delete/send/spend" | |
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
    wait for hotkey down; stream.reset(); stt.reset()
    while hotkey held, every ~400 ms:
        transcript = stt.update(audio.snapshot())     -> window: committed + pending words
        if transcript.committed grew:
            if stream.dictating:
                executor.type_text(stream.new_words()) -> typed as they commit
            decision = intent.classify(stream.tail(), ctx)   -> panel: probabilities, nouls, latency
            verdict = policy.decide(decision, stream.state)
            if EXECUTE: executor.run(decision); stream.consume(decision.consumed_words)
            if WAIT: nothing; tail carries to the next tick
            learning.record(decision, verdict)
    on release: final tick on the full transcript, then stream.reset()
```

The display uses `rich`. `yapp --once "open notes and switch to safari"` feeds the words
through `stream.py` at a scripted pace with no audio; this is the primary development and
demo mode and exercises the cursor exactly as live speech does.

### 4.10 `stream.py`: cursor and dictation

- Holds `committed: list[str]`, `cursor: int`, `dictating: bool`, and the last executed
  action. `tail()` is `" ".join(committed[cursor:])`. `consume(n)` advances the cursor.
- A decision is executed at most once per tail: the pair (cursor, consumed_words) is
  remembered so a tick that sees the same tail with no new words never re-fires.
- Dictation mode: entered when policy executes `type_text`. The cursor moves past the
  verb phrase ("type", "write", "say"), and every subsequently committed word is typed
  immediately with a leading space. Each tick still asks Jev about the tail with
  `dictating: true`; when `ends_dictation` clears its threshold, dictation stops, the
  words already typed stay, and the tail is evaluated as a fresh instruction. Saying
  "stop typing" or releasing the key also ends dictation.
- Typed words trail speech by the commit lag (~0.5 s), the same feel as native dictation.

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
     reverses the action. Undo after dictation removes the words typed in that dictation
     span (one cmd+z per committed chunk is unreliable; Yapp sends backspaces equal to the
     span length).
   Stored in `~/.yapp/learned.jsonl`. The builder merges the five most recent positives
   per option, capped at eight examples total per option, so state stays small.

Whisper mishearings ("open node" for Notes) are exactly what accumulates here.

## 5. Error handling

- Missing API key, missing permissions, and model download failures stop the app at
  startup with one actionable line each.
- Jev network or API error: report in the display, skip the utterance, keep listening.
- Whisper returns empty text: display "heard nothing", keep listening.
- A Jev call is still in flight when the next tick fires: the tick is skipped, not queued,
  so decisions never arrive out of order.
- Whisper revises a word after Yapp acted on it: the action stands (it was committed by
  agreement across two passes); the user says "undo".
- Executor failure (app not found, AppleScript denied): display the stderr, keep
  listening. Nothing retries an action automatically.
- Ctrl-C exits cleanly and releases the audio stream.

## 6. Testing

- `test_intent.py`: table of `(tail, expected intent, expected app or None, expected
  is_complete high/low)` run against the real API with a fixed fake catalog of 20 apps
  and a pinned model version. Fragments like "open", "switch to" must be low on
  `is_complete`; "open notes" must be high.
  Marked with a `jev` marker; skipped when `TYPESAFE_API_KEY` is unset so CI without a
  key still passes. Also asserts the free-text regexes on ten phrasings each.
- `test_policy.py`: every row of the threshold table, including boundary values, the
  destructive override, `is_complete` waiting, and dictation entry/exit.
- `test_stream.py`: scripted committed-word sequences with a fake `classify` that returns
  canned decisions; asserts which actions fire, in what order, cursor positions, that no
  action fires twice for the same tail, and that dictation types exactly the words after
  the verb and stops on `ends_dictation`.
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

- `intent.py` exposes `classify(tail, context) -> Decision`. Streaming already segments
  spoken sequences, so no LLM splitter is needed. A future LLM `planner.py` could take a
  tail that Jev classifies as `none` with high `is_complete` (a goal rather than an
  instruction, e.g. "email the report to Sam") and turn it into a list of instructions
  fed back through `stream.py`. No other module changes.
- `Decision.text` is the only free-text field. A future LLM "composer" can fill it for
  intents like `draft_text` without touching policy or executor.
- A future web dashboard subscribes to the same display events `app.py` already emits.

## 8. Teaching cadence

Built in this order. Each step is run and its raw output shown before the next begins:

1. One raw `curl` to Jev and one SDK call from a REPL; read the probability table.
2. `catalog.py`: see your own app list, watch `narrow` cut it down.
3. `intent.py` with tests: watch decisions change as question wording changes; watch
   `is_complete` flip between "open" and "open notes".
4. `policy.py` and `stream.py` with `yapp --once`: feed "open notes and switch to safari"
   word by word and watch two actions fire from one sentence, with no audio yet.
5. `executor.py`: grant Accessibility, open Notes from `yapp --once`; dictate a sentence.
6. `stt.py`: stream a recorded clip, watch words commit, measure commit lag per model size.
7. `audio.py` and the loop: hold the key, say "open notes and type hello there".
8. `learning.py` and `yapp eval`: undo something, see the example land, run the table.

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
| listening | hotkey held | leans in, body ripples with mic amplitude; a small tick each time a word commits |
| thinking | Jev request in flight | tightens, slow internal swirl |
| acting | executor running | quick decisive pulse toward the action; can interrupt listening and return to it |
| dictating | typing what it hears | steady, attentive, pulses per typed word |
| done | Result ok | settles, brief glow |
| unsure | policy Ignore/Refuse or empty transcript | softens, shrugs, fades back to idle |
| error | Jev/executor error | short shiver, dims |

- Motion is continuous between states (no cuts); implemented as CSS/JS or canvas with
  spring easing. The window is transparent outside the pill.

### 10.3 Window integration

- `pywebview` hosts the bundle in a native macOS window (frameless, always on top,
  transparent background, no dock icon). Python pushes state with
  `window.evaluate_js("yapp.setState({...})")`. 
- `ui/` in the repo holds the ported bundle (`index.html`, `avatar.js`, `styles.css`),
  packaged as data files of the Python package.
- Mic amplitude for the listening state is sampled from the audio callback at ~20 Hz and
  forwarded as a 0 to 1 float. Committed and pending words are pushed on every tick so the
  transcript line shows pending words dimmer than committed ones.

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
