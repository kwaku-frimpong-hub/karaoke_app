# PROJECT_BRAIN.md — Friday Karaoke

This is the authoritative, persistent project context for every coding agent.
**Read this file before modifying the project.**

Related files:

- `plan.md` — full milestone definitions and acceptance criteria
- `docs/PRODUCT_SPEC.md` — frozen MVP behavioral contract (flows, edge cases, rules)
- `docs/ARCHITECTURE.md` — system design
- `docs/DOMAIN_MODEL.md` — entities, states, relationships
- `docs/API_CONTRACT.md` — planned API surface
- `docs/DECISIONS.md` — architectural decisions (and why)
- `docs/DEV_BRAIN.md` — active development context (current task)
- `docs/RUNBOOK.md` — local development commands

---

## 1. Product purpose

A private karaoke queue application for our school's Friday karaoke nights.
It removes the repetitive work currently done by the host:

1. Host creates a karaoke session.
2. Application generates a QR code.
3. Students scan the QR code.
4. Students enter a nickname and paste the YouTube URL of the song they want.
5. The application fetches/displays the video metadata and puts the entry in the queue.
6. Everyone can see the current queue and their position.
7. The host has final control over the queue and playback.
8. The host's browser is the playback device (connected to the school's screen/speakers).
9. Songs transition automatically, with configurable preparation/cooldown time.
10. The next singer is notified.
11. When a round ends, participants are asked whether they want to join the next round.
    Default: YES if they do nothing.

The application is intended for **real use at school**, not just a portfolio demo.

## 2. Target users

- **Host** — the person who runs the Friday karaoke night (teacher/student organizer).
  Has an account, creates/manages sessions, has final authority over the queue and playback.
- **Participants** — students who attend. **No account required.** They scan the QR code,
  enter a nickname, and submit YouTube URLs. They can watch the queue and their position.

## 3. Core user journeys

Detailed flows, screens, edge cases, and normative behavioral rules are frozen in
**`docs/PRODUCT_SPEC.md`** (M1). The short versions:

### Host

```text
Login
  -> Create session
  -> Display QR
  -> Monitor queue
  -> Start / skip / edit / remove
  -> Automatic playback (host browser is the playback device)
  -> Finish round
  -> Start next round
  -> End session
```

### Participant

```text
Scan QR
  -> Enter nickname
  -> Paste YouTube URL
  -> Review song metadata
  -> Join queue
  -> Monitor position
  -> Receive "you're next"
  -> Perform
  -> Participate in next round (default YES)
```

## 4. Current architecture (summary)

- One **modular monolith** backend (FastAPI + PostgreSQL). No microservices.
- Backend/database is the **single source of truth** for queue order, current singer,
  round state, playback state, permissions, participant identity, and session state.
- Frontend is a React + TypeScript SPA (Vite). It never owns authoritative state;
  it can keep temporary optimistic overlays for instant song-add, playback,
  moderation, and cancel UX, reconciled by backend snapshots (D53/D54).
- Realtime delivery via **FastAPI WebSockets** (implemented M10). WebSockets are a delivery
  mechanism, **not** the source of truth; clients resync from the backend after reconnect.
- **Queue rounds** (M10.1): the queue is round-robin — one song per participant per
  round in a stable participant order, the active round is derived and auto-advances,
  and there is no next-round enrollment (decisions D43–D45).
- The **host's browser is the playback device** (YouTube embedded player).
  Participants' phones never play the song.

See `docs/ARCHITECTURE.md` for details.

## 5. Technology stack

| Concern          | Choice                          |
| ---------------- | ------------------------------- |
| Backend          | Python 3.12+ / FastAPI          |
| Database         | PostgreSQL                      |
| ORM              | SQLAlchemy 2.x                  |
| Migrations       | Alembic                         |
| Realtime         | FastAPI WebSockets              |
| Frontend         | React + TypeScript              |
| Build tooling    | Vite                            |
| PWA              | web manifest + service worker   |
| Containers       | Docker / Docker Compose         |
| Reverse proxy    | Caddy or Nginx                  |
| Notifications    | Web Push                        |
| Testing          | pytest + integration tests      |
| Dependency mgmt  | uv (preferred)                  |
| Validation       | Pydantic v2                      |
| Settings         | Pydantic Settings               |
| ASGI server      | Uvicorn                          |
| Static types     | Pyright or mypy                  |

