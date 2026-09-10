# DECISIONS.md — Friday Karaoke

Architectural and product decisions, with rationale. Each entry records what was
decided, why, and (where relevant) the rejected alternatives. New decisions should
be appended as the project evolves.

---

## D1. Modular monolith backend

- **Status:** Accepted (v1)
- **Decision:** One FastAPI backend application. No microservices, Kafka, RabbitMQ,
  Kubernetes, CQRS, or event sourcing.
- **Rationale:** A single school karaoke night is a small, mostly single-host
  workload. Distributed infrastructure adds operational cost without solving a real
  problem. The backend is layered internally (api/core/domain/services/repositories)
  so it can be split later if a concrete requirement appears.
- **Rejected:** Microservices from day one; event sourcing; message broker.

## D2. Backend is the single source of truth

- **Status:** Accepted
- **Decision:** The backend/database is authoritative for queue order, current
  singer, round state, playback state, permissions, participant identity, and
  session state. The frontend renders state and never owns it.
- **Rationale:** Multiple participants + one host + flaky school WiFi means clients
  must be able to resync from a trusted source. This also keeps the client simple.
- **Rejected:** Client-owned or locally-merged queue state.

## D3. Host is the final authority

- **Status:** Accepted
- **Decision:** Normal operation is automated, but the host can always remove entries,
  edit YouTube URLs, skip singers, pause/resume, manually advance, and end the session.
- **Rationale:** The host is responsible for what happens in the room. Automation
  reduces their workload but must never block recovery from a bad submission
  (e.g., a 3-hour podcast).

## D4. Host browser is the playback device

- **Status:** Accepted
- **Decision:** The host dashboard embeds the YouTube player and is connected to the
  school's screen/speakers. Participant devices never play audio.
- **Rationale:** Avoiding cross-device playback synchronization entirely. Also means
  participants' phones are only used for queueing.
- **Implication:** Browser autoplay policies may require host interaction before
  audio starts; the UI must be designed around this (M12/M13).

## D5. WebSockets are delivery, not truth

- **Status:** Accepted
- **Decision:** FastAPI WebSockets push typed domain events to clients. Reconnecting
  clients must re-fetch authoritative state from the REST API.
- **Rationale:** Events are denormalized notifications; the authoritative source is
  the database. This makes realtime failures survivable and avoids distributed-state
  bugs.

## D6. Participants are session-scoped identities, not accounts

- **Status:** Accepted
- **Decision:** Hosts have accounts; participants only get a session-scoped identity
  (nickname + opaque token) created when they join a session.
- **Rationale:** Students join by scanning a QR code; requiring accounts would destroy
  the intended UX. Privacy is also improved.

## D7. Do not over-validate YouTube content

- **Status:** Accepted
- **Decision:** Validate that a submitted URL is a supported YouTube URL, extract the
  video ID, fetch metadata where possible, and warn about unusually long videos.
  Never automatically reject for length; do not assume a video is a karaoke track.
- **Rationale:** The host decides whether a submitted video is appropriate. The app
  should make bad submissions recoverable (host edit) rather than blocking valid ones.
- **Rejected:** Auto-rejecting videos over some duration; requiring karaoke-track
  detection.

## D8. Queue order by creation, not position fields

- **Status:** Accepted (partly superseded at M10.1 by D43)
- **Decision:** Queue ordering is derived from entry creation/order in authoritative
  backend state. No mutable `position` field.
- **Rationale:** Eliminates a whole class of ordering bugs (two participants
  incrementing the same counter, reorder races). Position is computed when rendered.
- **M10.1 revision (D43):** the queue is now round-robin — one song per participant
  per round, ordered within a round by each participant's *earliest* submission
  time (stable participant order). Creation order remains the source of the stable
  order and the within-round tie-break; it no longer *directly* orders the queue.

## D9. Redis not required for first deployment

- **Status:** Accepted
- **Decision:** No Redis in the initial architecture.
- **Rationale:** Requirements (queue, session state, realtime fan-out) are served by
  PostgreSQL + FastAPI for the expected scale of one Friday night. Add Redis only if
  a concrete requirement (e.g., cross-process fan-out) appears.

## D10. Session contains multiple rounds

- **Status:** Accepted
- **Decision:** A Session contains multiple Rounds. A new session (and new QR code)
  is NOT created for each round.
- **Rationale:** Students scan once and stay for the whole night; rounds are a
  within-session lifecycle concept.

## D11. Default next-round answer is YES

- **Status:** Superseded at M10.1 by D44
- **Decision:** At round completion, participants are asked whether they want the next
  round. If they do nothing, the answer is YES.
- **Rationale:** The karaoke night flows with minimal friction; someone who wants out
  must explicitly say NO. (Disconnected participants get a cleanup strategy later.)
- **M10.1 note:** removed entirely — rounds auto-advance with no enrollment prompt;
  a participant opts out by cancelling their remaining songs (D44).

## D12. Tooling choices

- **Status:** Accepted
- **Decision:** uv for dependency management; Pydantic v2 for validation/settings;
  SQLAlchemy 2.x + Alembic; Uvicorn; pytest; pyright for static typing.
- **Rationale:** Plan §1.7 specifies this stack. Pyright selected for static checking
  (strong typing, easy CI integration).
- **Rejected:** Poetry (fine, but uv is faster/simpler for this project).

## D13. Project brain documents (M0)

- **Status:** Accepted
- **Decision:** The repository carries `PROJECT_BRAIN.md`, `DEV_BRAIN.md`,
  `ARCHITECTURE.md`, `DOMAIN_MODEL.md`, `API_CONTRACT.md`, `DECISIONS.md`, and
  `RUNBOOK.md` under `docs/`.
- **Rationale:** A new coding agent must understand the project without the original
  conversation. These documents persist the context and are updated per milestone.

---

## M1 behavioral decisions (product specification)

These freeze MVP product behavior. They were captured in `docs/PRODUCT_SPEC.md`.

### D14. Frozen product specification document (M1)

- **Status:** Accepted
- **Decision:** `docs/PRODUCT_SPEC.md` is the single behavioral contract for the
  MVP: roles/authority matrix, session and round lifecycles, detailed host and
  participant flows, screen inventory, edge-case catalog, normative behavioral
  rules, and playback/automation behavior.
- **Rationale:** plan.md §M1 requires the flows and business rules to be documented
  clearly enough that another developer can implement them without guessing. One
  canonical document avoids drift between flows/edge cases/rules.

### D15. Duplicate songs are allowed

