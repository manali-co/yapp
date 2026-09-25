# What Yapp is, for anyone reviewing a change

Yapp is a macOS voice assistant that acts while the user is still talking. Local Whisper hears,
TypeSafe's **Jev** decides, code executes. Jev is a decision model, not a text generator: it
picks among options the code builds from the live screen (Accessibility tree), the installed
apps, and the words heard. Anything Jev "knows" arrives as criteria and examples in
`questions.yaml`, `ax.py`, `placement.py`; anything it decides is executed by `executor.py`,
`ax.py`, `workspace.py`.

## Rules a change must not break

1. **Generic, never hardcoded.** Yapp works on whatever apps a user has. Product code
   (`src/yapp`, excluding the `tasks/` harness) must not name applications, menu items, or
   window titles to special-case them. App names may appear only as *examples* inside Jev
   criteria, and as a general pattern ("press Send", "open Terminal"), never as a branch in
   code. Platform facts (Finder exists, Return is key code 36, TextEdit inlines its save sheet
   buttons) are allowed when the code handles the general case too.
2. **Nothing harmful without the guard.** Every action that could delete, send, spend, sign
   out, change settings, or overwrite goes through `guard.py`, which scores the concrete action
   with Jev and asks by voice at or above the mode's threshold. A failed Jev call counts as
   harmful. Undo is the one ungated action.
3. **The user's focus is theirs.** In parallel mode Yapp opens with `open -g`, acts through
   Accessibility, types by setting values, and never raises a window while the user typed or
   clicked in the last 1.5 s. Borrowing focus or the pointer is announced (attention state),
   brief, and gives back exactly what the user had.
4. **The glow marks Yapp's windows only.** Never a window that was already the user's, never
   over the user's front window, gone the instant its window closes.
5. **Clean-up closes what Yapp opened, on request.** Hand-off windows (the user wanted to see
   them) are released at session end; tool windows keep their glow until "clean up". Nothing
   of the user's is closed or deleted by the product.
6. **The harness is not the product.** `tasks/` and `tasks.py` may quit apps, close tabs, and
   delete the notes and reminders a task itself created (snapshot-diff plus ownership by the
   task's dictated words). That code must never be reachable from the app.
7. **Every push is tested end to end** through the bundle (`yapp tasks`) on an unlocked, idle
   Mac before it lands; unit tests alone are not enough for anything that touches the screen.
8. **UI and avatar changes go through the Claude Design project first**, then are ported
   byte-exact; colours follow the user's macOS appearance.

## Where the design lives
`docs/superpowers/specs/` holds the approved designs; `CONTRIBUTING.md` and `SECURITY.md`
hold the process and threat model.
