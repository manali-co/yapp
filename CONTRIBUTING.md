# Contributing to Yapp

Thanks for helping. Yapp is small on purpose; keep it that way.

## Setup
    uv sync --all-groups
    export TYPESAFE_API_KEY=...   # only needed for tests marked `jev` and for running the app

## Branch flow
`feature/<name>` → PR into `dev` → `dev` → `main` (release-please). Direct pushes to `dev`
and `main` are blocked for everyone, including admins.

## Before opening a PR
    uv run ruff check . && uv run ruff format . && uv run mypy src && uv run pytest
Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
If a PR changes a threshold in `config.py`, paste the `yapp eval` table in the description.

## Design rule
UI and avatar changes go through the Claude Design project first, then get ported. Do not
improvise visuals in code.
