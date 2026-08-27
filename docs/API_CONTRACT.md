# API_CONTRACT.md — Friday Karaoke

Planned API surface for v1. **Status: PARTIALLY IMPLEMENTED.** The health
endpoints (M0/M2) and the host auth endpoints (M3) are live; everything else
is planned and will be implemented milestone by milestone. This document is
updated to reflect reality.

All structured request/response bodies are Pydantic v2 models. Domain states use
Python `Enum` types, never free-form strings. `id`s are UUIDs.

---

## Conventions

- **Base path: `/api/v1`** (confirmed at M3, decision D26) for business
  endpoints. The liveness/readiness endpoints stay at the root (`/`, `/health`,
  `/health/ready`).
- JSON bodies; `application/json`.
- Errors use a consistent shape:

```text
{"detail": "<human-readable message>"}
```

- Auth:
  - Host endpoints require host authentication (M3): an opaque **bearer token**
    sent as `Authorization: Bearer <token>`. Tokens are issued by login,
    revocable by logout, and expire (default 30 days, `KARAOKE_AUTH_TOKEN_TTL_DAYS`).
  - Participant endpoints require the participant's opaque token (M5).
- Responses shown below are target shapes and may evolve.

## 1. Health (M0/M2)

| Method | Path            | Auth | Description                            |
| ------ | --------------- | ---- | -------------------------------------- |
| GET    | /               | none | Service identity (liveness)            |
| GET    | /health         | none | Liveness check                         |
| GET    | /health/ready   | none | Readiness: probes the database (200/503)|

```text
GET /health
200 { "service": "friday-karaoke-backend", "status": "ok", "version": "0.1.0" }

GET /health/ready   (database reachable)
200 { "service": "friday-karaoke-backend", "status": "ok", "version": "0.1.0",
      "components": { "database": "ok" } }

GET /health/ready   (database unreachable)
503 { "detail": "database unavailable" }
```

## 2. Host auth (M3) — IMPLEMENTED

| Method | Path                              | Auth | Description            |
| ------ | --------------------------------- | ---- | ---------------------- |
| POST   | /api/v1/auth/host/register        | none | Create host account    |
| POST   | /api/v1/auth/host/login           | none | Host login             |
| POST   | /api/v1/auth/host/logout          | host | Logout (revoke token)  |
| GET    | /api/v1/auth/host/me              | host | Current host profile   |

```text
POST /api/v1/auth/host/register
{ "email": "host@school.edu", "password": "correct-horse-battery" }

201 {
  "id": "d4c7a99f-...",
  "email": "host@school.edu",      # normalized to lowercase
  "created_at": "2026-08-10T22:43:00.507099Z"
}

409 { "detail": "a host with this email already exists" }
422 { "detail": [...] }              # invalid email / short or overlong password
```

```text
POST /api/v1/auth/host/login
{ "email": "host@school.edu", "password": "correct-horse-battery" }

200 {
  "token": "fr5zCS4nGntz3pAGYIMlfyG0vK-5mWuHeS8xXud8_V4",
  "token_type": "bearer",
  "host": { "id": "d4c7a99f-...", "email": "host@school.edu", "created_at": "..." }
}

401 { "detail": "invalid email or password" }   # unknown email and wrong password
                                                # both return the same message
```

```text
POST /api/v1/auth/host/logout        Authorization: Bearer <token>
204                                   # token revoked; idempotent

GET /api/v1/auth/host/me             Authorization: Bearer <token>
200 { "id": "...", "email": "...", "created_at": "..." }
401 { "detail": "invalid or expired token" }   # missing/expired/unknown token
```

Notes (decision D25): tokens are opaque, random strings. Only their SHA-256
digest is stored; a database leak does not expose usable tokens. Passwords are
bcrypt-hashed. Emails are stored lowercase (case-insensitive uniqueness).

## 3. Sessions (M4) — IMPLEMENTED

