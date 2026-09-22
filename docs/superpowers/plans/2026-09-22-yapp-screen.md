# Yapp Screen Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "new tab", "zoom in", "find on page", "search for fable five" work in any app by reading its UI live through Accessibility and letting Jev pick the target.

**Architecture:** `ax.py` grows from spike to module: `Perceiver` (menu cache per app, controls per step, label normalisation, path-aware narrowing), `Screen` (one Jev call: target, operation, text span, submit; enforcement of operation vs role; AX press / focus-and-type). A new `screen_action` intent in `questions.yaml`; `Runner._execute` delegates it to `Executor.screen(tail)`; undo sends ⌘Z.

**Spec:** section 12 of `docs/superpowers/specs/2026-09-21-yapp-design.md`.

## Global Constraints
Same gates as before; AX calls behind small functions so tests use fakes; nothing per app.

### Task 1: Perceiver with normalisation, cache, structured criteria
Files: `src/yapp/ax.py`, `tests/test_ax.py`. Produces `normalize_label`, `Target.criteria()` (what + examples generated from the title/path), `Perceiver(read_menus, read_controls, clock)` with `targets(app_id, words, limit)`, menu cache keyed by app id with a 300 s TTL, `narrow` scoring `token_set_ratio` on label and `partial_ratio` on path.

### Task 2: Decision and execution
Files: `src/yapp/ax.py`, `tests/test_ax.py`. Produces `spans(words) -> list[str]`, `decide(words, targets, jev) -> ScreenDecision(target, operation, text, submit, confidence, probabilities)`, `fits(operation, target) -> bool`, `Screen(jev, perceiver, press, focus_type).run(words) -> Result`.

### Task 3: Wire the intent
Files: `questions.yaml`, `types.py` (`Intent.SCREEN`), `intent.py` (consumed/extract), `runner.py` (`Intent.SCREEN` → `executor.screen(tail)`), `executor.py` (`screen()` via a `Screen` collaborator; `undo` for screen = ⌘Z), `policy.py` (threshold `screen: 0.60`), `bardisplay.py` (copy "I don't see that here"), tests. Live intent test rows for the four phrases.

### Task 4: Live
`yapp ax` reuses the module; `yapp --once "new tab"` with Chrome frontmost presses New Tab; then the bar: ⌥ Space, "open chrome and then zoom in".