- **Status:** Accepted
- **Decision:** Two participants may queue the same video. The submitter sees an
  informational notice ("This song is already in the queue") but the entry is never
  blocked.
- **Rationale:** Consistent with "do not over-validate" (D7) — each participant
  queues their own song; blocking duplicates adds friction without a real need.

### D16. Nickname rules

- **Status:** Accepted
- **Decision:** Nicknames are required, trimmed, 1–20 characters, and unique per
  session (case-insensitive). Violations block submission with a clear message.
- **Rationale:** Uniqueness avoids ambiguity on the host dashboard ("two Emmas")
  without requiring participant accounts. Length limits support M17 abuse protection.

### D17. Active-entry limit per participant

- **Status:** Superseded at M10.1 by D45
- **Decision:** A participant may have at most **2 non-terminal entries**
  (WAITING + NEXT + SINGING) in the current round. Further submissions are
  rejected with a clear message.
- **Rationale:** plan.md §M7 requires a reasonable active-entry limit. A concrete
  number avoids implementer guessing; enforcement is hardened in M17.
- **M10.1 note:** replaced by a per-participant **total** song cap across all
  rounds (default 5, configurable) once multiple rounds per participant became the
  model (D45).

### D18. Sessions are not tied to a live browser connection

- **Status:** Accepted
- **Decision:** Closing the host's browser (or losing connectivity) does not end or
  pause the session. The session persists in the backend; the host reopens the
  dashboard and re-syncs.
- **Rationale:** Host machines/browsers crash; the backend is the source of truth
  (D2). Tying session lifetime to a socket would make the whole night fragile.

### D19. Round transition behavior

- **Status:** Superseded at M10.1 by D43/D44
- **Decision:** A round completes when the queue has no remaining non-terminal
  entries. The session enters `ROUND_COMPLETE`, the enrollment prompt opens
  (default YES, explicit NO excludes), and the host starts the next round or ends
  the session. Next-round queue order is deterministic: explicit YES answers in
  arrival order, then default-YES participants in creation order, resolved at round
  start.
- **Rationale:** Deterministic, backend-computed ordering avoids races (E19) and
  gives participants an immediate position in the new round.
- **M10.1 note:** enrollment is gone (D44). A round completes when its queue is
  exhausted and the session advances automatically to the next round that has
  entries; the next round's order is the stable participant order (D43).

### D20. Skip vs. manually advance

- **Status:** Accepted (partly revised by the queue-revision note below)
- **Decision:** "Skip" marks the current entry `SKIPPED` and advances immediately;
  "manually advance" marks it `COMPLETED` and advances immediately. Both bypass
  remaining automation. "Pause" holds automation after the current song.
- **Rationale:** Gives the host two distinct, meaningful actions (singer cut short
  vs. singer done early) while keeping the state machine simple and explicit.
- **Queue-revision note (post-M18):** "Skip" no longer marks the current entry
  `SKIPPED`. It moves the singer to the **end of the current round** (a re-chance
  for an absent singer; each further skip keeps them at the back); the singer is
  marked `SKIPPED` only when they are the **only** non-terminal entry left in the
  round, so the round can complete. "Finish"/manually advance still marks
  `COMPLETED` and advances.

---

## M2 backend-skeleton decisions

## D21. Async SQLAlchemy + asyncpg

- **Status:** Accepted
- **Decision:** The database layer uses SQLAlchemy 2.x with the asyncio extension
  and `asyncpg` as the PostgreSQL driver. Sessions are exposed to endpoints through
  a single FastAPI dependency (`app.core.database.get_session`).
- **Rationale:** FastAPI is async-first; blocking the event loop with sync DB calls
  would degrade the realtime features coming in M10+. Async SQLAlchemy is the
  standard, well-supported FastAPI pattern.
- **Rejected:** Sync SQLAlchemy + psycopg2 (simpler but blocks the loop); raw
  asyncpg without an ORM (loses Alembic/metadata tooling).

## D22. Self-contained test database

- **Status:** Accepted
- **Decision:** The automated test suite runs against in-memory SQLite
  (`sqlite+aiosqlite://` with a static pool), configured via the same
  `KARAOKE_DATABASE_URL` settings path. No PostgreSQL is required to run `pytest`.
- **Rationale:** Fresh clones and CI should not require Docker/Postgres to verify
  the skeleton. The engine is built from settings, so the same code path is
  exercised; PostgreSQL is verified manually via the dev compose file and Alembic.
- **Caveat:** SQLite-specific quirks must be watched in M4+ when real models land
  (Postgres-specific types such as UUID/JSONB may need dialect handling).

## D23. Development PostgreSQL via Docker Compose

- **Status:** Accepted
- **Decision:** A root `compose.yaml` provides a Postgres 17 service for local
  development (`docker compose up -d db`). Full production deployment compose
  (frontend + backend + db + reverse proxy) is M20.
- **Rationale:** Local Postgres parity for migrations and manual testing without
  installing a server on the host machine.
- **Rejected:** Testcontainers in the default suite (adds Docker coupling to every
  test run); requiring a locally installed Postgres.

## D24. Structured logging with stdlib JSON formatter

- **Status:** Accepted
- **Decision:** Logging is configured at startup via `app.core.logging` using the
  standard library with a JSON formatter (single-line records to stdout), covering
  the root and uvicorn loggers.
- **Rationale:** Machine-parseable logs for the M20 deployment without adding a
  logging dependency (structlog etc.).
- **Rejected:** structlog (extra dependency, no M2 need); plain text logs
  (unstructured).

---

## M3 host-auth decisions

## D25. Opaque database-backed bearer tokens (hashed at rest)

- **Status:** Accepted
- **Decision:** Hosts authenticate with email/password. Successful login issues an
  opaque random bearer token (`secrets.token_urlsafe`), returned to the client once
  in the login response and sent as `Authorization: Bearer <token>`. Only a SHA-256
  digest of the token is stored (`host_auth_tokens`); the raw token is never
  persisted. Tokens expire (default 30 days, `KARAOKE_AUTH_TOKEN_TTL_DAYS`) and
  logout revokes them by deleting the row. Passwords are bcrypt-hashed
  (`app.core.security`). Emails are stored lowercase; the unique constraint gives
  case-insensitive uniqueness.
- **Rationale:** A real logout and per-token revocation require server-side token
  state; PostgreSQL is already the source of truth (D2). Hashing tokens at rest
  means a database leak does not leak usable credentials. Opaque tokens avoid JWT
  signing-secret management and avoid cookies/CSRF surface in the SPA.