| Method | Path                       | Auth | Description                    |
| ------ | -------------------------- | ---- | ------------------------------ |
| POST   | /api/v1/sessions           | host | Create session                |
| GET    | /api/v1/sessions           | host | List own sessions, newest first (M9) |
| GET    | /api/v1/sessions/{id}      | host | Get session (owning host)     |
| GET    | /api/v1/sessions/{id}/summary | host | Round/session summary (M16)  |
| PATCH  | /api/v1/sessions/{id}/order  | host | Reorder the current round (per-round) |
| DELETE | /api/v1/sessions/{id}/order  | host | Reset the current round to join order |
| POST   | /api/v1/sessions/{id}/leave | participant | Delete the participant + all their songs (leave the night) |
| POST   | /api/v1/sessions/{id}/start| host | Start session (owning host)   |
| POST   | /api/v1/sessions/{id}/end  | host | End session (owning host)     |
| GET    | /api/v1/sessions/{id}/qr   | host | Join URL as SVG QR code (M5)  |

Session creation returns `id`, `name`, `joinCode`, a QR-friendly `joinUrl`, and
`status`. Session state is a `SessionStatus` enum:

```text
CREATED -> ACTIVE <-> PAUSED -> ENDED
```

`ENDED` is reachable from any other state; `PAUSED` becomes reachable at M14.
`ROUND_COMPLETE` was removed at M10.1 (rounds auto-advance, no enrollment).
Invalid transitions return `409`.
Accessing a session that does not exist *or belongs to another host* returns
`404 session not found` (no existence leak, decision D29).

```text
GET /api/v1/sessions                Authorization: Bearer <token>    # M9 dashboard home
200 [
  { "id": "...", "name": "Friday Karaoke - 2026-08-14", "join_code": "K7X3QP",
    "join_url": "http://localhost:5173/join/K7X3QP", "status": "ACTIVE",
    "created_at": "...", "started_at": "...", "ended_at": null },
  ...                                 # newest first (created_at, id) desc
]
401 { "detail": "authentication required" }

POST /api/v1/sessions                  Authorization: Bearer <token>
{ }                                    # name optional; defaults below
# or { "name": "Spring Concert Night" }
# or { "name": "...", "cooldown_seconds": 10, "countdown_seconds": 20 }  # M13 timings

201 {
  "id": "d4c7a99f-...",
  "name": "Friday Karaoke - 2026-08-14",   # default: "Friday Karaoke - <server date>"
  "join_code": "K7X3QP",                   # unambiguous alphabet, 6 chars (D27)
  "join_url": "http://localhost:5173/join/K7X3QP",   # {KARAOKE_PUBLIC_BASE_URL}/join/{code} (D28)
  "status": "CREATED",
  "playback_state": "IDLE",                # stored (M13, D47)
  "cooldown_seconds": 10,                  # per-session automatic-transition timings (M13)
  "countdown_seconds": 20,
  "created_at": "2026-08-10T22:43:00Z",
  "started_at": null,
  "ended_at": null
}

401 { "detail": "authentication required" }     # missing/invalid token
422 { "detail": [...] }                          # name > 100 chars, or timings out of 0..3600
```

```text
GET /api/v1/sessions/{id}              Authorization: Bearer <token>
200 { ...same shape as above... }
404 { "detail": "session not found" }            # unknown id or another host's session

POST /api/v1/sessions/{id}/start       Authorization: Bearer <token>
200 { ..., "status": "ACTIVE", "started_at": "..." }   # CREATED -> ACTIVE
409 { "detail": "session <id> cannot start from state ACTIVE" }  # already started/ended

POST /api/v1/sessions/{id}/end         Authorization: Bearer <token>
200 { ..., "status": "ENDED", "ended_at": "..." }   # any non-terminal -> ENDED
409 { "detail": "session <id> is already ended" }
```

Notes: only the owning host can get/start/end a session (decision D29). The join
URL is derived from the join code and `KARAOKE_PUBLIC_BASE_URL`; it is never
stored. QR generation (SVG encoding of the join URL) is served at
`GET /api/v1/sessions/{id}/qr` (decision D32); the `/join/{code}` lookup lands in
M5.

## 4. Public join (M5) — IMPLEMENTED

| Method | Path                                 | Auth | Description                        |
| ------ | ------------------------------------ | ---- | ---------------------------------- |
| GET    | /api/v1/join/{joinCode}              | none | Look up session by join code       |
| POST   | /api/v1/join/{joinCode}/participants | none | Register participant + nickname    |

