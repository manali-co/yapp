# Yapp: permission modes, voice approval, noise layers, task suite

Date: 2026-09-24. Approved in chat (approach A + four noise layers), user asked for
delivery without further check-ins.

## Goal

Yapp acts on its own, but pauses and asks, by voice, before anything harmful. Two modes:

| mode | asks when Jev's harm score is | who it is for |
|------|-------------------------------|---------------|
| ask (default) | ≥ 0.30 | everyone |
| auto | ≥ 0.85 | users who opted in from the menu bar |

Harm is judged by Jev on the **concrete action the model decided**, not only on the sentence:
"press Empty Trash in Finder", "open Terminal", "dictate into Mail". It is checked at every
point where Yapp is about to touch the machine.

## Components

- `guard.py` — `Mode`, `Guard.check(action, context) -> GuardVerdict(harm, threshold, asked,
  approved)`. One Jev noul (`is_harmful`, criteria in questions.yaml). Below threshold: act.
  Otherwise call `ask(action)`; act only on approval. The old hard refusal is gone.
- Check points: `Runner._execute` (open app, open file, press key, start of dictation),
  `ax.Screen.run` (every goal-loop step, with the screen summary as context). Undo is never
  gated: it is the safety valve.
- `approval.py` — Jev classifies a spoken reply as approve / deny / unrelated.
- `speaker.py` — WeSpeaker ResNet34 (ONNX, 26 MB, Hugging Face) embeddings over numpy
  Kaldi-style fbank; voiceprint at ~/.yapp/voice.npy; `Verifier.matches(samples)`. Enrolled from
  the menu bar ("Enroll my voice…", 10 s) or `yapp enroll`. Approvals need a voice match when a
  voiceprint exists; without one they are Jev-only and the log says so.
- `Session.ask(description)` — shows "Say yes to: <action>" in the bar, restarts the
  transcript, listens up to 8 s. Approve = Jev approve ≥ 0.6 and speaker match; deny = Jev
  deny ≥ 0.6 or Escape; ⏎ approves silently; timeout denies. The reply words never reach the
  command stream (transcript and stream reset afterwards).
- Noise layers: (1) whole-buffer silence skips decoding, Whisper segments with high
  no-speech probability or compression ratio are dropped, repeated n-grams are cut;
  (2) `is_addressed` noul in the intent batch, policy ignores tails Jev is confident are talk
  between people (threshold 0.35, not applied while dictating); (3) speaker match for
  approvals; (4) approval reply must be short and standalone, window 8 s.
- Mode persistence: `~/.yapp/state.json` (`mode`), menu-bar checkbox "Auto mode".
- Task suite: `tasks/*.yaml` (name, instruction, setup, check, expect_ask, budget) run by
  `yapp tasks [--only substr] [--mode ask|auto] [--approve]` on the real Mac through the
  Yapp bundle. Checkers: frontmost, window_title_contains, ax_value_contains, file_exists,
  file_contains, shell_contains, trash_count_unchanged. Output: table + ~/.yapp/tasks.jsonl
  with pass, ask expected/got, steps, Jev calls, seconds.

## Out of scope (later)

Requiring the enrolled voice for every command; harm scoring of each dictated chunk; LLM
planner ("Jarvis" layer) on top of these primitives.
