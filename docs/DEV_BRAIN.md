# DEV_BRAIN.md — Friday Karaoke (active development context)

This is the working context for the current milestone. Updated at the start and end
of every milestone. The persistent context lives in `PROJECT_BRAIN.md`.

---

## Current milestone

**M18 — Testing + failure scenarios** — COMPLETE (verified).

## Current task

**Optimistic playback/moderation follow-up (D54) — IMPLEMENTED, verification in progress.**

This follow-up extends the D53 instant-add UX to the rest of the live queue
surface. Queue snapshots now expose `cooldown_seconds` and `countdown_seconds`,
and the shared frontend queue store holds the last authoritative snapshot plus a
temporary optimistic snapshot. Host dashboard actions — session start/end,
playback start/end/finish/skip/advance/pause/resume, host remove/reorder/edit —
render immediately, fire the backend mutation in the background, reconcile from
REST/WebSocket snapshots, and revert to the last authoritative snapshot on
failure. Participant cancel also hides the row immediately and restores it on
failure. The host UI shows a subtle syncing badge while a prediction is pending.

Previous task: **Optimistic queue + keyless metadata (D53) — IMPLEMENTED, verified locally; host participant UI follow-up applied.**

Phase 2 moved song adding to an optimistic/local-first UX while keeping the
backend/database authoritative. The frontend now has `QueueProvider`/
`useQueueStore` for temporary optimistic rows, keyless YouTube oEmbed metadata
(`frontend/src/lib/youtube.ts`) with localStorage caching, an instant participant
add-song card, and optimistic host participant add rows. The backend submit paths
now degrade gracefully on YouTube Data API quota/rate-limit exhaustion: participant
submit and host participant add fall back to server-side oEmbed metadata
(`duration_seconds=0`) instead of failing, while preview stays strict so duration
warnings remain authoritative. If a later Data API fetch succeeds, a previous
oEmbed-only video row is refreshed with the real duration/title/channel/thumbnail.
Verification: backend suite **283 passed**; `uv run pyright` reports 0 errors;
frontend `npm run typecheck`, `npm run lint`, and `npm run build` all pass. PWA
work moves after this follow-up.

Host participant UI follow-up: `/host/sessions/{id}/participants` now opens with a
grid of singer tiles/cards. The host clicks a singer to open a selected-singer
detail panel, then adds YouTube links to that singer's playlist there. This keeps
the screen from showing every add-song form at once. Frontend verification after
this UI follow-up: `npm run typecheck`, `npm run lint`, and `npm run build` pass.

Previous task: **Host add-song reliability follow-up — IMPLEMENTED, verified locally.**

Real-use feedback showed phone participants could keep adding songs while host-added
no-phone participants eventually did not appear in the queue. Root cause: the D52
host-created participants were given `last_connected_at` at creation but never had a
device/WebSocket to refresh it, so the M16 lazy absent cleanup cancelled their
WAITING songs after the cleanup window, including songs submitted by the host right
before the broadcast snapshot. Fix: host-created/no-phone participants now store
`last_connected_at = None` and are not absence-tracked; QR-created participants keep
normal cleanup. YouTube Data API quota/rate-limit failures are also surfaced as a
distinct 503 instead of the misleading "video unavailable" 404. Regression tests
were added to `backend/tests/test_host_participants.py`, `backend/tests/test_entries.py`,
and `backend/tests/test_youtube.py`. Verification: backend suite **278 passed**;
`uv run pyright` reports 0 errors.

Previous task: **Host-assisted participant management (D52) — IMPLEMENTED,
verified, pushed/deployed.**

The host gets a separate `/host/sessions/{id}/participants` screen to keep the
playback dashboard mostly unchanged. It lists each participant and their
non-terminal queued playlist, lets the host create a participant by nickname, and
lets the host add a YouTube URL directly to any participant. Backend endpoints:
`GET/POST /api/v1/sessions/{id}/participants` and
`POST /api/v1/sessions/{id}/participants/{participantId}/entries`. Direct add
reuses the existing metadata fetch, song cap, round-robin assignment, duplicate
notice, and realtime `QueueUpdated` broadcast. Tests added:
`backend/tests/test_host_participants.py`.