These endpoints are **public** (no bearer token): anyone with the join code can
look up a session and join (rule B2). Participant registration returns an opaque
participant token and the session snapshot. No participant account exists
(decision D6).

```text
GET /api/v1/join/{joinCode}              # joinCode is case-insensitive
200 {
  "id": "d4c7a99f-...",
  "name": "Friday Karaoke - 2026-08-14",
  "status": "CREATED"                    # ENDED is still returned so the UI
}                                        # can show "This karaoke night has ended"
404 { "detail": "session not found" }

POST /api/v1/join/{joinCode}/participants
{ "nickname": "Emma" }                   # required, trimmed, 1-20 chars, unique per session

201 {
  "token": "fr5zCS4nGntz3pAGYIMlfyG0vK-5mWuHeS8xXud8_V4",   # opaque, shown once
  "token_type": "bearer",
  "session": { "id": "...", "name": "...", "status": "CREATED" },
  "participant": { "id": "...", "session_id": "...", "nickname": "Emma",
                   "created_at": "..." }
}
404 { "detail": "session not found" }
409 { "detail": "this karaoke night has ended" }      # ENDED sessions cannot be joined
409 { "detail": "nickname 'emma' is already taken" }  # case-insensitive per session
422 { "detail": [...] }                                # blank/overlong nickname
429 { "detail": "too many requests — please slow down" }   # M17: join is rate-limited (10/min/IP)
```

Notes: the nickname rules are B14/D16 (trimmed, 1-20 chars, case-insensitive
uniqueness per session, decision D31). The participant token is hashed at rest
(SHA-256 digest). The QR code (M5, decision D32) encodes the session's join URL
and is served as an SVG at `GET /api/v1/sessions/{id}/qr` (owning host).

## 5. Songs / queue (M6, M7) — IMPLEMENTED

| Method | Path                                     | Auth        | Description                              |
| ------ | ---------------------------------------- | ----------- | ---------------------------------------- |
| POST   | /api/v1/sessions/{id}/entries/preview    | participant | Validate URL + return metadata preview (M6) |
| POST   | /api/v1/sessions/{id}/entries            | participant | Submit song (create WAITING entry) (M7)  |
| GET    | /api/v1/sessions/{id}/entries            | none        | Queue snapshot (public, sanitized) (M7)  |
| DELETE | /api/v1/entries/{entryId}                | participant *or* host | Cancel own WAITING / host remove (M7) |
| PATCH  | /api/v1/entries/{entryId}/video          | host        | Host replaces the YouTube URL (M7)       |

### Submit (M7)

```text
POST /api/v1/sessions/{id}/entries            Authorization: Bearer <participant token>
{ "youtube_url": "https://youtu.be/dQw4w9WgXcQ" }

201 {
  "entry": { "id": "...", "participant_name": "Alice", "status": "WAITING",
             "video_id": "dQw4w9WgXcQ", "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
             "title": "Never Gonna Give You Up", "channel": "Rick Astley",
             "duration_seconds": 213, "thumbnail_url": "...", "position": 1,
             "created_at": "..." },
  "duplicate": false,                    # true when the same video is already queued (B16)
  "notice": null                         # "This song is already in the queue." when duplicate
}
401 / 404 (wrong session) / 409 (ended session, or per-participant cap B15) / 422 (bad URL)
404 { "detail": "we couldn't load this video" }   # E4
429 { "detail": "too many requests — please slow down" }   # M17: submit is rate-limited (20/min/IP)
```

The entry is assigned to a round at submission (D43): the current round when the
participant has no non-terminal entry there, otherwise the next round above their
highest round. `position` is `null` for future-round entries (not yet in the
active queue).

### Queue snapshot (M7, round-scoped at M10.1, summaries at M16)

```text
GET /api/v1/sessions/{id}/entries                # public, no auth
200 {
  "session_id": "...",
  "status": "ACTIVE",
  "round_number": 2,                             # active round (M10.1)
  "rounds_completed": 1,                         # fully-played rounds (M16)
  "playback_state": "PLAYING",                   # stored (M13, D47)
  "transition_until": null,                      # transition deadline (M13)
  "transition_remaining_seconds": null,          # countdown display (M13)
  "participants": [ { "nickname": "Alice", "remaining_songs": 2 }, ... ],  # M16
  "queue": [ { ...QueueEntryResponse as above, "position": 1 }, ... ]
}                                                # current round, stable participant order (D43)
404 { "detail": "session not found" }
```