- **Rejected:** JWT (revocation needs a blacklist; signing secret management);
  cookie-based sessions (CSRF considerations, extra cookie handling, no benefit
  here); storing raw tokens in the database (usable on leak); school SSO (no
  identity provider available at the school for v1).

## D26. API base path confirmed: `/api/v1`

- **Status:** Accepted
- **Decision:** Business endpoints live under `/api/v1` (e.g.
  `/api/v1/auth/host/...`). The liveness/readiness endpoints stay at the root
  (`/`, `/health`, `/health/ready`) as they did in M0/M2.
- **Rationale:** `API_CONTRACT.md` deferred the base-path decision to "the first
  real endpoint". M3 is that milestone; a versioned prefix keeps future breaking
  changes manageable without touching operational health checks.
- **Rejected:** Putting auth endpoints at the root alongside the health checks
  (mixed namespacing); `/api` without a version (no upgrade path).

---

## M4 session-creation decisions

## D27. Join codes: short, unambiguous, unique

- **Status:** Accepted
- **Decision:** Every session gets a 6-character uppercase join code drawn from
  the alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `0`/`O`/`1`/`I`). Codes are
  unique per session (unique index on `sessions.join_code`) and are generated with
  a pre-check + bounded retry (10 attempts) before inserting.
- **Rationale:** A school night has dozens of sessions at most, so 32^6
  combinations make collisions effectively impossible; the pre-check plus the
  unique index is a belt-and-suspenders approach. Excluding confusable characters
  means a student can read the code off a projector or type it reliably. Uppercase
  avoids case-sensitivity confusion (M5 lookup uppercases input).
- **Rejected:** Lowercase/mixed-case codes (case confusion); 4-character codes
  (too few combinations); storing a full random UUID as the join code (too long to
  type).

## D28. Join URL is derived, not stored

- **Status:** Accepted
- **Decision:** The session response includes `join_url =
  {KARAOKE_PUBLIC_BASE_URL}/join/{join_code}`. Only the join code is persisted;
  the URL is computed at the API boundary from the new
  `KARAOKE_PUBLIC_BASE_URL` setting (default `http://localhost:5173`, the Vite
  dev server; set to the deployed frontend in production).
- **Rationale:** The frontend host is deployment-dependent and can change
  without invalidating session data; storing it would go stale. The join code is
  the stable, authoritative identifier — the QR (M5) simply encodes the derived
  URL.
- **Rejected:** Storing `join_url` in the database (redundant, goes stale);
  hard-coding the frontend origin (breaks prod).

## D29. Session ownership + strict state machine

- **Status:** Accepted
- **Decision:** Session endpoints require a host bearer token
  (`get_current_host`, M3) and are scoped to the **owning host**:
  `GET/start/end` on a session that does not exist *or* belongs to another host
  returns `404 session not found` (indistinguishable on purpose). State
  transitions are enforced server-side by the `SessionStatus` state machine
  (`app.domain.session`): `start` only from `CREATED`, `end` from any
  non-terminal state; invalid transitions return `409`.
- **Rationale:** M3's acceptance criterion "another host cannot modify someone
  else's session" needs an enforcement point — 404 avoids leaking that a session
  exists. The state machine makes the documented lifecycle
  (`CREATED -> ACTIVE <-> PAUSED -> ROUND_COMPLETE -> ENDED`) explicit and
  testable, and prevents double-start/double-end corruption.
- **Rejected:** Returning `403` for another host's session (leaks existence);
  idempotent no-op on already-ended sessions (masks state bugs).

## D30. FastAPI 0.141.1 dependency-name collision (bug workaround)

- **Status:** Accepted (workaround for an upstream bug)
- **Decision:** Endpoint functions must never share a `__name__` with a
  dependency function. In M4 the GET endpoint was initially named `get_session`,
  colliding with the `app.core.database.get_session` dependency; on routes with a
  literal suffix after a path parameter (`POST /sessions/{id}/start` and
  `/end`), FastAPI 0.141.1 then invoked the *endpoint* instead of the dependency
  and injected a constructed response-model instance into the dependency
  parameter (500/AttributeError). The endpoint is named `session_detail`.
- **Rationale:** 0.141.1 is the latest FastAPI and the project already depends on
  it (M2/M3 used the same version); no upstream fix is released. The workaround is
  a naming convention — zero API-contract impact (the path is unchanged) and no
  dependency downgrade. Verified with a minimal repro before applying.
- **Rejected:** Downgrading FastAPI (risky project-wide change for a naming
  nit); changing the API contract to avoid `/{id}/start` paths (breaks the frozen
  contract).

---

## M5 public-join-flow decisions

## D31. Participant identity: opaque token (hashed) + normalized nickname

- **Status:** Accepted
- **Decision:** Joining creates a session-scoped `participants` row: display
  `nickname` (case preserved) plus a lowercased `nickname_lower` column that
  feeds a `(session_id, nickname_lower)` unique constraint (portable
  case-insensitive uniqueness, B14/D16). The participant's opaque bearer token is
  returned once and stored only as a SHA-256 digest (`token_hash`), reusing the
  M3 token helpers.
- **Rationale:** Participants are anonymous identities, not accounts (D6), so
  there is no login — the token is issued at join time and authorizes later
  participant endpoints (M6+). Hashing the token at rest mirrors D25 (a DB leak
  exposes nothing usable). Normalizing a copy of the nickname keeps display case
  while enforcing case-insensitive uniqueness on both SQLite and PostgreSQL
  without dialect-specific `COLLATE`/`CITEXT` features.
- **Rejected:** Storing the raw participant token (usable on leak); case-sensitive
  nickname uniqueness (allows "Emma" and "emma" to coexist, violating B14);
  dialect-specific case-insensitive columns (breaks the SQLite test suite).

## D32. QR codes are generated server-side as SVG

- **Status:** Accepted
- **Decision:** The backend exposes `GET /api/v1/sessions/{id}/qr` (owning host
  only, D29) returning an SVG QR code (via the pure-Python `segno` library) that
  encodes the session's join URL (`{KARAOKE_PUBLIC_BASE_URL}/join/{code}`, D28).
  The host dashboard (M9) renders this image on the projector; the QR never
  changes for the session's lifetime (PRODUCT_SPEC §3).
- **Rationale:** The plan's M5 "QR generation/display" task is split: generation
  is a deterministic backend capability (testable in M5), display is the frontend
  dashboard's job (M9). SVG scales crisply on a projector and needs no image
  encoding dependency (unlike PNG, which would require Pillow/pypng).