Earlier task: **Participant "leave session" feature (D50) — IMPLEMENTED,
verified, DEPLOYED via CI.**

A participant can delete themselves from the session (`POST /api/v1/sessions/{id}/leave`):
their identity and all their songs are removed via the DB cascade (nickname freed,
token dies, absent from future rounds), and if they were the current singer playback
advances (E6). The participant queue screen has a "Leave session" button. SQLite's
foreign-key cascade is now enabled in the test engine (`PRAGMA foreign_keys=ON`) so
the suite exercises the same cascade PostgreSQL has. Suite **264 passed**; pyright 0;
frontend green; local smoke verified deletion + nickname reuse. Live revision
`karaoke-app-00006-9bb` (health + DB OK). The queue revision (join order /
skip-to-end / per-round reorder) is already deployed. Decisions D43/D20/D50 carry
notes. Next milestone: **M19 — PWA + mobile UX**.

## CI/CD pipeline (live)

Pushing to `dev` auto-builds the image and deploys to Cloud Run
(`.github/workflows/deploy-dev.yml`, live as of this milestone). Auth uses the
`github-actions-deployer` service-account key stored only as the encrypted
`GCP_SA_KEY` GitHub Actions secret (never in the repo/history); Neon DB URL and
YouTube API key are also Actions secrets. Initially tried keyless Workload Identity
Federation, but its impersonated-credentials path kept denying
`iam.serviceAccounts.getAccessToken` despite correct bindings — pivoted to a SA key
(same secret-not-in-repo protection). Cloud Run's runtime SA needs the deployer to
have `roles/iam.serviceAccountUser` (actAs) on it. A future `master` branch can get
its own deploy workflow to a separate server.

## Frontend UX follow-up (submit → queue)

Participant submit keeps the original post-submit flow: the success card remains on
the add-song screen with **View Queue** and **Add Another** actions. The queue screen
only changes its initial loading state: while the authoritative snapshot loads, it
keeps the mobile topbar visible and shows a styled loading card instead of a bare
"Loading queue…" message. Host dashboard initial loading now uses the wide
host/projector layout instead of the mobile participant container. Frontend checks:
`npm run typecheck`, `npm run lint`, `npm run build`.

## Frontend visual refresh follow-up

The frontend now uses a more energetic karaoke/music-app visual treatment: richer
dark gradients, glowing primary actions, glassy cards, playlist-style queue rows
with thumbnails, and a participant queue view with **Live queue / Your songs** tabs.
The participant "Now singing" card renders like a music player with a spinning
record-style thumbnail (disabled for reduced-motion users). Host screens keep their
existing workflow but get the same modernized surfaces, stronger projector contrast,
and a more polished participant-management view. Frontend checks: `npm run
typecheck`, `npm run lint`, `npm run build`.

## M18 scope (plan.md §M18)

Formalize the behavioral + integration + concurrency test matrix. Most behaviors
were already covered by the endpoint suite; M18 adds the **concurrency and
failure-scenario** tests that were missing: rapid-submission determinism, the
find-or-create races, single-transition guarantees under host intervention, the
E21 cancel-vs-remove race in both directions, and host/participant reconnect
recovery.

## Verification results (M18, plan.md §M18 — matrix)

