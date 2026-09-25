# Contributing to Yapp

Thanks for helping. Yapp is small on purpose; keep it that way.

## Setup
    uv sync --all-groups
    export TYPESAFE_API_KEY=...   # only needed for tests marked `jev` and for running the app

## Branch flow
One branch per feature, always: `git switch dev && git pull && git switch -c feature/<name>`.
Push early and often so the work is visible and recoverable. When the feature is done, open a
PR into `dev`; `dev` → `main` is a release PR. Direct pushes to `dev` and `main` are blocked
for everyone. A requested change gets addressed in the PR, not dismissed; repo admins can
bypass the rules to merge in a pinch, and every bypass is in the audit log. Keep PRs focused: one feature, its tests, and its docs. A PR
that grows past a feature should be split.

## Review
CI (`ci`, `security`, `dependency-review`) must be green and every CodeRabbit thread resolved
before merging. Treat review findings as questions to answer, not commands to obey: fix real
issues, explain why when something is intentional. Dependabot PRs are merged once CI passes.

## Security
Read `SECURITY.md`. Never commit keys (push protection is on), never add a shell call outside
the `run` seam in `executor.py`, never weaken the guard in `guard.py` without a test and a
sentence in the PR explaining why.

## Before opening a PR
    uv run ruff check . && uv run ruff format . && uv run mypy src && uv run pytest
Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
If a PR changes a threshold in `config.py`, paste the `yapp eval` table in the description.

## Design rule
UI and avatar changes go through the Claude Design project first, then get ported. Do not
improvise visuals in code.