- **Rejected:** Client-side QR generation (duplicates logic across the stack,
  untestable in the backend suite); PNG (extra dependency, no projector benefit
  over SVG).

---

## M6 YouTube-metadata decisions

## D33. Metadata source: YouTube Data API v3 (not oEmbed)

- **Status:** Accepted
- **Decision:** Song previews fetch metadata (title, channel, duration,
  thumbnail) from the **YouTube Data API v3**
  (`videos?part=snippet,contentDetails`) using `KARAOKE_YOUTUBE_API_KEY`. The
  key is required for real use; when it is unset the preview endpoint returns
  503 with a clear message. The fetch is injected with an `httpx.AsyncClient`
  so the test suite uses a mock transport (no network, no key).
- **Rationale:** The preview and the long-video warning (D34) require
  **duration**, which the keyless oEmbed endpoint does not provide. The Data
  API is Google's sanctioned, stable interface — no scraping the watch page.
  The API key is a one-time free Google Cloud setup and was already anticipated
  for deployment (PROJECT_BRAIN §M20 "YouTube API credentials if required").
- **Rejected:** oEmbed alone (no duration — cannot warn on long videos or show
  durations on the host dashboard); watch-page scraping (fragile, against the
  spirit of a maintained contract); a third-party oEmbed proxy (same duration
  gap, adds an external dependency).

## D34. Long-video warning threshold (configurable, never a rejection)

- **Status:** Accepted
- **Decision:** A video longer than `KARAOKE_YOUTUBE_LONG_VIDEO_SECONDS`
  (default 600 s = 10 min) gets `is_long: true` and a human-readable warning in
  the preview. The video is **never** rejected for length (rule B6, D7).
- **Rationale:** Karaoke tracks are typically a few minutes; a 10+ minute video
  is usually not a karaoke track, but the host has final authority (D3) and may
  accept it (e.g., a longer version). Making the threshold configurable avoids
  re-deploys when the school decides what "unusual" means.
- **Rejected:** Hard-coding a threshold (must re-deploy to change); auto-rejecting
  long videos (violates B6); warning only above a much larger fixed value (e.g.,
  30 min) which would miss 12-minute non-tracks.

---

## M7 queue-engine decisions

## D35. Rounds exist from session creation; queue entries are round-scoped

- **Status:** Accepted
- **Decision:** A `rounds` table exists with a unique `(session_id, number)`
  constraint. Round 1 is created in the same transaction as the session
  (SessionService.create). Every `QueueEntry` carries `round_id` and the active
  queue/positions/limits are scoped to the session's latest round.
- **Rationale:** The domain model (D10) and PRODUCT_SPEC §6.5 ("creates the queue
  entry in the active round") require entries to live in a round, and the
  active-entry limit (B15/D17) is per-round. Creating round 1 eagerly keeps the
  FK invariant (`round_id` is never null) and makes M16's "start next round"
  just insert round N+1.
- **Rejected:** Omitting rounds until M16 (would leave `round_id` nullable or
  drop the documented field); auto-creating round 1 lazily on first submit
  (asymmetric — a session with no submissions has no round).
- **M10.1 note (D43):** round 1 is still created with the session; later rounds
  are created lazily when the first entry is assigned to them. The active
  round is the *lowest-numbered* round with a non-terminal entry (not the
  latest), and advances automatically.

## D36. Deterministic queue ordering: microsecond `created_at` + `id` tie-break

- **Status:** Accepted
- **Decision:** Queue order is `ORDER BY created_at, id`. `created_at` is
  assigned in Python (`datetime.now(timezone.utc)`, microsecond precision) rather
  than by the database default.
- **Rationale:** SQLite's `CURRENT_TIMESTAMP` is second-precision, so two
  submissions in the same second tie and a random-UUID tie-break scrambles
  insertion order (caught by the M7 ordering test). A microsecond Python
  timestamp preserves insertion order on SQLite tests and PostgreSQL alike;
  `id` remains as a deterministic (if arbitrary) tie-break for the vanishingly
  rare same-instant case (E19 requires determinism, not client-clock order).
- **Rejected:** Relying on `server_default now()` (ties on SQLite); an integer
  autoincrement PK (deviates from the UUID-keyed domain model); a per-session
  counter (concurrency-racy without a sequence).

## D37. YouTubeVideo is a shared metadata row; DELETE /entries/{id} is dual-actor

- **Status:** Accepted
- **Decision:** (1) `youtube_videos` holds one immutable metadata row per unique
  video id (unique index on `youtube_video_id`); duplicate-song submissions and
  host URL edits find-or-create it (race-safe via the unique constraint), so
  duplicate songs share the metadata snapshot. (2) `DELETE /api/v1/entries/{id}`
  accepts either a participant or a host token (a `get_host_or_participant`
  dependency): participants cancel their own WAITING entry (→ `CANCELLED`, 409
  otherwise), hosts remove any entry (→ `REMOVED`).
- **Rationale:** (1) Matches "A QueueEntry references exactly one YouTubeVideo"
  while keeping metadata storage normalized (B16 allows duplicates — they share
  the row). (2) The API contract defines a single path for both actions; the
  actor type cleanly disambiguates the behavior without leaking existence
  (foreign entries/sessions → 404).
- **Rejected:** A `youtube_videos` row per queue entry (duplicate storage, no
  unique-key benefit); two endpoints for cancel vs remove (breaks the documented
  contract).

---

## M8 participant-UI decisions

## D38. Participant identity lives in localStorage; snapshots are polled until M10

- **Status:** Accepted
- **Decision:** (1) The participant's identity (opaque token, session id/name,
  join code, nickname) is persisted in `localStorage` under one key; refreshing
  or revisiting `/join/{code}` resumes the queue without re-joining (E8). (2) The
  queue screen polls the public snapshot endpoint every 5 s until the WebSocket
  channel lands in M10.
- **Rationale:** (1) PRODUCT_SPEC E8 requires nothing to be lost on refresh; the
  token is a session-scoped secret by design (D31), and localStorage is the
  standard place for a bearer token in an SPA. (2) Real-time push is M10; polling
  the authoritative snapshot keeps this milestone simple and correct — the
  frontend never synthesizes state.
- **Rejected:** Cookies for the participant token (extra CSRF surface, no benefit
  for a bearer-token SPA); a frontend state store that merges/owns queue state
  (violates D2); relying on realtime events before M10.

---

## M9 host-dashboard decisions

## D39. Host dashboard: session list endpoint + host identity in localStorage

