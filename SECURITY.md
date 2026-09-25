# Security

## Reporting
Report vulnerabilities privately through GitHub's private vulnerability reporting on this repo
(Security → Report a vulnerability). Do not open a public issue. We aim to acknowledge within
72 hours.

## What Yapp does on your Mac
Yapp listens to the microphone while the bar is up, reads the screen through Accessibility,
and acts: it launches apps, presses controls and menu items, and types. That is the whole
point, and it is why the following holds:

- **Nothing runs without a score.** Every action is scored for harm by Jev before it happens
  (`guard.py`). At or above the mode's threshold the bar asks and waits for a spoken yes from
  the enrolled voice. A failed Jev call counts as harmful. Undo is never gated.
- **One seam for the shell.** Every shell or AppleScript call goes through `Executor._run`
  with argv lists; user text is escaped before it reaches AppleScript. Review `executor.py`
  before running a fork you did not build.
- **Keys stay in the environment.** `TYPESAFE_API_KEY` is read from the environment only.
  Secret scanning with push protection is on for this repo.
- **Local audio and voiceprint.** Audio never leaves the machine; Whisper and the speaker
  model run locally. The voiceprint lives in `~/.yapp/voice.npy`; delete it to un-enrol.
  Only transcript text, screen labels, and action descriptions are sent to TypeSafe's API.
- **Logs.** `~/.yapp/app.log` contains transcripts and the labels of on-screen controls.
  Treat it as private.

## Repository controls
Branch rulesets on `dev` and `main` (PR required, CI required, no force pushes, no
bypass), CodeQL default setup, Dependabot alerts and security updates, secret scanning with
push protection, private vulnerability reporting, CodeRabbit on every PR, `pip-audit` and
`bandit` in CI, dependency review on PRs.

## Distribution (when we ship a bundle)
`yapp install-app` today signs ad hoc, which is fine on the machine that built it and nothing
else. A distributed build must: sign with a Developer ID Application certificate, enable the
hardened runtime with only the entitlements Yapp needs (microphone; no JIT, no unsigned
memory), notarize and staple, ship a lockfile-pinned environment or a frozen build rather than
the developer's working tree, and publish a SBOM and checksums with each release. The launcher
must keep Yapp as the responsible process for TCC (see `launcher.c`) so permissions attach to
Yapp, not to Python.
