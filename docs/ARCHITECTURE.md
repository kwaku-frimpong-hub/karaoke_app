# ARCHITECTURE.md — Friday Karaoke

High-level design of the Friday Karaoke system. This is a living document and will
be refined as milestones are implemented. It describes both the current state and
the intended target state for v1.

---

## 1. System context

```text
                Internet / School WiFi
                         |
                         v
                Reverse Proxy (Caddy or Nginx)
                         |
            +------------+------------+
            |                         |
            v                         v
         Frontend                  Backend
       (React + TS SPA)          (FastAPI)
                                       |
                                       v
                                  PostgreSQL
```

- **Frontend** — React + TypeScript SPA built with Vite. Two main surfaces:
  participant flow (mobile-first) and host dashboard. Serves the QR join flow and
  the host playback UI. No authoritative state; D53/D54 add only temporary
  optimistic overlays for instant song-add, host control, and cancel UX.
- **Backend** — FastAPI modular monolith. Owns all authoritative state:
  queue order, current singer, round state, playback state, permissions,
  participant identity, session state.
- **PostgreSQL** — durable persistence for the backend's authoritative state.
- **Realtime** — FastAPI WebSockets push meaningful domain events to connected
  clients. Delivery only; clients resync from the backend after reconnect.

## 2. Guiding principles

1. **Backend owns the truth.** The frontend never decides queue order, who is
   singing, round state, or playback state. It renders what the backend says.
2. **Host is the final authority.** Normal operation is automated, but the host can
   always skip, remove, edit, pause/resume, advance manually, and end the session.
3. **Host browser is the playback device.** The host dashboard embeds the YouTube
   player and is connected to the school's screen/speaker setup. Participant
   devices never play the song, avoiding cross-device sync problems.
4. **Realtime is a delivery mechanism.** WebSocket events are denormalized
   notifications. After a reconnect, the client must re-fetch authoritative state.
5. **Modular monolith first.** One deployable backend. No microservices, Kafka,
   RabbitMQ, Kubernetes, CQRS, or event sourcing unless a concrete later
   requirement demands them.

## 3. Backend structure

Layout (implemented at M2: packages exist; `domain/` and `repositories/` were
placeholders; `services/` gained its first real use-case at M3 — host auth;
`domain/` gained its first real model at M4 — `SessionStatus`):

```text
backend/
    app/
        api/          # HTTP + WebSocket endpoints/routers (health M2, auth M3, sessions M4, join M5, entries M6, realtime M10, playback M11)
        core/         # config (Pydantic Settings), structured logging, database, security,
                      # rate limiting (M17, ratelimit.py)
        domain/       # domain models, enums, business rules, state machines (SessionStatus M4)
        services/     # use-cases (host auth M3, sessions M4, join M5, youtube M6, queue M7)
        repositories/ # persistence access (SQLAlchemy) (deferred until shared)
        models/       # SQLAlchemy ORM models (Host, Session, Participant, YouTubeVideo, Round, QueueEntry)
        schemas/      # Pydantic API schemas (health M2; auth M3; sessions M4; join M5; youtube M6; queue M7; realtime M10)
        realtime/     # in-process WebSocket delivery hub (M10, decision D42)
        main.py       # FastAPI app factory / entry point
    tests/            # pytest suite (self-contained: in-memory SQLite)
    alembic/          # migrations (async env; 0001..0004)
    alembic.ini
```

Implementation status at M6:

- **Configuration:** Pydantic Settings (`app/core/config.py`), env prefix
  `KARAOKE_`, `.env` file support, cached singleton via `get_settings()`. Auth
  token lifetime via `KARAOKE_AUTH_TOKEN_TTL_DAYS` (default 30, M3). Public
  frontend base URL via `KARAOKE_PUBLIC_BASE_URL` (default `http://localhost:5173`,
  M4). YouTube Data API key via `KARAOKE_YOUTUBE_API_KEY` and long-video warning
  threshold via `KARAOKE_YOUTUBE_LONG_VIDEO_SECONDS` (default 600, M6).
- **Database:** async SQLAlchemy engine + session factory + `get_session`
  dependency (`app/core/database.py`); PostgreSQL via `asyncpg`, in-memory SQLite
  for tests. Models: `Host`, `HostAuthToken` (M3), `Session` (M4), `Participant`
  (M5), `YouTubeVideo`, `Round`, `QueueEntry` (M7, UUID PKs via
  `sqlalchemy.Uuid`, dialect-safe on both PostgreSQL and SQLite). Queue
  `created_at` uses a microsecond Python default so SQLite ordering is
  deterministic (D36).