- **Status:** Accepted
- **Decision:** (1) A new `GET /api/v1/sessions` endpoint returns the
  authenticated host's sessions, newest first (`SessionService.list_for_host`,
  ordered `(created_at, id)` desc — a D36-style stable tie-break, since
  `sessions.created_at` is a second-precision server default). (2) The host's
  identity (bearer token, email, host id) is persisted in `localStorage` under
  one key (mirroring D38), so reopening the dashboard resumes the session list
  without re-logging in (E11).
- **Rationale:** (1) The M9 home screen needs to show the host's sessions and let
  the host re-sync after reopening the dashboard (E11); without a list endpoint
  the host would have to remember a UUID. The endpoint reuses the existing
  `get_for_host` ownership model — no cross-host leakage. (2) Same rationale as
  D38: the bearer token is the secret, localStorage is the standard SPA
  placement, and the backend remains authoritative for all state.
- **Rejected:** Storing the session list in localStorage (goes stale; violates
  D2); a paginated/admin-style session list (unnecessary — a host has a handful
  of sessions).

## D40. M9 playback-status actions are not wired to the backend

- **Status:** Accepted
- **Decision:** The M9 host dashboard renders the host action bar (start, skip,
  finish, pause, resume, end session) but only **start**, **remove**, **edit**,
  and **end session** call backend endpoints. Skip / finish / pause / resume are
  rendered disabled with an explanatory tooltip: they require the M11 playback
  state machine and its endpoints, which are not part of M9.
- **Rationale:** The plan (plan.md §M9) lists those actions on the dashboard, but
  the backend has no playback endpoints yet (M11/M14). Silently omitting them
  would under-deliver the documented control surface; wiring them to
  non-existent endpoints would be broken. Disabled controls keep the surface
  honest and visible.
- **Rejected:** Implementing fake playback endpoints in M9 (scope creep into
  M11/M14); hiding the actions entirely (the plan documents them).

---

## M9.1 frontend-UI decisions

## D41. Frontend UI quality bar is a project skill (`frontend-ui`)

- **Status:** Accepted
- **Decision:** The frontend's design system and quality rules live in a
  project skill at `.opencode/skills/frontend-ui/SKILL.md`: design tokens
  (colors/spacing/radius/type scale as CSS variables in `src/index.css`), the
  two-surface layout rules (mobile-first participant vs projector/TV host),
  component patterns, accessibility, and a per-change Definition of Done. The
  coder agent loads the skill for frontend work; the reviewer loads it for
  frontend reviews; `plan.md` gained a "Frontend UI quality bar" section and an
  M9.1 milestone. All screens were refactored onto the token-driven styles
  (M9.1).
- **Rationale:** The frontend is a real user-facing product (student phones +
  a projector host screen), so visual/UX quality is part of every frontend
  milestone's Definition of Done. A skill is loadable by any agent at the right
  moment (unlike a wall of prose in `plan.md`, which agents skim), and keeping
  it out of `AGENTS.md` avoids bloating every prompt.
- **Rejected:** Putting the design system only in `AGENTS.md` (always loaded,
  noisy for backend-only work); relying on ad-hoc "make it look nice" requests
  per milestone (inconsistent, untestable).

---

## M10 realtime decisions

## D42. WebSocket channel: in-process hub + per-session broadcast

- **Status:** Accepted
- **Decision:** One WebSocket endpoint per session —
  `GET /api/v1/sessions/{id}/ws` — with a bearer token passed as the `token`
  query parameter (the browser WebSocket API cannot set request headers). The
  token must belong to the session: a participant token must be bound to it, a
  host token must own it; anything else is rejected before `accept()` (close
  code 1008 / HTTP 403 on the upgrade, no session-existence leak, D29). A
  single in-process `RealtimeHub` (`app/realtime/hub.py`) fans out typed
  events to every subscriber of a session; REST routes broadcast after a domain
  change commits. Events for M10 are `QueueUpdated` (full authoritative queue
  snapshot, emitted on submit/cancel/remove/edit), `ParticipantJoined`
  (join), and `SessionUpdated` (start/end). Singer/round/pause events are NOT
  emitted until their milestones create the producing code paths
  (M11/M13/M14/M16). The hub is in-process and per-worker (no Redis, D9); a
  shared hub is deferred until the backend runs multiple workers.
- **Rationale:** The plan's realtime acceptance criterion is that queue changes
  reach participant phones almost immediately. A per-session fan-out over one
  authenticated socket is the smallest design that does that, matches
  API_CONTRACT §8 (token query param; typed payloads), and keeps the frontend a
  thin renderer (D2). Carrying the full snapshot in `QueueUpdated` means every
  subscriber renders exactly the same authoritative state the REST snapshot
  returns. Reconnecting clients must re-fetch authoritative state (D5), which
  the frontend implements by resuming snapshot polling while the socket is
  down (B13).
- **Rejected:** Unauthenticated sockets (events are the same data as the public
  snapshot, but the contract documents a token and auth keeps a future
  host-only stream possible); Redis pub/sub (D9 — one worker today); publishing
  from services (keeps services pure; routes own the HTTP/socket boundary).

---

## M10.1 queue-round decisions

## D43. Round-robin queue with stable participant order

- **Status:** Accepted (revision of D8/D19)
- **Decision:** Queue entries are round-scoped with at most one non-terminal
  entry per participant per round. Round N holds each participant's N-th song.
  The active queue is the **current round's** entries, ordered by the **stable
  participant order** — each participant's earliest submission time
  (`MIN(created_at)`), fixed once and repeated every round; `created_at` + `id`
  are the deterministic tie-break. The active round is **derived** (the
  lowest-numbered round with ≥ 1 non-terminal entry) and advances automatically
  when it empties. A participant's first song goes into the current round;
  subsequent songs go one round above their highest round. A late joiner's first
  song is appended to the current round.
- **Rationale:** Participants may queue several songs; a flat creation-order
  queue let one participant's 2nd song jump ahead of someone's 1st. Round-robin
  ("everyone's first song, then everyone's second") matches how a hosted karaoke
  night actually runs, keeps the queue fair, and makes "moving to everyone's next
  song" a natural, automatic round transition. Deriving the active round (rather
  than storing a counter) keeps the backend the single source of truth (D2) and
  avoids a mutable-state bug class, consistent with D8's "derive, don't store".
  The stable order is fixed by first engagement so cancelling a song never
  reorders the night.