## 6. Domain concepts

See `docs/DOMAIN_MODEL.md` for full detail. High-level:

- **Host** — account holder with authority over sessions.
- **Session** — one karaoke night. Contains multiple rounds. Has a join code / QR link.
- **Participant** — session-scoped identity (nickname). No account. Created by joining.
- **Round** — one pass through the queue within a session.
- **QueueEntry** — a participant's song in a round, with status and a *computed*
  position (derived from authoritative order, never stored as a mutable field).
- **YouTubeVideo** — metadata snapshot (video ID, URL, title, channel, duration, thumbnail).

```text
Host
 |
 +---- Session
          |
          +---- Participant
          |
          +---- Round
                  |
                  +---- QueueEntry
                          |
                          +---- YouTubeVideo
```

## 7. Important business rules

The normative, implementer-facing rules are in `docs/PRODUCT_SPEC.md` §9
(rules B1–B18). The high-level rules below remain the canonical summary:

1. Only authenticated hosts can create/manage sessions.
2. Anyone with the session QR/link can join. Participants need no account.
3. Participants can cancel their own waiting entries (current or future rounds);
   they cannot modify others'.
4. Host has final authority over the queue (remove any entry, edit YouTube URLs, skip,
   pause/resume, advance manually, end the session).
5. Invalid YouTube URLs cannot be queued. Long videos produce a **warning**, not a rejection.
6. Queue order is authoritative backend state: one song per participant per round,
   in stable participant order, with a derived active round that auto-advances —
   never a mutable position field (D43).
7. Host playback is authoritative for actual song playback.
8. Automatic advancement can always be overridden by the host.
9. A session contains multiple rounds; rounds advance automatically, no next-round
   enrollment (do not create a new session per round).
10. A participant may queue up to 5 songs total (configurable); beyond the cap is
    rejected. A participant with no songs left drops out of later rounds.
11. Realtime events are not authoritative state. Reconnecting clients must resync.
12. Host actions must be authorized server-side.
13. The application must remain usable if realtime connections temporarily fail.

Additional M1 decisions (duplicate songs allowed, nickname rules, per-participant
song cap, sessions not tied to a browser) are in `docs/PRODUCT_SPEC.md` §8–§9 and
`docs/DECISIONS.md` D15–D20 / D43–D45.

## 8. Current milestone

**M19 — PWA + mobile UX** (next; frontend). Active follow-up: host-assisted
participant management for singers without phones (D52) — separate host screen,
participant playlist view, and host add-song flow. M18 is complete; see
`docs/DEV_BRAIN.md` for live status.

## 9. Completed milestones

- **M18 — Testing + failure scenarios** (complete, tests): formalized the
  behavioral/concurrency/failure matrix — rapid-submission determinism,
  find-or-create race handling (video + round), single-transition guarantees
  under host intervention, E21 in both directions, and host/participant
  reconnect recovery. 10 new tests (suite 240); pyright 0; tests-only, no code
  changes (no bugs surfaced).
- **Host add-song reliability follow-up** (backend): host-created/no-phone
  participants are no longer absence-tracked (`last_connected_at = NULL`) so the
  M16 lazy cleanup does not cancel host-added songs after 30 minutes; QR-created
  participants still use normal realtime-based cleanup. YouTube quota/rate-limit
  failures are surfaced as HTTP 503 instead of the misleading video-unavailable
  404. Regression coverage added in host participants, entries, and YouTube tests.
- **Optimistic queue + keyless metadata follow-up** (backend + frontend): song
  adds now feel client-side without changing backend authority. The frontend uses
  keyless YouTube oEmbed + localStorage metadata cache and renders temporary
  optimistic rows for participant and host add-song flows; submit paths still sync
  to the backend in the background and reconcile from authoritative snapshots.
  Backend submit/host-add degrade gracefully on Data API quota/rate limits by
  falling back to oEmbed metadata (`duration_seconds=0`), while preview remains
  strict for duration warnings.
- **Optimistic playback/moderation follow-up** (backend + frontend): queue
  snapshots expose per-session `cooldown_seconds`/`countdown_seconds`; the shared
  frontend queue store now holds the authoritative snapshot plus a temporary
  optimistic snapshot. Host playback, start/end, remove/reorder/edit, and
  participant cancel update instantly, then reconcile via REST/WebSocket or
  revert with an error on failure (D54).
