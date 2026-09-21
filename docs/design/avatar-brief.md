# Yapp: avatar and window, design brief for Claude Design

Yapp is a macOS voice assistant by Manali. You hold a key, say "open notes", release, and
the Mac does it. Speech is transcribed locally; a fast decision model (TypeSafe Jev)
classifies the intent with a confidence score; code executes. Yapp needs a face and one
small window.

## Brand

Manali's existing system (What Should We Watch): near-black chrome, ink text, colour only
on user actions. Fonts Bricolage Grotesque (display) and Figtree (text). Yapp is a
sibling: same restraint, more playful, because the name is "yap".

## The avatar

- Abstract, not literal. No eyes-nose-mouth arrangement, no limbs. A single fluid body
  whose shape and motion carry the expression. Think a drop of something viscous that is
  clearly alive: it breathes, leans, tightens, settles.
- Expression comes from silhouette, tension, and timing, plus at most one minimal facial
  cue (a crease, a highlight, an opening) that appears only when it helps read the state.
- Motion is continuous. States blend into each other with spring easing; there are no
  cuts. Idle is never static.
- Palette: one body hue that shifts subtly per state (calm neutral at idle, warmer while
  listening, cooler while thinking), on a transparent background. Should read on light
  and dark desktops.
- Deliver as HTML/CSS/JS (or canvas), no external dependencies, so it can be embedded in
  a native window as-is. Expose `setState(name, {level})` where `level` is 0 to 1 mic
  amplitude for listening.

### States (each needs a distinct silhouette and motion)

| State | When | Feel |
|---|---|---|
| idle | waiting | slow breath, occasional drift, half attention |
| listening | key held, user talking | leans toward the user, body ripples with voice level |
| thinking | decision request in flight, 100 to 500 ms | tightens, slow internal swirl |
| confirm | app is unsure and asks "did you mean X?" | tilts, holds, expectant |
| acting | executing | quick decisive pulse in the direction of the action |
| done | success | settles, brief glow, back to idle |
| unsure | did not understand | softens, small shrug, fades to idle |
| error | something failed | short shiver, dims, recovers |

## The window

- One frameless pill near the top of the screen, about 360 by 120 px, transparent
  outside the pill, always on top. Never a dock icon.
- Layout: avatar on the left (about 72 px), two text lines on the right: the live
  transcript (what was heard) and the decision line (e.g. "Opening Notes", "Did you mean
  Notes? Enter / Esc", "Not sure what you meant").
- A confidence indicator that is honest but not a number: a thin bar or ring on the
  avatar that fills with the model's confidence.
- Show the hotkey hint on idle ("hold ⌥ to talk") and drop it once the user has used it a
  few times.
- Confirm state shows Enter / Esc affordances.
- Also design the terminal companion palette (rich): colours for transcript, probability
  table, verdict, so the two views feel related.

## Deliverables

1. `avatar.html`: the avatar with a state switcher for all eight states and a slider for
   mic level.
2. `window.html`: the pill window with sample content for each state.
3. `tokens.css`: colours, type, spacing, motion durations and easings.
4. An app icon derived from the avatar's idle silhouette (for the README and a future
   menu-bar item).