| Area | Result |
| ---- | ------ |
| Queue ordering (deterministic) | Verified — `test_two_participants_submit_rapidly_are_ordered` (burst of three submissions → stable order + positions 1–3) |
| Find-or-create race handling | Verified — duplicate songs share one `YouTubeVideo` row (`test_rapid_duplicate_submits_share_one_video_row`); lazy rounds are created once and reused (`test_rapid_second_submits_reuse_the_same_future_round`); the race path (a concurrent winner already inserted the row) is handled (`test_find_or_create_video_uses_existing_row`, `test_find_or_create_round_uses_existing_round`) |
| Skip / finish / remove / cancel semantics | Verified — `test_skip_during_countdown_is_not_possible` (nothing singing → 409); E21 both directions: participant-cancel-then-host-remove no-ops (M14) and host-remove-then-participant-cancel is rejected with the state preserved (`test_host_remove_then_participant_cancel_ends_valid`) |
| "Only one valid transition" (host skip/advance during automation) | Verified — `test_advance_twice_yields_a_single_transition`: with cooldown 0, `end` enters COUNTDOWN directly and the first advance auto-starts with exactly one entry `SINGING`; a second advance is a 409 no-op |
| Reconnect recovery (host + participant, D18/D5/E8/E11) | Verified — `test_host_reconnect_recovers_playback_state` (fresh fetches show ACTIVE + PLAYING + SINGING after a browser close); `test_participant_reconnect_recovers_identity_and_queue` (stored token re-fetches the participant's entries and reconnects to the realtime channel) |
| Integration (session creation, joining, submission, moderation, authorization, persistence) | Verified — covered by the existing suite (test_sessions/test_join/test_queue/test_playback/test_rounds) |

Additional verification:

- Backend suite: **240 passed** (230 prior + 10 new `tests/test_concurrency.py`),
  `pyright` 0 errors. No code changes in M18 (tests only) — none of the new
  tests surfaced a bug in the find-or-create/transition/race logic.
- Frontend unchanged; typecheck/lint/build still green.
- Note: true *simultaneous* requests cannot run against the in-memory SQLite
  test engine (StaticPool shares one connection), so "simultaneous" is exercised
  as rapid sequential requests — the backend serializes them, which is the
  observable contract. True multi-connection concurrency is exercised only
  against PostgreSQL (deployment, M20).

## Files changed (M18)

```text
backend/tests/test_concurrency.py     (new — 10 tests)
docs/PROJECT_BRAIN.md, docs/ARCHITECTURE.md, docs/DEV_BRAIN.md, docs/RUNBOOK.md
```

## Implementation notes (M18)

- **Concurrency semantics:** the tests assert the *observable* contract (rapid
  sequential requests are serialized deterministically) and exercise the
  find-or-create race handling directly (a pre-inserted "concurrent winner" row
  is found, not violated). The M13 frozen-clock pattern is not needed here
  (cooldown/countdown 0 sessions make transitions instant).
- **No scope creep:** M18 is tests + docs only — no new endpoints, no schema
  change, no new dependencies, no production-code edits.

## Tests added (M18)

- `tests/test_concurrency.py` (10): rapid submissions ordered; duplicate songs
  share one video row; second songs share one round; find-or-create video race;
  find-or-create round race; advance-twice yields one transition; skip during a
  countdown is impossible; host-remove-then-cancel ends valid (E21); host
  reconnect recovers playback state; participant reconnect recovers identity +
  queue.

## Current blockers

- None.

## Unresolved technical questions

- Starlette deprecation warning (`httpx` vs `httpx2` in `fastapi.testclient`) —
  non-blocking, tracked since M0.
- FastAPI 0.141.1 dependency-name collision (D30): workaround documented; watch
  for an upstream fix.
- `RealtimeHub` + `RateLimiter` are in-process/per-worker (D42/D49): a
  multi-worker deployment needs shared state — tracked for M20.
- Web Push deferred to the PWA milestone (M19) — documented in DECISIONS.
- True concurrent-request testing needs PostgreSQL (the SQLite test engine
  serializes via StaticPool) — exercised at deployment (M20).

## Next recommended task

**M19 — PWA + mobile UX** (frontend): web manifest + installable PWA, a service
worker for offline/reconnect handling (and the deferred Web Push "you're next"
notifications via VAPID), plus mobile/offline polish (loading/error states,
QR-friendly join URL, large touch targets already in place).