- **M17 — Security + abuse protection** (complete, backend): in-process fixed-
  window rate limiting on the public QR surface (`app/core/ratelimit.py`, D49) —
  join 10/min/IP, preview 20/min/IP, submit 20/min/IP → 429; a YouTube metadata
  TTL cache (1 h) protects the Data API daily quota from repeated lookups of the
  same video; the session retention strategy is documented (no destructive
  cleanup in v1, M22 ops). 8 new tests (suite 230); pyright 0; live smoke: 11th
  join 429, repeated previews cached.
- **M16 — Round lifecycle cleanup + summaries** (complete, backend + frontend):
  absent-participant cleanup — `last_connected_at` on participants (set at join,
  refreshed on realtime connect) with a lazy GC-on-render cleanup
  (`KARAOKE_ABSENT_PARTICIPANT_CLEANUP_SECONDS`, default 30 min, D48, migration
  `0007`) that cancels stale participants' remaining WAITING songs. Round/
  participant summaries: `rounds_completed` + per-participant `remaining_songs`
  in the snapshot (dashboard shows "Round N (M completed)" and "· N more" per
  row), plus a host-only `GET /sessions/{id}/summary` (submitted/sung/remaining)
  for the wrap-up. 7 new tests (suite 223); pyright 0; live smoke confirmed.
- **M15 — Next-singer notifications** (complete, backend + frontend): a typed
  `NextSingerNotified` realtime event (phase `next` on `NEXT` promotion, phase
  `countdown` at countdown start) delivers in-app "you're next!" notifications;
  the participant queue screen renders a filtered, auto-dismissing banner
  (PRODUCT_SPEC §11). Web Push deferred to the PWA milestone (M19) — the Web
  Push open question is resolved. 4 new tests (suite 216); pyright 0; live smoke
  confirmed Bob's device received both phases.
- **M14 — Host moderation + manual controls** (complete, backend): the host's
  full authority surface is live (PRODUCT_SPEC §5.5): Remove + Edit (M7),
  Skip/Finish/Pause/Resume (M11/M13), End session (M4). M14 closes the last
  gap — **removing the current `SINGING` entry advances playback** (promotes the
  next to `NEXT` and begins the countdown, E6), so the host can recover from a
  bad live song without database access; removing an already-terminal entry is a
  no-op (E21). 4 new tests (suite 212); pyright 0; live smoke confirmed.
- **M13 — Automatic song transitions** (complete, backend + frontend): sessions
  gain stored playback state + authoritative transition deadlines
  (`playback_state`, `transition_until`, per-session `cooldown_seconds`/
  `countdown_seconds`, defaults 10/20, D47; migration `0006`). Songs advance
  automatically: natural end → `play/end` → COOLDOWN → COUNTDOWN → auto-start
  (`play/advance`, idempotent, no background timers); host skip/finish skip the
  cooldown (D20). The host dashboard counts down and calls advance; a reopened
  tab   self-recovers. `COOLDOWN`/`COUNTDOWN` are now reachable (D46 superseded by
  D47; `PREPARING` remains a documented enum value — the player pre-loads during
  the countdown). 8 new tests (suite 208); pyright 0; live smoke verified
  the full transition cycle against Postgres + real YouTube.
- **M12 — YouTube host player** (complete, frontend): the host dashboard embeds
  the YouTube IFrame player (host browser is the playback device, D4). A new
  `YouTubePlayer` component loads the `SINGING` entry's video from the snapshot,
  attempts playback after the host's start gesture, detects completion and
  reports it back via the M11 `finish` endpoint, and maps player errors to
  host-facing messages (E5/E24). The IFrame API is loaded at runtime; a small
  ambient `src/youtube.d.ts` types the YT surface (no new dependency). No
  backend changes; suite still 199; typecheck/lint/build green.
