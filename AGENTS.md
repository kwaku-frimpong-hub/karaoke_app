# AGENTS.md — Friday Karaoke

Project-specific instructions for coding agents working in this repository.

## Read first

Before modifying anything, read:

- `docs/PROJECT_BRAIN.md` — authoritative project context (purpose, architecture, rules)
- `docs/ARCHITECTURE.md`
- `docs/DEV_BRAIN.md` — current milestone/task
- `plan.md` — milestone definitions and acceptance criteria

## Branch rules

- Development happens on `dev` only. Never commit directly to `master`.
- `master` only receives reviewed merges, gated by the `merge-to-master`
  command (`/merge-to-master`), which runs the `reviewer` agent before merging.
- The `committer` agent stages and commits; it is denied merge/push/rebase.

## Agents

- `coder` (primary) — implements one milestone at a time on `dev`.
- `reviewer` (subagent) — reviews diffs, runs tests, checks acceptance
  criteria; cannot edit code.
- `committer` (subagent) — stages intended files and commits on `dev` with
  meaningful messages.

## Engineering rules (summary)

- Backend is the single source of truth for queue, round, playback, and
  identity state. Frontend never owns state.
- Host is the final authority; the system only automates normal operation.
- Python: Pydantic v2 models at all API boundaries, Pydantic Settings for
  config, `Enum` for domain states, SQLAlchemy models separate from Pydantic
  schemas, explicit type hints, static type checks must pass.
- Do not over-validate YouTube content: validate URL format, warn on long
  videos, never auto-reject for length.
- No scope creep. Implement only the assigned milestone.

## Definition of done per milestone

Implementation + tests + documentation updated (`PROJECT_BRAIN.md`,
`DEV_BRAIN.md`, `DECISIONS.md` if needed) + run instructions + acceptance
criteria verified + lint/type checks pass.
