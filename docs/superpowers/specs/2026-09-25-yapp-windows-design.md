# Yapp: window placement, parallel mode, attention state, ledger and clean-up

Date: 2026-09-25. Design approved in chat; user chose "borrow focus, but make me aware".

## Placement decision
One Jev choice per instruction (`placement.py`): **hand_over** or **parallel**. State: the
instruction, the app in front when the user spoke, seconds since the user's last key or click
(Quartz HID idle time), whether that app is the instruction's target, the display count.
Parallel needs ≥ 0.60; unsure means hand over (today's behaviour). Decided once per session at
the first executed action and reused until the session ends.

## Layout (`windows.py`)
All geometry in top-left screen coordinates (what Accessibility uses). Displays from NSScreen
(visible frames, so the menu bar and Dock are excluded). Parallel with ≥ 2 displays: the work
area is the largest display that does not contain the user's focused window. Parallel with one
display: the user's window goes to the left half, the work area is the right half; the user's
original frame is remembered. Every window Yapp opens in parallel mode is placed in the work
area (full screen exited first). Hand-over mode places nothing.

## Acting without the user's focus
Parallel mode never activates the target app: `open -g -a`, presses through AXPress, typing by
setting the field's AXValue. When a field refuses (error, or the value did not change), Yapp
**borrows focus**: attention state on, raise the target app, keystrokes, raise the user's app
again, attention state off. Target ≤ 300 ms; measured 720–780 ms on the first build (the raise
polls at 150 ms and the keystrokes themselves take most of it). Dictation in parallel mode appends through AXValue
per flush; if the field refuses, the words are held and typed with one borrow at the end.

## Attention state
`BarDisplay.attention(text)` / `attention_done()`: the pill stays up, avatar in the "acting"
spring with the attention copy ("Borrowing your keyboard for a moment", then "Back to you").
Used for borrowing focus and for approval asks in parallel mode. A dedicated avatar state is
briefed to Claude Design (docs/design/attention-brief.md) and will replace the interim
mapping when it lands.

## Ledger and clean-up (`ledger.py`)
During a session Yapp records: apps it launched that were not running, windows it created
(new AX windows of the work app after an action), and the user's original window frame when
split. New intent **cleanup** ("clean up", "close everything", "we're done", "close what you
opened", "put it back") unwinds in reverse: close recorded windows through their AX close
button, quit launched apps, restore the user's frame. The guard scores one action
"close the windows and apps Yapp opened". Content typed into existing documents is not
deleted; that is undo's job.

## Tests and tasks
Unit tests for the layout math, placement decoding, ledger, executor parallel path, screen loop
with an explicit target app and AX-typing fallback. Two tasks: `13-parallel-split` (placement
forced to parallel, Notes in front as the user's app: TextEdit lands on the right half, Notes
stays in front on the left) and `14-cleanup` (open TextEdit, then clean up: TextEdit is gone).


## Addendum (2026-09-26): the working glow and the pointer tiers
`highlight.py` draws the acting-hue frame around the window Yapp works in (both modes),
pulses it in the attention state, fades it on done, hides it on clean-up; colour and timings
come from the design bundle. `pointer.py` gives Yapp three tiers: Accessibility (no pointer),
a click posted to the target process with its own coordinates (the user's cursor never moves;
Yapp's drawn cursor marks the spot), and, only when that changed nothing, the real cursor
borrowed for a moment under the attention state and never while a button is held.