- **M11 — Playback state machine** (complete, backend + frontend): host-driven
  playback endpoints under `/api/v1/sessions/{id}/play/…` (start/skip/finish/
  pause/resume) that promote entries through `WAITING → SINGING → COMPLETED/
  SKIPPED` (with `NEXT` on advance, D20), enable the dashboard's previously
  disabled Skip/Finish/Pause/Resume buttons (D40), and make `PAUSED` reachable.
  Playback state is **derived** (`PLAYING` iff an entry is `SINGING`, D46) and
  surfaced in the snapshot; round boundaries auto-advance (M10.1). New realtime
  events `SingerStarted`/`SingerFinished`/`SingerSkipped`. No schema migration.
  15 new tests (suite 199); pyright 0; live smoke confirmed the full host-driven
  flow.
- **M10.1 — Queue rounds + auto-advance** (complete, backend + frontend): the
  queue is round-robin — one song per participant per round, in stable
  participant order (earliest first engagement), with the active round derived
  (lowest-numbered round with a non-terminal entry) and auto-advancing when it
  empties. `ROUND_COMPLETE` and the M16 enrollment prompt were removed
  (participants opt out by cancelling remaining songs); the per-participant cap
  is `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT` (default 5, D45); the snapshot
  gains `round_number`; a participant-scoped `GET /entries/mine` lists current +
  upcoming songs. No schema migration (entries were already round-scoped). 9
  new queue/round tests (suite 184); pyright 0; frontend round badge + "Your
  songs" section; live smoke against Postgres + real YouTube metadata confirmed
  round assignment, auto-advance, and positions.
- **M10 — Realtime updates** (complete, backend + frontend): FastAPI WebSocket
  channel at `GET /api/v1/sessions/{id}/ws` with the bearer token in a `token`
  query param (browser WS cannot set headers); tokens must belong to the
  session (participant bound to it / host owning it) or the upgrade is rejected
  (D42). An in-process `RealtimeHub` (`app/realtime/hub.py`, no Redis per D9)
  fans out typed events per session; REST routes broadcast after domain changes
  commit: `QueueUpdated` (full authoritative `QueueSnapshotResponse`, on
  submit/cancel/remove/edit), `ParticipantJoined` (join), `SessionUpdated`
  (start/end). Event models in `app/schemas/realtime.py` (typed, never
  free-form). The participant queue screen and host dashboard subscribe via
  `src/ws/client.ts` + `src/ws/useRealtime.ts` and fall back to 5 s snapshot
  polling while the socket is down (B13/D42); reconnecting clients re-fetch the
  REST snapshot (D5). Vite dev proxy forwards WS (`ws: true`). 12 new realtime
  tests; suite now 175 passed; live smoke verified against PostgreSQL.
- **M9.1 — Frontend UI polish** (complete, frontend + config): codified the
  project's frontend UI quality bar as the `frontend-ui` skill
  (`.opencode/skills/frontend-ui/SKILL.md`), wired into the coder and reviewer
  agents, added a "Frontend UI quality bar" section and the M9.1 milestone to
  `plan.md`, and refactored all screens onto the new design system: CSS design
  tokens (colors/spacing/radius/type scale) in `src/index.css`, token-driven
  component styles in `App.css`, labeled inputs with `:focus-visible`, per-fetch
  loading/empty/error states, and the invalid `<a>`-wrapping-`<button>` nesting
  on the host home removed. No backend changes; suite still 163 passing.
- **M9 — Host Dashboard** (complete, frontend + one backend endpoint): the host's
  projector/TV control screen — `HostAuthScreen` (login/register, M3),
  `HostHomeScreen` (create session + list own sessions), and
  `HostDashboardScreen` (now/next cards, full queue with names/titles/durations,
  QR + join code, start/remove/edit/end actions; skip/finish/pause/resume
  rendered disabled until M11). Host identity persisted in localStorage (D39);
  dashboard polls the queue snapshot every 5 s (D38) until M10 websockets. New
  backend `GET /api/v1/sessions` (list own sessions, newest first) powers the
  home screen and E11 re-sync. Decisions D39–D40 recorded in
  `docs/DECISIONS.md`.
- **M8 — Participant Queue UI** (complete, first frontend milestone): mobile-first
  participant screens — join by nickname (`/join/:code`), song submit with
  preview→confirm (`/join/:code/submit`), and a polled queue screen
  (`/join/:code/queue`) showing session status, now/up-next cards (from backend
  statuses), positions, and cancel of own WAITING entries. Typed API client
  (`src/api/`), participant identity in localStorage (D38, E8), Vite `/api` dev
  proxy, `react-router-dom`. Frontend never owns queue state (D2).
