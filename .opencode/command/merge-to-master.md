---
description: Review and merge the dev branch into master via a local PR-style review gate.
agent: coder
---

You are running the local PR merge workflow for the Friday Karaoke project.

Workflow:

1. Confirm the current branch is `dev` (`git branch --show-current`). If not,
   abort.
2. Check that the working tree is clean (`git status`) and that `dev` is ahead
   of `master` (`git log master..dev --oneline`).
3. Invoke the `reviewer` subagent to review the full diff
   (`git diff master...dev`), run the test suite, and verify the relevant
   milestone acceptance criteria from `plan.md`. It must return a status of
   APPROVED before proceeding.
4. If the reviewer returns NEEDS_CHANGES, stop and report its findings. Do NOT
   merge.
5. Only after APPROVAL: switch to `master` and merge with `--no-ff` using a
   merge commit message that references the milestone, e.g.
   `Merge branch 'dev' into master — M4 session creation`.
6. Switch back to `dev`.
7. Report: what was reviewed, the reviewer status, the merge commit hash, and
   that `dev` is now in sync with `master`.

Never force-push, rebase, or fast-forward master behind the reviewer gate.