- **Rejected:** Flat creation-order queueing (unfair interleaving);
  storing the active round number as a mutable session field (drift risk);
  ordering within a round by that round's own submission times (unstable across
  rounds — a participant who submits their 2nd song late would suddenly move
  ahead/behind others in round 2).
- **Queue-revision note (post-M18, real-pilot feedback):** the within-round
  ordering was changed after live testing: it is now **join order** (earliest
  join first, via `participants.created_at` with a microsecond Python default
  for deterministic ties) instead of first-engagement. The host can **re-arrange
  the current round** via `PATCH /api/v1/sessions/{id}/order` — per-round only
  (a `round_orders` table; the next round resets to join order). **Skip moves
  the singer to the end of the round** (`queue_entries.skip_count`; one
  re-chance), and they are excluded only when they are the only non-terminal
  entry left so the round can complete. The round-robin structure, derived
  active round, and per-participant cap are unchanged.

## D44. Rounds auto-advance; no next-round enrollment

- **Status:** Accepted (supersedes D11)
- **Decision:** Rounds advance automatically: when the current round's queue is
  exhausted, the session moves to the next round that has entries — there is no
  `ROUND_COMPLETE` state and no "Join the next round?" prompt. A participant
  opts out by cancelling their remaining songs; participants whose songs run out
  simply do not appear in later rounds.
- **Rationale:** With round-robin ordering (D43), "the next round" is just
  "everyone's next song", so an enrollment step adds friction with no value: a
  participant who already queued songs clearly intends to sing them, and someone
  who wants to stop cancels their own songs (B3). This also removes the
  `ROUND_COMPLETE` session state, simplifying the state machine to
  `CREATED -> ACTIVE <-> PAUSED -> ENDED`.
- **Rejected:** Keeping the M1/M16 enrollment flow (default YES / explicit NO) —
  an extra prompt and state for a decision the queue already encodes;
  a `ROUND_COMPLETE` interstitial without enrollment (dead state, no purpose).

## D45. Per-participant total song cap (configurable)

- **Status:** Accepted (revision of D17)
- **Decision:** A participant may queue at most
  `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT` non-terminal songs **total**, across
  all rounds. Default **5**. Submissions beyond the cap are rejected with a clear
  message; the duplicate-song notice (B16) is unchanged.
- **Rationale:** The old "2 per current round" limit (D17) made no sense once
  one song per round is the rule. A total cap bounds how much of the night one
  participant can reserve (5 matches the planned pilot scale) while staying
  configurable so the school can tune it without a redeploy (mirroring D34's
  configurable threshold).
- **Rejected:** No cap (one participant could clog a whole night);
  keeping 2 (too small now that songs are round-scoped).

---

## M11 playback decisions

## D46. Playback state is derived, not stored; host-driven controls

- **Status:** Superseded at M13 by D47
- **Decision:** The session's playback state is **derived** from queue state —
  `PLAYING` while an entry is `SINGING`, otherwise `IDLE` — and surfaced in the
  queue snapshot (`playback_state`). It is never stored, so it cannot drift from
  the queue. M11 exposes host-only endpoints under
  `/api/v1/sessions/{id}/play/…`: `start` (promote the front of the active queue
  to `SINGING`), `skip` (`SKIPPED` + advance, D20), `finish` (`COMPLETED` +
  advance, D20), `pause` (`ACTIVE -> PAUSED`), `resume` (`PAUSED -> ACTIVE`).
  Advancing promotes the next entry to `NEXT` and, because the active round is
  derived (D43), automatically crosses into the next round. Each endpoint
  returns the authoritative snapshot and broadcasts the matching realtime event
  (`SingerStarted`/`SingerFinished`/`SingerSkipped` plus `QueueUpdated`;
  `SessionUpdated` for pause/resume).
- **Rationale:** The `PlaybackState` enum documents the full lifecycle
  (IDLE/PREPARING/COUNTDOWN/PLAYING/COOLDOWN/FINISHED/SKIPPED), but the
  timer-driven transient states are M13's job. Storing playback state (a column
  that can drift) adds a second source of truth for something the queue already
  encodes — inconsistent with D2/D8. Host-driven controls satisfy M11's
  acceptance criterion (the backend determines the active singer) and enable the
  dashboard's previously-disabled Skip/Finish/Pause/Resume buttons (D40) without
  pre-empting M12 (host player) or M13 (automation timers).