- **M7 — Queue Management** (complete): the authoritative queue engine —
  `QueueEntry` + `YouTubeVideo` + `Round` tables (migration `0005_queue`; round 1
  created with the session, D35), submit (`POST /sessions/{id}/entries`, with the
  active-entry limit B15 and duplicate notice B16), public queue snapshot with
  computed positions (D8/D36), participant cancel of own WAITING entry and host
  remove via one dual-actor endpoint (D37), and host URL editing (E7). Queue
  decisions D35–D37 recorded in `docs/DECISIONS.md`.
- **M6 — YouTube URL Submission + Metadata** (complete): `POST
  /api/v1/sessions/{id}/entries/preview` (participant token) validates YouTube
  URLs (watch/youtu.be/embed/shorts), extracts the video ID, fetches metadata
  (title/channel/duration/thumbnail) from the YouTube Data API v3 (D33,
  `KARAOKE_YOUTUBE_API_KEY`), and returns a stateless preview with a
  configurable long-video warning that never rejects (D34, B6). New
  `get_current_participant` dependency; metadata decisions D33–D34 recorded in
  `docs/DECISIONS.md`.
- **M5 — Public QR Join Flow** (complete): public session lookup by join code
  (`GET /api/v1/join/{code}`, case-insensitive) and participant registration
  (`POST /api/v1/join/{code}/participants`) — no account, nickname rules
  B14/D16 (trimmed, 1-20 chars, case-insensitive uniqueness per session), opaque
  participant tokens stored as SHA-256 digests (D31), ended-session guard, and a
  server-side SVG QR endpoint `GET /api/v1/sessions/{id}/qr` encoding the join
  URL (D32). `Participant` table (migration `0004_participants`); `segno` added
  for QR generation. Decisions D31–D32 in `docs/DECISIONS.md`.
- **M4 — Karaoke Session Creation** (complete): host-owned sessions with
  create/get/start/end under `/api/v1/sessions` (auth via `get_current_host`,
  cross-host access → 404), the `SessionStatus` domain state machine
  (`CREATED -> ACTIVE <-> PAUSED -> ROUND_COMPLETE -> ENDED`), 6-char
  unambiguous unique join codes (D27), derived join URLs from
  `KARAOKE_PUBLIC_BASE_URL` (D28), ownership + strict-transition semantics (D29),
  `Session` table (migration `0003_sessions`), and a documented FastAPI 0.141.1
  dependency-name collision workaround (D30 — never name an endpoint like a
  dependency). Sessions decisions D27–D30 recorded in `docs/DECISIONS.md`.
- **M3 — Host Authentication** (complete): host registration/login with
  email/password, bcrypt password hashing, opaque revocable bearer tokens (only a
  SHA-256 digest stored), logout, the `get_current_host` dependency protecting host
  endpoints, `GET /api/v1/auth/host/me`, `Host` + `HostAuthToken` tables (migration
  `0002_host_auth`), and confirmation of the `/api/v1` API base path (D26). Auth
  decisions D25–D26 recorded in `docs/DECISIONS.md`.
- **M2 — Backend Skeleton + Database** (complete): FastAPI app factory, async
  SQLAlchemy 2.x + asyncpg, PostgreSQL via Docker Compose (`compose.yaml`), Alembic
  migrations (async env, initial revision), Pydantic Settings (`KARAOKE_` prefix),
  structured JSON logging, project layers (api/core/models/schemas + empty
  domain/services/repositories), and health endpoints (`/`, `/health`,
  `/health/ready` with a database probe). Tests run self-contained on SQLite;
  verified against real PostgreSQL locally.
- **M1 — Product Specification + UX** (complete): MVP behavior frozen in
  `docs/PRODUCT_SPEC.md` — roles and authority matrix, session/round lifecycles,
  detailed host and participant flows, screen inventory, 24 edge cases (E1–E24),
  and normative behavioral rules B1–B18. Behavioral decisions D14–D20 recorded in
  `docs/DECISIONS.md`.
- **M0 — Repository + Project Brain** (complete): repository layout, backend
  (FastAPI + health check), frontend (Vite + React + TS scaffold), and the full
  documentation set under `docs/`. Backend and frontend both start; no business
  functionality exists yet.

## 10. Known limitations