- **Security:** bcrypt password hashing, opaque bearer token generation, SHA-256
  token digesting (`app/core/security.py`) — shared by host tokens (M3) and
  participant tokens (M5).
- **Domain:** `SessionStatus` enum + transition rules (`app/domain/session.py`,
  M4) mirroring the documented lifecycle
  `CREATED -> ACTIVE <-> PAUSED -> ENDED`; `ENDED` is terminal
  and reachable from any other state. (`ROUND_COMPLETE` existed until M10.1,
  when rounds became automatic — see `docs/PRODUCT_SPEC.md` §3 and DECISIONS D44.)
- **Services:** `HostAuthService` (M3), `SessionService` (M4: create/get/start/
  end/pause/resume, unique join codes, creates round 1), `ParticipantService`
  (M5/M16: public session lookup, participant registration + `last_connected_at`
  presence tracking, token lookup), `YouTubeService` (M6: Data API v3 metadata
  fetch, URL validation, duration parsing), `QueueService` (M7/M10.1/M16:
  round-robin engine — round assignment, derived active round, stable ordering,
  per-participant cap, snapshots with computed positions + round/participant
  summaries, lazy absent-participant cleanup, cancel/remove, host URL editing),
  `PlaybackService` (M11/M13: host-driven start/skip/finish and automatic
  transitions — `play/end` begins COOLDOWN → COUNTDOWN → auto-start, host
  skip/finish skip the cooldown; playback state is stored on the session with
  authoritative transition deadlines, D47).
- **API:** health at root; host auth under `/api/v1/auth/host` (M3); sessions
  under `/api/v1/sessions` (create/get/**list (M9)**/start/end + SVG QR, M4/M5); public join
  under `/api/v1/join` (M5); song endpoints under `/api/v1/sessions/{id}/entries`
  (preview M6, submit + snapshot M7) and `/api/v1/entries` (cancel/remove, host
  edit, M7). Realtime under `/api/v1/sessions/{id}/ws` (M10): a bearer token
  in the `token` query parameter must belong to the session (participant bound
  to it / host owning it); typed events fan out via the in-process
  `RealtimeHub`. `get_current_host`, `get_current_participant`, and
  `get_host_or_participant` dependencies enforce bearer tokens; ownership/session
  binding is enforced in services/endpoints (cross-owner → 404, D29). Business
  endpoints use the `/api/v1` base path (D26); health stays at the root.
- **Realtime (M10):** `app/realtime/hub.py` is an in-process, per-worker
  broadcast hub (no Redis, D9/D42) keyed by session id. REST routes broadcast
  after a domain change commits: `QueueUpdated` (full authoritative snapshot)
  on submit/cancel/remove/edit, `ParticipantJoined` on join, `SessionUpdated`
  on start/end. Event models live in `app/schemas/realtime.py` (typed, never
  free-form). Clients re-fetch the REST snapshot on reconnect (D5); the
  frontend falls back to polling while the socket is down (B13).
- **Migrations:** Alembic async env wired to application settings; revisions
  `0001_initial` … `0005_queue`. `alembic check` reports no drift.

Rules:

- SQLAlchemy ORM models are separate from Pydantic schemas; explicit mappings.
- Pydantic v2 models at every API/application boundary.
- Pydantic Settings for configuration.
- Python `Enum` types for domain states.
- `UUID`, `datetime`, `timedelta` instead of strings for typed values.
- Explicit type hints everywhere; static type check (pyright/mypy) must pass.

## 4. Frontend structure

Implement at M9/M9.1 (design system via the `frontend-ui` skill; all screens
use token-driven styles from `src/index.css`); the host dashboard lands at M9:

```text
frontend/
    src/
        api/       # typed API client (client.ts, types.ts, session.ts, entries.ts, host.ts)
        ws/        # typed WebSocket client (M10)
        features/
            join/       # QR join flow (JoinScreen)
            submit/     # song submission (SubmitSongScreen)
            queue/      # participant queue view (QueueScreen)
            host/       # host dashboard (HostAuthScreen, HostHomeScreen,
                        # HostDashboardScreen + YouTubePlayer (M12))
        app/       # routing, providers
        components/
        lib/       # shared utilities (token/hostToken persistence, formatting, session labels)
    public/        # manifest, icons, service worker
```

Frontend rules (all in effect at M8/M9/M9.1, updated by D53):

