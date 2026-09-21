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