- **Web Push is not implemented** (M15 = in-app notifications only); out-of-band
  "you're next" alerts need the M19 service worker + VAPID credentials.
- Rate limits and the YouTube quota cache are in-process (D49): a multi-worker
  deployment needs a shared limiter/store (M20).
- YouTube playback is only exercisable in a real browser (autoplay policies,
  audio output); automated checks cover the build and the backend contract.
- Realtime (M10) delivers only the events whose producers exist: `QueueUpdated`
  (submit/cancel/remove/edit), `ParticipantJoined` (join), and `SessionUpdated`
  (start/end). Round events arrive with M10.1; singer/pause events with their
  milestones (M11/M13/M14). The `RealtimeHub` is in-process/per-worker (D42): a
  multi-worker backend would need a shared hub (Redis) first (D9).
- Only the Host/HostAuthToken/Session/Participant/YouTubeVideo/Round/QueueEntry
  tables exist (migration `0005`). PAUSED is defined but not reachable yet
  (M14). ROUND_COMPLETE was removed from the domain at M10.1 (rounds
  auto-advance; no enrollment).
- Song previews and submissions require `KARAOKE_YOUTUBE_API_KEY` (YouTube Data
  API v3, D33); without it those endpoints return 503. Tests mock the HTTP call.
- Host bearer tokens are long-lived (30 days) unless logged out; fine for the
  pilot, token rotation/refresh is not in scope for v1.
- Browser autoplay policies will require host interaction before audio playback
  (to be designed for in M12/M13).
- The automated test suite uses in-memory SQLite; Postgres-specific SQL should be
  avoided in domain code or handled dialect-aware (see DECISIONS D22). UUID columns
  use the generic `sqlalchemy.Uuid` type, which is dialect-safe. Queue ordering
  uses a microsecond Python timestamp default to keep SQLite tests deterministic
  (D36).
- FastAPI 0.141.1 has an unresolved dependency-name collision bug (D30): an
  endpoint function sharing a `__name__` with a dependency breaks literal-suffix
  routes. Workaround (naming convention) is in effect; watch for an upstream fix.

## 11. Important decisions

See `docs/DECISIONS.md` for the full, maintained list. Highlights:

- Modular monolith; no microservices/Kafka/Kubernetes unless a concrete requirement appears.
- Backend is the single source of truth; frontend never owns state.
- Host browser is the playback device.
- WebSockets deliver events but never replace authoritative state.
- Participants are session-scoped identities, not accounts.
- Do not over-validate YouTube content (validate format, warn on length, never auto-reject).
- Redis is not required for the first deployment.
- MVP behavior is frozen in `docs/PRODUCT_SPEC.md` (M1): duplicates allowed,
  nickname rules, per-participant song cap (D45), round-robin queue ordering
  (D43), sessions not tied to a browser connection.
- Async SQLAlchemy + asyncpg; self-contained SQLite test suite; dev PostgreSQL via
  Docker Compose; stdlib JSON logging (M2, DECISIONS D21–D24).
- Host auth: email/password + bcrypt, opaque revocable bearer tokens hashed at rest
  (D25); business API base path `/api/v1` confirmed, health endpoints stay at root
  (M3, DECISIONS D25–D26).
- Sessions (M4): unambiguous 6-char unique join codes (D27), join URL derived from
  `KARAOKE_PUBLIC_BASE_URL` and never stored (D28), cross-host access returns 404
  and state transitions are strict server-side (D29), FastAPI 0.141.1
  dependency-name collision workaround (D30).
- Public join (M5): participants are session-scoped identities with opaque tokens
  hashed at rest and case-insensitive per-session nickname uniqueness (D31); QR
  codes are generated server-side as SVG encoding the join URL (D32).
- YouTube previews (M6): metadata comes from the YouTube Data API v3 with
  `KARAOKE_YOUTUBE_API_KEY` (D33); long videos warn but are never auto-rejected,
  threshold configurable via `KARAOKE_YOUTUBE_LONG_VIDEO_SECONDS` (D34).
- Queue engine (M7): rounds exist from session creation and entries are
  round-scoped (D35); ordering is microsecond `created_at` + `id` tie-break (D36);
  YouTubeVideo rows are shared per video id and DELETE /entries/{id} is dual-actor
  (participant cancel vs host remove) (D37).