- **Rejected:** A stored `playback_state` column on sessions (drift risk, no
  benefit — the SINGING entry is the state); implementing PREPARING/COUNTDOWN/
  COOLDOWN timing in M11 (that is M13's automatic-transition scope).
- **M13 note (D47):** the derived approach could not express the automatic
  transition phases (nothing is `SINGING` during COOLDOWN/COUNTDOWN), so the
  state is now stored together with authoritative transition deadlines.

---

## M13 automatic-transition decisions

## D47. Stored playback state + authoritative transition deadlines (frontend-driven advance)

- **Status:** Accepted (revision of D46)
- **Decision:** M13 stores the playback state on the session (`playback_state`
  column, default `IDLE`) together with the absolute `transition_until` deadline
  of the current phase and per-session timings (`cooldown_seconds`,
  `countdown_seconds`, defaults 10/20 from settings, PRODUCT_SPEC §10). The
  automatic transition runs `COOLDOWN → COUNTDOWN → auto-start (PLAYING)` after a
  song ends (`play/end`); host `skip`/`finish` skip the cooldown and go straight
  to the countdown (D20). The frontend renders the remaining time from the
  snapshot's `transition_until`/`transition_remaining_seconds` and calls the
  idempotent `play/advance` endpoint when a phase deadline passes; a reopened tab
  sees an overdue deadline and calls `advance` again, so recovery needs no
  background timers.
- **Rationale:** The M11/D46 derived state (`PLAYING` iff an entry is `SINGING`)
  cannot express the transition phases (nothing is singing during the cooldown/
  countdown), so the state must be stored. Keeping the *timing* authoritative in
  the backend (D2) while letting the host dashboard trigger each phase avoids
  fragile per-session background tasks: nothing drifts, nothing leaks across
  restarts, and the clock can be frozen in tests for deterministic coverage. The
  host device is the playback device (D4), so automation only needs to run while
  the dashboard is open anyway.
- **Rejected:** asyncio background tasks per session (restart-fragile, harder to
  test, still need a stored deadline for recovery); client-owned timers with no
  backend deadline (frontend would own authoritative timing, violating D2);
  deriving the transition state from entry statuses (impossible — no entry is
  singing during COOLDOWN/COUNTDOWN).

---

## M16 round-lifecycle decisions

## D48. Absent-participant cleanup via last-connection tracking (lazy, GC-on-render)

- **Status:** Accepted
- **Decision:** Participants carry a `last_connected_at` (set at join and
  refreshed on every realtime connect, migration `0007`). While a session is
  `ACTIVE`/`PAUSED`, participants who have not connected for
  `KARAOKE_ABSENT_PARTICIPANT_CLEANUP_SECONDS` (default 30 min) have their
  remaining `WAITING` entries cancelled. The cleanup runs **lazily whenever the
  authoritative queue snapshot is built** (a garbage-collection-on-render step,
  idempotent and cheap when nobody is stale). Only `WAITING` entries are
  cleaned: an absent `NEXT`/`SINGING` singer is the host's skip call (E2/E6).
  M16 also adds round/participant summaries: `rounds_completed` + per-
  participant `remaining_songs` in the snapshot, and a host-only
  `GET /api/v1/sessions/{id}/summary` endpoint (rounds played + per-participant
  submitted/sung/remaining) for the projector and the end-of-night wrap-up.
- **Rationale:** In the round-robin model an absent singer already cannot block
  the queue indefinitely (the host skips them), so cleanup is hygiene — freeing
  future-round slots of people who left. Tracking last realtime connection is
  the simplest non-invasive presence signal (no new polling), and running the
  cleanup on snapshot render avoids background timers entirely (consistent with
  D47) while guaranteeing the authoritative state never shows ghost entries.
  The write is idempotent and only fires when stale participants exist.
- **Clarification (post-D52):** `last_connected_at = NULL` means the participant
  is not presence-tracked and is therefore not considered absent by this cleanup.
  This is used for host-created/no-phone participants, because they have no
  client WebSocket to refresh presence; QR-created participants still set and
  refresh `last_connected_at` normally.
- **Rejected:** A periodic background sweep task (restart/multi-worker fragility,
  D47 spirit); heartbeat pings from clients (extra protocol); treating absence as
  immediate (network blips would wrongly cancel songs — the window absorbs
  them); cleaning `NEXT`/`SINGING` entries (the host, not automation, handles an
  absent current singer).

---

## M17 security decisions

## D49. In-process rate limiting + YouTube metadata quota cache

- **Status:** Accepted
- **Decision:** M17 adds a small in-process fixed-window rate limiter
  (`app/core/ratelimit.py`, keyed by `<scope>:<client-ip>`, gated by
  `KARAOKE_RATE_LIMITS_ENABLED`) protecting the public QR-code surface:
  `POST /join/{code}/participants` (10/min/IP), `POST /sessions/{id}/entries/
  preview` (20/min/IP) and `POST /sessions/{id}/entries` (20/min/IP) all return
  429 when exceeded. The YouTube service gains an in-process TTL metadata cache
  (`KARAOKE_YOUTUBE_CACHE_TTL_SECONDS`, default 1 h) so repeated previews/
  submissions of the same video cost one Data API call instead of many —
  protecting the free key's daily quota (D33). YouTube quota/rate-limit errors
  are reported distinctly as HTTP 503 instead of being collapsed into the
  user-facing "video unavailable" 404. Sessions are intentionally **retained**
  (no auto-deletion): ENDED is terminal, and a retention/cleanup policy is an
  ops decision for M22, not a v1 feature.
- **Rationale:** The realistic threats to a public QR code are join flooding and
  YouTube quota exhaustion via preview/submit spam; both are cheaply bounded
  in-process (D9 — single worker, no Redis). The existing defenses already
  cover the rest of M17's checklist: Pydantic request validation + input length
  limits, opaque hashed-at-rest tokens (D25/D31), per-session authorization with
  cross-host 404s (D29), YouTube URL validation (D33/D34), and the per-
  participant song cap (D45). CSRF does not apply (bearer headers, not cookies,
  D25). Tests disable the limiter via the environment (conftest) so the suite
  is not coupled to wall-clock windows; the limiter is unit-tested directly and
  an integration test re-enables it to prove the 429 path.
- **Rejected:** A third-party rate-limit dependency (extra dependency, no need);
  Redis-based limiting (D9); a background sweep for session retention (deleting
  data is destructive and unrequested — M22 ops decision); rate limiting the
  public snapshot GET or WebSocket handshake (cheap paths; token-gated WS and
  NAT-shared school IPs make it counterproductive).

---

## Leave-session decision

## D50. Participant leave = hard delete (nickname freed, mid-song advances)

- **Status:** Accepted
- **Decision:** A participant can delete themselves from a session via
  `POST /api/v1/sessions/{id}/leave` (participant token, session-bound). The
  `participants` row is deleted and the existing `ON DELETE CASCADE`
  relationships remove all their queue entries (every round) and any reorder
  rows, so they never appear in later rounds and their **nickname is freed** (a
  later rejoin is a fresh identity with a new token). If they were the current
  `SINGING` singer, playback advances to the next singer (same E6 path as the
  host removing a singer). The token dies with the row, so all further
  participant actions return 401 naturally.
- **Rationale:** "Going home early" should be a clean, final exit. Hard-deleting
  is the simplest mechanism (no departed-flag, no extra blocking logic — a dead
  token is automatically rejected) and naturally frees the nickname per the
  product request. SQLite's foreign-key cascade is enabled for the test suite via
  `PRAGMA foreign_keys=ON` so tests exercise the same cascade PostgreSQL has.
- **Trade-off (accepted):** deleting the row also removes a leaver's already-sung
  songs from the session summary stats. The alternative (a departed flag that
  preserves history but keeps the nickname taken) is more code for little value
  on a school night.
- **Rejected:** keeping a `departed_at` flag (more code; doesn't free the
  nickname); revoking the token in a separate table (a live delete already makes
  the token unresolvable).

## D51. CI/CD auth = service-account key secret, not Workload Identity Federation

- **Status:** Accepted
- **Decision:** The `dev`-branch deploy workflow (`.github/workflows/deploy-dev.yml`)
  authenticates to GCP with the `github-actions-deployer` service-account key,
  stored only as the encrypted `GCP_SA_KEY` GitHub Actions secret (`credentials_json`
  to `google-github-actions/auth@v2`). This replaced the initially-chosen keyless
  Workload Identity Federation (pool `github`, provider `friday-karaoke`, SA
  bindings `workloadIdentityUser` + `serviceAccountTokenCreator`).
- **Rationale:** WIF's impersonated-credentials path kept returning
  `Permission 'iam.serviceAccounts.getAccessToken' denied` on the SA even after
  granting `roles/iam.serviceAccountTokenCreator` to both the `dev` WIF principal
  and the SA itself (verified in the IAM policy, with propagation waited out). After
  several failed runs, we pivoted to a service-account key. This is still secret-
  not-in-repo: the key exists only as an encrypted GitHub Actions secret (never
  committed), same protection as the Neon/YouTube secrets.
- **Trade-off (accepted):** a long-lived service-account key needs rotation instead
  of WIF's ephemeral tokens; the key is still exposed if GitHub is compromised (as
  with any GitHub secret). The WIF pool/provider + bindings were left in place but
  are unused, so we can revisit keyless later.