Positions are computed within the current round from the authoritative stable
participant order (each participant's earliest submission time; decision D43);
future-round songs are not part of the snapshot and have no position. There is no
mutable position field. `rounds_completed` counts the rounds fully played and
`participants` the per-participant remaining-song counts (M16). The snapshot is
sanitized (no host identity, no participant tokens).

### Session summary (M16)

```text
GET /api/v1/sessions/{id}/summary                Authorization: Bearer <host token>
200 {
  "session_id": "...", "status": "ACTIVE",
  "active_round": 2, "rounds_completed": 1,
  "participants": [ { "nickname": "Alice", "songs_submitted": 3,
                      "songs_sung": 1, "songs_remaining": 2 }, ... ]
}
404 { "detail": "session not found" }             # unknown or another host's
```

### Cancel / remove / edit (M7)

```text
DELETE /api/v1/entries/{entryId}   Authorization: Bearer <participant token>
204                                 # own WAITING entry -> CANCELLED (B3)
409 { "detail": "only WAITING entries can be cancelled, not SINGING" }

DELETE /api/v1/entries/{entryId}   Authorization: Bearer <host token>
204                                 # any entry in a session you own -> REMOVED (B4)

PATCH /api/v1/entries/{entryId}/video   Authorization: Bearer <host token>
{ "youtube_url": "https://youtu.be/9bZkp7q19f0" }
200 { ...QueueEntryResponse... }     # position + participant preserved (E7)
422 { "detail": "that doesn't look like a valid YouTube link" }   # old URL kept
```

Cross-actor semantics: the same DELETE path means "cancel own entry" for a
participant and "remove any entry" for a host (decision D37); unknown entries or
entries outside the actor's reach return 404 (no existence leak). Since M10.1
(D43) cancelling works for **any** of the participant's own WAITING entries,
including songs assigned to future rounds (they leave their round; the queue is
unchanged because they were never in the active queue). Since M14 (E6), **removing
the current `SINGING` entry advances playback** — the next entry is promoted to
`NEXT` and the countdown transition begins (skipping the cooldown, D20) — so the
host can cut a bad live song without database access. Removing an already-terminal
entry is a no-op (the status is preserved, E21).

### Preview (M6) — IMPLEMENTED

```text
POST /api/v1/sessions/{id}/entries/preview   Authorization: Bearer <participant token>
{ "youtube_url": "https://youtu.be/dQw4w9WgXcQ" }   # watch / youtu.be / embed / shorts

200 {
  "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # canonical
  "video_id": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "channel": "Rick Astley",
  "duration_seconds": 213,
  "thumbnail_url": "https://i.ytimg.com/vi/medium.jpg",
  "is_long": false,                      # true when > KARAOKE_YOUTUBE_LONG_VIDEO_SECONDS (D34)
  "warning": null                        # "This video is unusually long (...)" when is_long
}

401 { "detail": "authentication required" }             # missing/invalid participant token
404 { "detail": "session not found" }                    # unknown session or token from another session
409 { "detail": "this karaoke night has ended" }         # ENDED sessions cannot preview
422 { "detail": "that doesn't look like a valid YouTube link" }   # E3: malformed/non-YouTube URL
404 { "detail": "we couldn't load this video" }          # E4: valid format, metadata unavailable
503 { "detail": "KARAOKE_YOUTUBE_API_KEY is not configured" }    # service unconfigured (D33)
429 { "detail": "too many requests — please slow down" }         # M17: preview is rate-limited (20/min/IP)
```

The preview is stateless (nothing persisted until M7). Metadata source is the
YouTube Data API v3 (decision D33); long videos warn but are never rejected
(rule B6, decision D34). The participant token must belong to the session in
the path.

Target request/response example:

```text
POST /sessions/{id}/entries
{
  "youtubeUrl": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}

201 {
  "id": "8f2b...",
  "participantName": "Alice",
  "songTitle": "...",
  "channel": "...",
  "durationSeconds": 212,
  "status": "WAITING",
  "position": 3
}
```

## 6. Playback (M11, M13) — IMPLEMENTED

| Method | Path                       | Auth | Description             |
| ------ | -------------------------- | ---- | ----------------------- |
| POST   | /api/v1/sessions/{id}/play/start  | host | Manually start the front of the queue (→ SINGING; cancels any pending transition) |
| POST   | /api/v1/sessions/{id}/play/end    | host | The host player reports the video ended naturally (→ COMPLETED, then COOLDOWN → COUNTDOWN → auto-start, M13) |
| POST   | /api/v1/sessions/{id}/play/skip   | host | Current singer -> SKIPPED, then the countdown (D20/M13) |
| POST   | /api/v1/sessions/{id}/play/finish | host | Current singer -> COMPLETED, then the countdown (D20/M13) |
| POST   | /api/v1/sessions/{id}/play/advance | host | Progress an automatic transition whose phase deadline passed (M13: COOLDOWN -> COUNTDOWN -> auto-start) |
| POST   | /api/v1/sessions/{id}/play/pause  | host | ACTIVE -> PAUSED (cancels any pending transition) |
| POST   | /api/v1/sessions/{id}/play/resume | host | PAUSED -> ACTIVE |

All return the authoritative `QueueSnapshotResponse`. Its `playback_state` is
the stored state (D47): `PLAYING` while an entry is `SINGING`, `IDLE` when idle,
and `COOLDOWN`/`COUNTDOWN` during an automatic transition. The snapshot also
carries `transition_until` (absolute deadline) and
`transition_remaining_seconds` for countdown display; the host dashboard calls
`play/advance` when the deadline passes (idempotent — a reopened tab with an
overdue deadline self-recovers). Per-session timings are set at session creation
(`cooldown_seconds`, `countdown_seconds`; defaults 10/20).

```text
POST /api/v1/sessions/{id}/play/start          Authorization: Bearer <host token>
200 {
  "session_id": "...", "status": "ACTIVE", "round_number": 1,
  "playback_state": "PLAYING", "transition_until": null,
  "transition_remaining_seconds": null,
  "queue": [ { "...", "status": "SINGING", "position": 1 }, ... ]
}
409 { "detail": "the queue is empty" }                # nothing queued
409 { "detail": "a song is already playing" }
404 { "detail": "session not found" }                 # unknown or another host's

POST /api/v1/sessions/{id}/play/end            # natural video end (M13)
200 { ..., "playback_state": "COOLDOWN", "transition_until": "...",
      "transition_remaining_seconds": 9.8, "queue": [ { ..., "status": "NEXT" } ] }
409 { "detail": "no song is currently playing" }

POST /api/v1/sessions/{id}/play/advance        # when the phase deadline passed
200 { ..., "playback_state": "COUNTDOWN", ... }        # COOLDOWN -> COUNTDOWN
200 { ..., "playback_state": "PLAYING", "queue": [ { ..., "status": "SINGING" } ] }  # -> auto-start
409 { "detail": "cooldown is still running" }   # / "countdown is still running"
409 { "detail": "no automatic transition in progress" }

POST /api/v1/sessions/{id}/play/skip           # and /play/finish
200 { ..., "playback_state": "COUNTDOWN", "queue": [ { ..., "status": "NEXT" }, ... ] }
409 { "detail": "no song is currently playing" }

POST /api/v1/sessions/{id}/play/pause
200 { ..., "status": "PAUSED", "playback_state": "IDLE", ... }
409 { "detail": "session <id> cannot be paused from state CREATED" }

POST /api/v1/sessions/{id}/play/resume
200 { ..., "status": "ACTIVE", ... }
409 { "detail": "session <id> cannot be resumed from state ACTIVE" }

# Reorder the current round (queue revision: join order by default; the host
# can re-arrange per round — the next round resets to join order).
PATCH /api/v1/sessions/{id}/order               Authorization: Bearer <host token>
{ "participant_names": ["Charlie", "Alice", "Bob"] }
200 { ...QueueSnapshotResponse with the reordered queue... }
422 { "detail": "unknown participant(s): Ghost" }   # / "participant names must be unique"
422 { "detail": "the queue is empty — nothing to reorder" }
404 { "detail": "session not found" }

DELETE /api/v1/sessions/{id}/order               # back to join order
200 { ...QueueSnapshotResponse... }

# Leave the session (participant goes home early): deletes the participant and
# all their songs; the nickname is freed and their token dies. If they were the
# current singer, playback advances (E6).
POST /api/v1/sessions/{id}/leave                Authorization: Bearer <participant token>
204
404 { "detail": "session not found" }            # unknown session or token from another session
```

The queue snapshot's `queue` entries carry their `SINGING`/`NEXT`/`WAITING`
status, so clients derive "now singing" and "up next" from the authoritative
data. Advancing past a round's last entry crosses into the next round
automatically (M10.1/M13).

## 7. Rounds (revised at M10.1)

The M1/M16 enrollment endpoints (`/rounds/{roundId}/enroll`, host "start next
round") are **removed**: rounds auto-advance (decision D44) and there is no
enrollment. The round number is surfaced in the queue snapshot
(`round_number`, M10.1) and the realtime `QueueUpdated` event. A participant
cancels their remaining songs to drop out (existing `DELETE /api/v1/entries/{id}`,
B3). Remaining round-lifecycle concerns (absent-participant cleanup, round/session
summaries) are tracked in plan.md §M16.

## 8. Realtime (WebSocket, M10) — IMPLEMENTED (QueueUpdated / ParticipantJoined / SessionUpdated)

- Session stream: `ws(s)://<host>/api/v1/sessions/{id}/ws?token=<bearer>`
  (the browser WebSocket API cannot set request headers, so the bearer token
  rides in the query parameter; decision D42).

The `token` must belong to the session — a participant token must be bound to
it, a host token must own it; anything else is rejected before the connection
is accepted (close code 1008, HTTP 403 on the upgrade, no existence leak).

Events are typed domain events (delivery only, never authoritative):

```text
QueueUpdated       payload: { type, session_id, snapshot: QueueSnapshotResponse }
ParticipantJoined  payload: { type, session_id, nickname }
SessionUpdated     payload: { type, session_id, status }
SingerStarted      payload: { type, session_id, entry_id, participant_name, title }
SingerFinished     payload: { type, session_id, entry_id }
SingerSkipped      payload: { type, session_id, entry_id }
NextSingerNotified payload: { type, session_id, entry_id, participant_name,
                              title, channel, phase: "next" | "countdown" }   (M15)
```

`QueueUpdated` carries the full authoritative queue snapshot (the same shape
the REST `GET /sessions/{id}/entries` returns) so every subscriber renders the
same state. It is emitted after submit, participant cancel, host remove, host
edit, and every playback transition. `ParticipantJoined` fires when someone
registers in the session; `SessionUpdated` fires when the host starts/ends/
pauses/resumes the session.

`NextSingerNotified` is the in-app "you're next" notification (M15,
PRODUCT_SPEC §11): phase `next` when an entry is promoted to `NEXT`, phase
`countdown` when the countdown transition begins. It is broadcast to every
subscriber; the participant's device filters on `participant_name`. Web Push is
deferred (needs the M19 service worker + VAPID credentials).

The other events in the original target list (`RoundStarted`, `RoundCompleted`,
`SessionPaused`, `SessionResumed`, `ParticipantRemoved`) are not emitted. Round
advances are visible through `round_number` in the `QueueUpdated` snapshot
(M10.1); singer events arrive at M11/M13 and pause/resume at M14.

Rules:

- WebSockets are a delivery mechanism, not the source of truth.
- On reconnect, clients must re-fetch authoritative state via the REST API.
- Event payloads carry typed fields, not free-form strings.

## 9. Queue snapshot shape (target)

```text
{
  "sessionId": "uuid",
  "status": "ACTIVE",
  "roundNumber": 2,
  "currentSinger": { "participantName": "Alice", "songTitle": "...", "entryId": "uuid" },
  "upNext": { "participantName": "Bob", "songTitle": "...", "entryId": "uuid" },
  "queue": [ { "entryId": "uuid", "participantName": "...", "songTitle": "...",
               "status": "WAITING" } ],
  "yourPosition": 3
}
```

Exact shape is finalized when the queue APIs are implemented (M7); M10.1 adds
`round_number` (the active round) to the public snapshot.