- Participant UI (M8): the frontend is a thin renderer — typed API client, identity
  in localStorage, snapshot polling until M10 websockets (D38).
- Host dashboard (M9): host identity in localStorage, a `GET /api/v1/sessions`
  list endpoint for the dashboard home / E11 re-sync, and the dashboard's action
  bar wired only to existing M4/M7 endpoints — playback actions stay disabled
  until M11 (D39, D40).
- Frontend UI (M9.1): the `frontend-ui` skill codifies the design system
  (tokens, two-surface layout, components, accessibility) and is the quality bar
  for every frontend milestone; all screens now use the token-driven styles.
- Realtime (M10): one authenticated WebSocket channel per session
  (`/api/v1/sessions/{id}/ws`, token in the query param) with an in-process
  per-worker `RealtimeHub` (no Redis, D9); typed per-event payloads in
  `app/schemas/realtime.py`; only events whose producers exist are emitted;
  clients re-fetch on reconnect (D5, D42).
- Queue rounds (M10.1): the queue is round-robin — one song per participant per
  round in a stable participant order (earliest first engagement), the active
  round is derived and auto-advances, `ROUND_COMPLETE` and the next-round
  enrollment prompt are removed, and the per-participant cap is a configurable
  total of 5 (`KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT`) (D43–D45).
- Playback (M11): the playback state is derived (`PLAYING` iff an entry is
  `SINGING`, never stored) and host-driven via `/play/start|skip|finish|pause|
  resume`; advancing crosses round boundaries automatically; the full
  `PlaybackState` lifecycle (PREPARING/COUNTDOWN/COOLDOWN) waits for M13 (D46).
- Automatic transitions (M13): the playback state is now **stored** with
  authoritative transition deadlines (`transition_until`) and per-session
  timings (defaults 10/20); songs auto-advance COOLDOWN → COUNTDOWN → auto-start
  with no background timers — the dashboard counts down and calls the idempotent
  `play/advance`; host skip/finish skip the cooldown (D20, D46 superseded by
  D47).
- Round lifecycle (M16): absent-participant cleanup via `last_connected_at` +
  lazy GC-on-render (D48); snapshot round/participant summaries and a host-only
  session summary endpoint. Host-created/no-phone participants intentionally keep
  `last_connected_at = NULL` and are not absence-tracked, because they cannot
  refresh presence over WebSockets.
- Security (M17): in-process per-IP rate limits on join/preview/submit (429
  beyond the window) and a YouTube metadata TTL cache for quota protection; the
  service now distinguishes YouTube quota/rate-limit exhaustion as 503 instead
  of a video-unavailable 404; the rest of the abuse-protection checklist was
  already in place (D49).
- Optimistic queue/playback UX (D53/D54): client-side oEmbed metadata,
  temporary optimistic rows, and temporary optimistic snapshots make adds and
  host controls instant; backend/database still owns order, rounds, playback,
  permissions, identity, session state, and durable queue persistence.
- No user-visible feature in M0 beyond a health check.

## 12. Commands for running / testing

See `docs/RUNBOOK.md`. Short version:

```bash
# Database (local PostgreSQL via Docker Compose)
docker compose up -d db

# Backend
cd backend
uv sync
uv run alembic upgrade head                  # apply migrations
uv run uvicorn app.main:app --reload         # http://localhost:8000
uv run pytest                                # tests (SQLite, no Docker needed)
uv run pyright                               # static type check

# Frontend
cd frontend
npm install
npm run dev                                  # starts Vite dev server
npm run build                                # production build
npm run typecheck                            # tsc --noEmit
```

## 13. Things explicitly NOT to build (v1 non-goals)

- Spotify integration, song streaming service, custom karaoke music hosting
- AI recommendations / AI singing analysis
- Voting, leaderboards, payments/tipping
- Public/multi-venue management, public discovery of sessions
- Microservices, Kubernetes, Kafka, RabbitMQ, event sourcing
- Complex analytics, social profiles

These may be reconsidered only after the real school deployment proves the core product.

## 14. Agent rules reminder

- Work on `dev`. Never commit directly to `master`.
- Implement only the assigned milestone; no scope creep.
- Python typing rules (Pydantic v2 at boundaries, `Enum` for states, explicit types,
  static checks passing) apply to every milestone.
- At milestone completion: tests pass, docs updated, acceptance criteria verified.