- Never store authoritative state; treat API responses as the source of truth.
  The only durable client-side persistence is participant identity
  (token/session), host identity (token/email), and a non-authoritative YouTube
  metadata cache in localStorage (D38/D39/E8/D53). The frontend may keep a
  temporary optimistic queue/snapshot overlay for instant adds, playback,
  moderation, and cancellation, but it is reconciled by the next authoritative
  REST/WebSocket snapshot and never decides order, position, rounds, playback,
  permissions, or persistence.
- The `frontend-ui` skill (`.opencode/skills/frontend-ui/SKILL.md`) is the
  frontend quality bar: design tokens (CSS variables in `src/index.css`), the
  two-surface layout rules (mobile-first participant vs projector/TV host),
  component patterns, and accessibility. The coder loads it for frontend work;
  the reviewer loads it for frontend reviews (M9.1).
- Reuse API types/schemas generated from backend Pydantic contracts where
  possible — `src/api/types.ts` mirrors the backend schemas by hand and the API
  client (`src/api/client.ts`) is a typed fetch wrapper.
- Mobile-first participant UI (large touch targets ≥ 44px); the host dashboard
  is designed for a projector/TV (large text, high contrast, minimal scrolling
  for current/next) (M9).
- Standard PWA (manifest + service worker) planned for M19.
- Realtime is a delivery mechanism only (D5): since M10, the queue screen and
  host dashboard subscribe to the session's WebSocket channel
  (`src/ws/client.ts` + `src/ws/useRealtime.ts`) and only fall back to polling
  the authoritative snapshot every 5 s while the socket is down (B13/D42).
  Reconnecting clients re-fetch from the REST API (D5).

## 5. Data flow (target state)

```text
Participant phone                   Host browser
     |                                   |
     | keyless oEmbed title/thumb       | host action (skip/remove/...)
     | optimistic local row/cancel      | optimistic snapshot patch
     | background submit/cancel         | background mutation
     v                                   v
Backend (validates/authorizes mutation and persists authoritative state)
     |
     | persists to PostgreSQL
     v
Backend publishes WebSocket events (QueueUpdated, SingerStarted, ...)
     |                                   |
     v                                   v
Participant phone updates            Host dashboard updates
```

Realtime is a notification channel. If it fails, participants can still reload and
get correct state from the API. Optimistic client predictions are temporary UI
only: the next REST/WebSocket snapshot replaces them, and failed mutations clear
the overlay and revert to the last authoritative snapshot (D54).

## 6. Playback architecture (target)

- Playback state machine lives in the backend (`IDLE -> PREPARING -> COUNTDOWN ->
  PLAYING -> COOLDOWN -> ...`), with explicit transitions.
- The host browser renders the YouTube embedded player and reports player events
  (started, ended, errors) back to the backend.
- Automatic advancement is the normal path and is fully configurable per session
  (e.g., post-song cooldown 10s, next-singer countdown 20s). The host can override
  at any time.
- Browser autoplay policies mean the host must interact with the page before audio
  playback; the UI must be designed around this.

## 7. Milestone phases (architecture growth)

- **M0** — repository + documentation (complete).
- **M2** — backend skeleton (complete): FastAPI app factory, async SQLAlchemy 2.x +
  asyncpg, PostgreSQL, Alembic, Pydantic Settings, structured JSON logging,
  readiness health endpoint, project layers.
- **M3** — host authentication (complete): email/password registration/login,
  bcrypt password hashing, opaque revocable bearer tokens (hashed at rest), logout,
  `/api/v1` base path confirmed, `Host` + `HostAuthToken` tables.
- **M4** — karaoke session creation (complete): host-owned sessions
  (create/get/start/end), `SessionStatus` domain state machine, unique join codes,
  derived join URLs, `Session` table.
- **M5** — public QR join flow (complete): public session lookup by join code,
  participant registration (nickname + opaque token), server-side SVG QR of the
  join URL, `Participant` table.
- **M6** — YouTube URL submission + metadata (complete): preview endpoint with
  URL validation, YouTube Data API v3 metadata fetch, configurable long-video
  warnings.
- **M7** — queue management (complete): authoritative queue engine
  (`QueueEntry`/`YouTubeVideo`/`Round` tables), submit + snapshot with computed
  positions, participant cancel, host remove/edit.
- **M8** — participant queue UI (complete, frontend): join/submit/queue screens,
  typed API client, localStorage identity, snapshot polling.