- **Rejected:** continuing to debug WIF's getAccessToken impersonation (blocked on
  external IAM behavior, multiple failed runs); committing a key to the repo (never).

## D52. Host-assisted participants and queued playlists

- **Status:** Accepted
- **Decision:** Add a separate host participant-management screen and host-only
  endpoints under `/api/v1/sessions/{id}/participants`. The host can list every
  participant with their non-terminal queued playlist, create a participant by
  nickname, and add a YouTube song directly to a participant. The main playback
  dashboard only gains a navigation link so its core control layout remains stable.
- **Rationale:** Friday-night reality includes singers who forgot a phone or do
  not want to use one. The host is already the final authority, and the host's
  browser is the playback device, so letting the host create a session-scoped
  participant and submit songs on their behalf preserves the backend/database as
  the source of truth while avoiding paper/manual queue work.
- **Cleanup rule (revised after live feedback):** Host-created/no-phone
  participants are **not absence-tracked**: `last_connected_at` is stored as
  `NULL`, so lazy absent cleanup leaves their WAITING songs alone. QR-created
  participants still set `last_connected_at` on join and refresh it on realtime
  connect, so normal absent cleanup remains in place for phone participants.
  Rationale: no-phone singers have no WebSocket presence to refresh, and the
  host is explicitly managing them; treating them like disconnected phones made
  host-added songs vanish after the cleanup window.
- **Trade-off (accepted):** the no-phone participant does not receive their raw
  participant token and cannot later manage/cancel their own entries from a phone
  unless they join separately with a different nickname; the host can still remove
  or edit entries from the host surfaces.
- **Rejected:** changing the main dashboard into a large participant-management
  UI; preview-before-add for the host path (extra tap and extra YouTube quota
  call). The earlier rejection of exempting host-created participants from
  absent cleanup was reversed after real-use testing showed it made host-added
  songs disappear.

---

## D53. Optimistic song-add UX with keyless oEmbed metadata

- **Status:** Accepted
- **Decision:** Song-add surfaces use a local-first optimistic UX while preserving
  D2 backend/database authority. The frontend validates/extracts supported
  YouTube IDs, fetches keyless oEmbed metadata directly for instant
  title/channel/thumbnail display when available, stores only non-authoritative
  video metadata in localStorage, and renders temporary `syncing`/`failed` rows
  through a shared queue overlay. Client-side oEmbed is best-effort: if YouTube
  returns 401/404/CORS/network failure, the frontend still shows a generic
  `Song syncing…` optimistic row and lets the backend submit decide. Participant
  submit and host participant add still POST to the backend in the background;
  REST/WebSocket snapshots reconcile the optimistic rows and provide
  authoritative position, round, duplicate notice, playback, and persistence
  state.
- **Backend metadata fallback:** Submit paths normally use the YouTube Data API.
  If quota/rate limits are exhausted, participant submit and host participant add
  fall back to server-side oEmbed metadata and still queue the song with
  `duration_seconds=0`. Preview remains strict because its job is to provide the
  duration-based long-video warning. A later successful Data API fetch refreshes
  a previously oEmbed-only video row with real duration/display metadata.
- **Rationale:** Real school use needs adding songs to feel instant and not fail
  just because the Data API quota is temporarily exhausted. oEmbed is keyless and
  quota-free but lacks duration, so the frontend can use it for fast display while
  the backend retains authority over ordering, rounds, limits, identity, sockets,
  and durable persistence.
- **Rejected:** A truly client-authoritative queue with the backend as a dumb
  relay (would lose refresh/crash durability and create ordering conflicts);
  keeping the blocking Preview -> Add double round-trip; rejecting songs solely
  because duration could not be fetched.

---

## D54. Optimistic playback and moderation snapshot overlay

- **Status:** Accepted
- **Decision:** Host playback/moderation actions and participant cancellation use
  the same temporary optimistic-overlay model as D53. The frontend keeps the last
  authoritative `QueueSnapshot` from REST/WebSocket and may render a predicted
  snapshot immediately for start/end/finish/skip/advance/pause/resume, host
  remove/reorder/edit, session start/end, and participant cancel. The HTTP
  mutation still runs in the background; the next authoritative snapshot replaces
  the optimistic one, and a failed mutation clears the overlay to revert the UI
  and surface an error. Snapshot payloads now expose `cooldown_seconds` and
  `countdown_seconds` so optimistic transition deadlines match per-session
  configuration.
- **Rationale:** During a live performance, a host pressing **Finish** or
  **Skip** needs the projector UI to move immediately even if the school network
  adds latency. This is a UI responsiveness layer only: backend/database remains
  authoritative for queue order, statuses, rounds, playback, permissions,
  identity, and persistence; WebSockets/polling reconcile any prediction drift.
- **Trade-off:** The client mirrors a small part of the playback state machine for
  display, so rare edge cases (round boundaries, another tab acting first, socket
  loss) can briefly differ from the backend. The overlay is intentionally
  temporary and is replaced by REST/WebSocket snapshots or reverted on API
  failure.

---

## Open questions (tracked)

- ~~Authentication mechanism for hosts (email/password vs. school SSO)~~ — **M3
  resolved: email/password + opaque bearer tokens (D25).**
- ~~YouTube metadata source (oEmbed vs. Data API key)~~ — **M6 resolved:
  YouTube Data API v3 (D33).**
- ~~Exact realtime payload schemas~~ — **M10 resolved: typed per-event models
  (`app/schemas/realtime.py`), discriminated by `type` (D42).**
- ~~Web Push service choice~~ — **M15 resolved: M15 is in-app notifications only
  (a typed `NextSingerNotified` realtime event, PRODUCT_SPEC §11). Web Push
  (service worker + VAPID push subscription) is deferred — it needs a service
  worker (PWA, M19) and out-of-band credentials, which the school pilot does not
  require: participants watch the queue screen live.**