- **M9** — host dashboard (complete, frontend): host auth + home (session list,
  create) + dashboard (now/next cards, full queue, QR/join code, start/remove/
  edit/end actions; skip/finish/pause/resume rendered disabled until M11).
- **M9.1** — frontend UI polish (complete, frontend): `frontend-ui` skill
  (design system, two-surface rules, components, accessibility) + all screens
  refactored onto token-driven styles.
- **M10** — realtime updates (complete): FastAPI WebSocket channel
  (`/api/v1/sessions/{id}/ws`, token query param, D42), in-process
  `RealtimeHub` fan-out, typed events (`QueueUpdated` full snapshot /
  `ParticipantJoined` / `SessionUpdated`), and frontend subscription with
  fallback polling while disconnected (B13).
- **M10.1** — queue rounds + auto-advance (complete): round-robin queue — one
  song per participant per round, stable participant order, derived active round
  that auto-advances, `ROUND_COMPLETE`/enrollment removed, per-participant cap
  (default 5, configurable) (D43–D45). No schema migration: entries were already
  round-scoped; ordering/round-assignment/limit logic changed in the queue
  service. `QueueUpdated` snapshots carry `round_number`.
- **M11** — playback state machine (complete): host-driven playback endpoints
  (`/api/v1/sessions/{id}/play/start|skip|finish|pause|resume`) promote entries
  through `WAITING → SINGING → COMPLETED/SKIPPED` (+ `NEXT` on advance); playback
  state is derived (`PLAYING` iff `SINGING`, D46); `PAUSED` becomes reachable;
  `SingerStarted`/`SingerFinished`/`SingerSkipped` realtime events.
- **M12** — YouTube host player (complete, frontend): the host dashboard embeds
  the YouTube IFrame player (`src/features/host/YouTubePlayer.tsx`); it plays the
  `SINGING` entry's video on the host device (D4), reports completion back via
  the M11 `finish` endpoint, and surfaces player errors (E5/E24). The IFrame API
  loads at runtime; `src/youtube.d.ts` types the YT surface.
- **M13** — automatic song transitions (complete): sessions store the playback
  state + authoritative `transition_until` deadline + per-session timings
  (defaults 10/20, migration `0006`, D47). `play/end` → COOLDOWN → COUNTDOWN →
  auto-start via the idempotent `play/advance` (no background timers; the
  dashboard counts down and advances); skip/finish skip the cooldown (D20);
  pause cancels a pending transition.
- **M14** — host moderation + manual controls (complete): the host authority
  surface is live — removing the current `SINGING` entry advances playback
  (promote next → `NEXT` → countdown transition, E6), removing an already-
  terminal entry is a no-op (E21); skip/finish/pause/resume/edit/end all wired
  from earlier milestones.
- **M15** — next-singer notifications (complete): a typed `NextSingerNotified`
  realtime event (phase `next`/`countdown`, PRODUCT_SPEC §11) is broadcast when
  an entry is promoted to `NEXT` and when the countdown begins; the participant
  queue screen renders a filtered auto-dismissing banner. Web Push deferred to
  the PWA milestone (M19).
- **M16** — round lifecycle cleanup + summaries (complete): absent-participant
  cleanup via `participants.last_connected_at` (join + realtime connect) with a
  lazy GC-on-render pass (D48, migration `0007`); snapshot `rounds_completed` +
  per-participant `remaining_songs`; host-only `GET /sessions/{id}/summary`.
- **M17** — security + abuse protection (complete): in-process fixed-window
  per-IP rate limits (`app/core/ratelimit.py`, D49) on join/preview/submit
  (429), a YouTube metadata TTL cache protecting the Data API quota, and a
  documented session-retention strategy.
- **M18** — testing + failure scenarios (complete): concurrency/failure test
  matrix (rapid-submission determinism, find-or-create races, single-transition
  guarantees, E21 both directions, reconnect recovery) in `tests/test_concurrency.py`.
- **M19** — PWA + mobile UX.
- **M17–M19** — security, testing, PWA/mobile UX.
- **M20–M22** — deployment, pilot, fixes.

## 8. Deployment (target)

- Docker Compose: frontend, backend, PostgreSQL.
- Reverse proxy terminates HTTPS (Caddy or Nginx).
- Environment variables/secrets for DB credentials, auth secrets, YouTube API
  credentials (if required), Web Push credentials, production URLs.
- Health checks, basic logging, restart policy, database backups.
- No Kubernetes unless a real operational requirement appears.
