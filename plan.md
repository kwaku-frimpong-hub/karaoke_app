# Friday Karaoke — Implementation Plan

## 0. Project Mission

Build and deploy a private karaoke queue application for our school's Friday
karaoke nights.

The application removes the repetitive work currently done by the host:

1. Host creates a karaoke session.
2. Application generates a QR code.
3. Students scan the QR code.
4. Students enter a nickname and paste the YouTube URL for the song they want.
5. The application fetches/displays the video metadata and puts the entry in the queue.
6. Everyone can see the current queue and their position.
7. The host has final control over the queue and playback.
8. The host's browser is the playback device.
9. Songs transition automatically, with configurable preparation/cooldown time.
10. The next singer is notified.
11. When a round ends, participants are asked whether they want to participate in
    the next round. Default: YES if they do nothing.

The application is intended for real use at school, not just as a portfolio demo.

---

# 1. Engineering Principles

These rules apply to every milestone.

### 1.1 Build a modular monolith first

Use one backend application.

Do NOT introduce microservices, Kafka, RabbitMQ, Kubernetes, CQRS, event sourcing,
or other distributed infrastructure unless a later milestone has a concrete
requirement for it.

### 1.2 Keep milestones small

Each milestone should produce a working, testable increment.

A less powerful coding agent should be able to implement one milestone without
having to understand the entire future system.

### 1.3 Backend owns the truth

The frontend must never be the source of truth for:

- queue order
- current singer
- round state
- playback state
- permissions
- participant identity
- session state

The backend/database is authoritative.

### 1.4 Host is the final authority

Participants can submit songs and leave/cancel their own entries.

The host can:

- remove queue entries
- edit/fix YouTube URLs
- skip singers
- start/stop playback
- manually advance the queue
- end the session

The system should automate normal operation but always allow host intervention.

### 1.5 Do not over-validate YouTube content

A participant may submit a long or unusual video.

The application should:

- validate that the URL is a supported YouTube URL
- extract video metadata where possible
- warn about unusually long videos

It should NOT automatically reject a video simply because it is long.

The host decides whether the submitted video is appropriate.

### 1.6 Host browser is the playback device

Participants' phones do not play the karaoke songs.

The host dashboard contains the YouTube player and is connected to the
school's screen/speaker setup.

This avoids trying to synchronize playback across many participant devices.

### 1.7 Prefer simple technology

Recommended initial stack:

- Backend: Python 3.12+ / FastAPI
- Language: Python 3.12+
- Database: PostgreSQL
- ORM: SQLAlchemy 2.x
- Realtime: FastAPI WebSockets
- Frontend: React + TypeScript
- Build tooling: Vite
- PWA: standard web manifest + service worker
- Containers: Docker / Docker Compose
- Reverse proxy: Caddy or Nginx
- Notifications: Web Push
- Testing: pytest + integration tests
- Dependency management: uv (preferred) or Poetry
- Validation/settings: Pydantic v2
- Migrations: Alembic
- ASGI server: Uvicorn
- Static type checking: Pyright or mypy

### Python engineering rules

**Pydantic is mandatory for API and application-boundary models.**

- Use Pydantic v2 for all FastAPI request models and response models.
- Use Pydantic Settings for application configuration and environment variables.
- Do NOT use raw `dict` payloads for structured API input/output when a Pydantic model can be used.
- Use Python `Enum` types for domain states instead of free-form strings.
- Use `UUID`, `datetime`, `timedelta`, and other appropriate Python types instead of representing typed values as strings.
- Use Pydantic field constraints, `Annotated`, and validators where appropriate.
- Keep SQLAlchemy ORM models separate from Pydantic API schemas.
- Define explicit mappings between persistence models and API/application models.
- Use explicit type hints on public functions, service methods, WebSocket messages, and event payloads.
- Avoid `Any` unless there is a documented reason.
- Avoid untyped `dict[str, Any]` structures for domain data.
- Configure a static type checker and require it to pass before a milestone is considered complete.
- Do not weaken types simply to make implementation easier.

Pydantic models are part of the architecture, not optional convenience classes.

Redis is NOT required for the first deployment. Add it only if a concrete
requirement appears.

### Frontend UI quality bar

The project ships a real user-facing UI (participant phones + a projector host
dashboard), so visual/UX quality is part of every frontend milestone's
Definition of Done. Every frontend milestone must follow the **`frontend-ui`**
skill in `.opencode/skills/frontend-ui/SKILL.md`:

- **Design tokens** — colors, spacing, radius, and type scale are CSS variables
  in `src/index.css`; screens never hard-code values.
- **Two surfaces** — participant screens are mobile-first (single column, ≥ 44px
  targets); the host dashboard is projector/TV-ready (large text, high contrast,
  now/next above the fold).
- **Component patterns** — buttons (primary/ghost/danger), cards, badges, labeled
  inputs with `:focus-visible`, list rows, and loading/empty/error states for
  every fetch.
- **Accessibility** — WCAG AA contrast, visible focus rings, semantic HTML, and
  no `<a>` wrapping a `<button>`.
- **Checks** — `npm run typecheck`, `npm run lint`, and `npm run build` pass.

The coder agent loads this skill when touching frontend UI; the reviewer loads
it when reviewing frontend diffs.

---

# 1.1 Engineering Portfolio Intent

This project is also intended to demonstrate practical Python backend engineering
for Python and C/C++-oriented roles. Favor clean Python, strong typing, clear data
structures, deterministic state machines, concurrency-safe backend logic, API design,
PostgreSQL, networking/realtime concepts, testing, Docker/Linux deployment, and
performance-conscious code where it matters.

Do not force C++ into this application merely for portfolio purposes. Demonstrate
engineering fundamentals through a real Python system.

## Engineering Portfolio Intent

This project should also demonstrate practical Python backend engineering for Python and C/C++ roles. Favor clean Python, strong typing, deterministic state machines, concurrency-safe logic, API design, PostgreSQL, networking/realtime concepts, testing, Docker/Linux deployment, and performance-conscious code where appropriate. Do not force C++ into the application merely for portfolio purposes.

# 2. Repository / Agent Workflow

## 2.1 Establish the project "main brain"

Before implementation begins, create:

```text
/docs/
    PROJECT_BRAIN.md
    ARCHITECTURE.md
    DOMAIN_MODEL.md
    API_CONTRACT.md
    DECISIONS.md
    RUNBOOK.md
```

### PROJECT_BRAIN.md

This is the project's persistent context for coding agents.

It must contain:

- product purpose
- target users
- core user journeys
- current architecture
- technology stack
- domain concepts
- important business rules
- current milestone
- completed milestones
- known limitations
- important decisions
- commands for running/testing the project
- things explicitly NOT to build

Every coding agent must read `PROJECT_BRAIN.md` before modifying the project.

### DEV_BRAIN.md

Create a second file for active development context:

```text
DEV_BRAIN.md
```

This should contain:

- current milestone
- current task
- files being changed
- implementation notes
- current blockers
- tests added
- unresolved technical questions
- next recommended task

At the end of every milestone, update `PROJECT_BRAIN.md` and `DEV_BRAIN.md`.

### Rule for agents

When starting work:

1. Read `PROJECT_BRAIN.md`.
2. Read `ARCHITECTURE.md`.
3. Read the current milestone section in `DEV_BRAIN.md`.
4. Inspect the existing implementation.
5. Implement only the requested milestone.
6. Run tests.
7. Update documentation.
8. Report what changed and what remains.

Do not silently redesign previous decisions.

If a requirement conflicts with the architecture, document the conflict in
`DECISIONS.md` before making a major change.

---

# 3. Milestone Overview

```text
M0  Repository + project brain
M1  Product specification + UX flows
M2  Backend skeleton + database
M3  Authentication
M4  Karaoke session creation
M5  Public QR join flow
M6  YouTube URL submission + metadata
M7  Queue management
M8  Participant queue UI
M9  Host dashboard
M9.1 Frontend UI polish (design system + quality bar)
M10 Realtime updates (WebSockets)
M10.1 Queue rounds + auto-advance (round-robin queue)
M11 Playback state machine
M12 YouTube host player
M13 Automatic song transitions
M14 Host moderation + manual controls
M15 Next-singer notifications
M16 Round lifecycle cleanup + summaries (revised at M10.1)
M17 Security + abuse protection
M18 Testing + failure scenarios
M19 PWA + mobile UX
M20 Deployment
M21 Real-world Friday karaoke pilot
M22 Post-pilot fixes and v1 release
```

---

# M0 — Repository + Project Brain

## Goal

Create the project structure and persistent context for future coding agents.

## Tasks

- Initialize git repository if necessary.
- Create backend project.
- Create frontend project.
- Create docs directory.
- Create `PROJECT_BRAIN.md`.
- Create `DEV_BRAIN.md`.
- Create `ARCHITECTURE.md`.
- Create `DOMAIN_MODEL.md`.
- Create `API_CONTRACT.md`.
- Create `DECISIONS.md`.
- Add `.gitignore`.
- Add basic README.
- Document local development commands.

## Acceptance criteria

- Fresh clone can be opened by a developer/agent.
- Documentation explains how the project works.
- Backend starts.
- Frontend starts.
- No business functionality is required yet.

---

# M1 — Product Specification + UX

## Goal

Freeze the MVP behavior before implementing complex functionality.

## Define

### Host flow

```text
Login
  -> Create session
  -> Display QR
  -> Monitor queue
  -> Start/skip/edit/remove
  -> Automatic playback
  -> Finish round
  -> Start next round
  -> End session
```

### Participant flow

```text
Scan QR
  -> Enter nickname
  -> Paste YouTube URL
  -> Review song metadata
  -> Join queue
  -> Monitor position
  -> Receive "you're next"
  -> Perform
  -> Participate in next round
```

## Define edge cases

At minimum:

- duplicate song
- participant leaves
- participant submits invalid URL
- YouTube video unavailable
- video becomes unavailable after submission
- host removes participant
- host edits a song
- participant refreshes page
- participant loses internet
- host loses internet
- host closes browser
- song ends
- host manually skips
- host manually advances
- queue becomes empty
- round ends
- participant does not answer next-round prompt *(superseded at M10.1 — no enrollment)*

## Acceptance criteria

The user flows and business rules are documented clearly enough that another
developer can implement them without guessing.

---

# M2 — Backend Skeleton + Database

## Goal

Create a clean backend foundation.

## Tasks

- Configure FastAPI.
- Configure SQLAlchemy 2.x.
- Configure PostgreSQL.
- Add migrations.
- Establish FastAPI dependency injection.
- Add configuration system.
- Add structured logging.
- Add health endpoint.
- Establish project layers/modules.

Suggested structure:

```text
backend/
    app/
        api/
        core/
        domain/
        services/
        repositories/
        models/
        schemas/
        main.py
    tests/
```

Do not create unnecessary abstractions.

## Acceptance criteria

- Application starts.
- PostgreSQL connects.
- Migrations run.
- Health endpoint works.
- Automated test project runs.
- API request/response contracts use Pydantic models.
- Configuration uses Pydantic Settings.
- Static type checking is configured and passes.

---

# M3 — Host Authentication

## Goal

Allow a host to securely create/manage karaoke sessions.

## Requirements

For v1, keep authentication simple.

Possible implementation:

- email/password
- or school-approved authentication if available

Do not build complex identity infrastructure unless required.

## Tasks

- Host registration/login.
- Password hashing.
- Authentication tokens/cookies.
- Authorization.
- Logout.
- Protected host endpoints.

## Acceptance criteria

- Anonymous users cannot create sessions.
- Authenticated host can access host endpoints.
- Another host cannot modify someone else's session.

---

# M4 — Karaoke Session Creation

## Goal

A host can create a Friday karaoke session.

## Session fields

At minimum:

```text
id
name
joinCode
status
createdAt
startedAt
endedAt
```

Possible statuses:

```text
CREATED
ACTIVE
PAUSED
ROUND_COMPLETE    # removed at M10.1 (rounds auto-advance; no enrollment)
ENDED
```

## Tasks

- Create session API.
- Get session API.
- Start session.
- End session.
- Generate unique join code.
- Generate join URL.

## Acceptance criteria

Host can create:

```text
Friday Karaoke - 2026-08-14
```

and receive a join URL/code.

---

# M5 — Public QR Join Flow

## Goal

Students can join without creating accounts.

## Tasks

- Public session lookup by join code.
- Participant registration.
- Nickname creation.
- Anonymous participant identity.
- Secure participant token/session.
- QR code generation/display.

## Important rule

A participant account is NOT required.

The host has an account.

Participants only need a session-specific identity.

## Acceptance criteria

A student scans the QR code and reaches the correct session.

---

# M6 — YouTube URL Submission + Metadata

## Goal

Replace the host manually searching YouTube.

## Flow

```text
Participant
    |
    | paste URL
    v
Backend
    |
    | validate URL
    v
Extract video ID
    |
    v
Fetch metadata
    |
    v
Return preview
```

## Store

At minimum:

```text
youtubeVideoId
youtubeUrl
title
channel
duration
thumbnailUrl
```

## Rules

- Support normal YouTube watch URLs.
- Support youtu.be URLs.
- Reject malformed/non-YouTube URLs.
- Warn about unusually long videos.
- Do not reject long videos automatically.
- Do not assume the video is a karaoke track.
- Host has final authority.

## Acceptance criteria

Participant pastes a valid YouTube URL and sees a preview before joining.

---

# M7 — Queue Management

## Goal

Create the authoritative queue engine.

## Queue entry

Suggested fields:

```text
id
sessionId
roundId
participantId
youtubeVideoId
title
artist/channel
duration
status
createdAt
startedAt
endedAt
```

Statuses:

```text
WAITING
NEXT
SINGING
COMPLETED
SKIPPED
CANCELLED
REMOVED
```

## Rules

- Queue ordering is determined by creation/order, not a mutable position field.
- Participant can cancel their own waiting entry.
- Host can remove any entry.
- Host can edit a YouTube URL.
- Participant cannot modify another participant.
- One participant should have a reasonable per-participant song cap (a total cap
  across rounds, default 5; revised at M10.1).

## Acceptance criteria

Multiple users can join and queue order remains deterministic.

---

# M8 — Participant Queue UI

## Goal

Build the mobile-first queue experience.

Display:

```text
Currently singing
Up next
Queue
Your position
Your song
Session status
```

Participant actions:

- join
- cancel waiting song
- view current position
- view current singer
- view next singer

Do not build the host dashboard yet.

## Acceptance criteria

A student can use the entire queue flow from a phone.

---

# M9 — Host Dashboard

## Goal

Give the host one screen to control karaoke.

Display:

```text
Current singer
Current song
Playback status
Queue
Participant names
Song titles
Song durations
```

Actions:

```text
Start
Skip
Finish
Remove
Edit
Pause
Resume
End session
```

The host dashboard must be usable while connected to a projector/TV.

---

# M9.1 — Frontend UI polish

## Goal

Bring the participant and host screens up to the project's frontend UI quality
bar (the `frontend-ui` skill in `.opencode/skills/frontend-ui/SKILL.md`), which
every frontend milestone must follow from now on.

## Tasks

- Codify the design tokens (colors, spacing, radius, type scale) as CSS
  variables in `frontend/src/index.css`; refactor `App.css` to use them.
- Rework the host screens (login, home, dashboard) and the participant screens
  (join, submit, queue) to the component patterns in the skill.
- Fix invalid HTML: no `<a>` element may wrap a `<button>` (host home currently
  does).
- Add real labels/focus states to inputs; ensure every async region shows
  loading, empty, and error states.
- Keep the dark theme and the existing architecture; no scope creep, no new
  dependencies, no backend changes.

## Acceptance criteria

- Design tokens are defined and used (no hard-coded colors/spacing in screens).
- Host dashboard is projector/TV-ready: large text, high contrast, now/next
  above the fold, actions grouped and disabled states explained.
- Participant screens are mobile-first with ≥ 44px touch targets.
- No `<a>` wrapping `<button>`; `:focus-visible` visible; inputs labeled.
- `npm run typecheck`, `npm run lint`, `npm run build` pass.
- No backend changes; existing backend suite still passes.

---

# M10 — Realtime Updates

## Goal

Everyone sees queue changes without refreshing.

Use FastAPI WebSockets.

Events should represent meaningful domain changes, for example:

```text
QueueUpdated
SingerStarted
SingerFinished
SingerSkipped
ParticipantJoined
ParticipantRemoved
RoundStarted
RoundCompleted
SessionPaused
SessionResumed
```

## Important rule

WebSockets are a delivery mechanism, not the source of truth.

After reconnecting, the client must fetch authoritative state again.

## Acceptance criteria

If the host skips a singer, participant phones update almost immediately.

---

# M10.1 — Queue Rounds + Auto-Advance

## Goal

Round-robin queue: each participant's songs play one round at a time — everyone's
1st song, then everyone's 2nd song, and so on. One song per participant per round;
rounds advance automatically; there is **no** next-round enrollment.

## Background / motivation

Participants may queue multiple songs (product decision, DECISIONS D43–D45). A
flat creation-order queue lets one participant's 2nd song jump ahead of another
participant's 1st. This milestone replaces that ordering (M1 rule B7 / decision
D8) with a round model: round N holds each participant's N-th song, ordered by a
**stable participant order** (the order in which participants first engaged,
fixed once and repeated every round). Rounds auto-advance, so "moving to everyone's
next song" IS the next round; the M16 enrollment prompt (default YES / explicit NO)
is dropped.

## Tasks

- **Submit / round assignment:** a participant's new song goes to the current
  round when they have no non-terminal entry there (first song, or rejoining the
  round after a skip/cancel); otherwise it goes one round above their highest
  round. At most one non-terminal entry per participant per round.
- **Active round is derived:** the lowest-numbered round with ≥ 1 non-terminal
  entry. When it empties, the session advances automatically to the next round
  that has entries. No stored counter, no `ROUND_COMPLETE` state.
- **Snapshot:** the active queue = the current round's non-terminal entries,
  ordered by stable participant order (each participant's earliest submission
  time, i.e. `MIN(created_at)`), then `created_at`/`id` as the deterministic
  tie-break. Add the current `round_number` to the queue snapshot. Positions are
  computed within the current round.
- **Song cap:** replace the active-entry limit (2 per round, B15/D17) with a
  per-participant **total** cap across all rounds, default 5, configurable via
  `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT`.
- **No enrollment:** remove `ROUND_COMPLETE` from `SessionStatus` and its
  transitions (`CREATED -> ACTIVE <-> PAUSED -> ENDED`). Participants opt out by
  cancelling their remaining songs; the existing cancel endpoint already works
  for any own WAITING entry, including future-round songs.
- **Participant "my songs":** a participant-scoped endpoint listing their own
  current + upcoming entries so the queue screen can show and cancel them.
- **Frontend:** the participant queue screen shows the round number, one song per
  participant, the participant's own songs (current + upcoming, each cancellable),
  and their position within the current round. The host dashboard shows a round
  indicator.
- **Realtime:** `QueueUpdated` snapshots already fire on every mutation; the
  round advance is visible through the snapshot's `round_number`. A dedicated
  `RoundStarted` event is **not** emitted: the mutation that empties a round
  already broadcasts `QueueUpdated` (which carries the new round's snapshot).

## Acceptance criteria

1. With p1 ×3, p2 ×2, p3 ×5 queued songs, the play order is p1,p2,p3 →
   p1,p2,p3 → p1,p3 → p3 → p3.
2. A participant's 2nd song is not visible in the queue until every
   participant's 1st song is done.
3. Round order is stable: within every round, participants sing in the order they
   first submitted/joined; late joiners are appended to the current round.
4. A participant whose songs run out drops out automatically; the queue continues.
5. The per-participant cap (default 5) is enforced; exceeding it rejects with a
   clear message.
6. No `ROUND_COMPLETE` state: rounds advance automatically with no enrollment
   prompt.
7. Positions are computed within the current round; future-round songs have no
   position.

---

# M11 — Playback State Machine

## Goal

Formalize playback behavior.

State example:

```text
IDLE
PREPARING
COUNTDOWN
PLAYING
COOLDOWN
FINISHED
SKIPPED
```

Transitions must be explicit.

Example:

```text
NEXT
  -> PREPARING
  -> COUNTDOWN
  -> PLAYING
  -> COOLDOWN
  -> NEXT
```

Host can interrupt transitions.

## Acceptance criteria

The backend can determine exactly which singer/song should be active: the
first non-terminal entry of the current round (stable participant order, M10.1).
When the current round's queue is exhausted, playback advances into the next
round's first entry automatically (M10.1).

---

# M12 — YouTube Host Player

## Goal

Embed the YouTube player into the host dashboard.

Important:

- Host browser is the playback device.
- Participants do not play the song.
- Use the YouTube embedded player/API where permitted.
- Handle player errors.
- Detect playback completion.
- Allow host manual control.

## Important limitation

Browser autoplay policies may require the host to interact with the page before
audio playback is allowed.

Design the UI around this.

## Acceptance criteria

Host can start a queued song and play it through the host machine's speakers.

---

# M13 — Automatic Song Transitions

## Goal

Reduce host workload.

Default behavior:

```text
Song ends
   ↓
cooldown
   ↓
next singer preparation
   ↓
countdown
   ↓
next song
```

The exact durations should be configurable per session.

Example defaults:

```text
post-song cooldown: 10 seconds
next-singer countdown: 20 seconds
```

The earlier product idea of a short rest before the next song should be
implemented as configuration, not hard-coded behavior.

## Important

Automatic advancement is a fallback/normal path.

Host can always:

- skip
- finish
- pause
- manually start another entry

---

# M14 — Host Moderation + Manual Controls

## Goal

Make the host the final authority.

Implement:

### Remove

Host removes a queue entry.

### Edit

Host can replace the YouTube URL for an entry.

Example:

```text
Student submits:
3 hour podcast

Host:
Edit -> correct YouTube URL -> Save
```

The participant remains in the queue.

### Skip

Host skips current song.

### Manual advance

Host can move to the next singer.

### Pause

Pause automatic progression.

### Resume

Continue session.

## Acceptance criteria

The host can recover from bad submissions without needing database access.

---

# M15 — Next-Singer Notifications

## Goal

Make sure people know when they are about to sing.

Start with in-app notifications.

Then add Web Push.

Example:

```text
🎤 You're next!

Get ready to sing:
Bohemian Rhapsody — Queen
```

Notification timing should be configurable.

Possible triggers:

```text
When moved to NEXT
During countdown
When immediately next
```

## Acceptance criteria

The next participant receives a clear notification.

---

# M16 — Round Lifecycle Cleanup + Summaries (revised at M10.1)

## Goal

(Revised at M10.1.) Rounds now **auto-advance** with no enrollment (M10.1,
decision D44): round N holds one song per participant, and when the queue is
exhausted the session moves to everyone's next song automatically. This
milestone covers the remaining round/participant lifecycle concerns that M10.1
does not.

## Tasks

- **Absent-participant cleanup:** participants who have disconnected/left should
  not silently keep future-round slots forever. Define a server-side cleanup
  window and behavior (entries removed or marked) so an absent singer cannot
  block the queue indefinitely.
- **Round/session summaries:** surface to the host how many rounds have been
  played, how many songs each participant had/remaining, and the active round,
  for the projector dashboard and end-of-night wrap-up.
- **End-of-night flow:** when no rounds remain and the queue is empty, the
  session can end cleanly (host action) without leftover state.

## Important

Do not create a new session for every round. A session contains multiple rounds:

```text
Session
  ├── Round 1   (everyone's 1st song)
  ├── Round 2   (everyone's 2nd song)
  ├── Round 3   (everyone's 3rd song)
  └── ...
```

Rounds advance automatically; there is no enrollment prompt.

## Acceptance criteria

- A participant who has left no longer occupies a future-round slot after the
  configured cleanup window.
- The host dashboard shows the active round and a per-participant song count.
- A Friday karaoke session can run multiple rounds without recreating the QR code.

---

# M17 — Security + Abuse Protection

## Goal

Make the application safe enough for real school use.

Implement:

- request validation
- rate limiting
- input length limits
- secure participant tokens
- authorization checks
- host ownership checks
- CSRF protection where applicable
- secure cookies/tokens
- YouTube URL validation
- maximum active queue entries per participant
- session expiration/cleanup strategy

Do not implement unnecessary enterprise security.

Focus on realistic threats to a public QR code.

---

# M18 — Testing + Failure Scenarios

## Goal

Test behavior rather than just endpoints.

## Unit tests

Test:

- queue ordering
- state transitions
- round transitions (round-robin ordering, round auto-advance — M10.1)
- skip
- finish
- remove
- cancel
- per-participant song cap (M10.1)

## Integration tests

Test:

- session creation
- participant joining
- queue submission
- host moderation
- authorization
- database persistence

## Concurrency tests

At minimum:

### Two users join simultaneously

Must receive deterministic order.

### Host skips while automatic transition occurs

Only one valid transition should happen.

### Participant cancels while host removes

System must end in a valid state.

### Host browser reconnects

It must recover authoritative playback/queue state.

### Participant reconnects

They must recover their session/queue state.

---

# M19 — PWA + Mobile UX

## Goal

Make the application feel native enough on phones.

Implement:

- web manifest
- installable PWA
- service worker
- mobile responsive UI
- offline/reconnect handling
- loading states
- error states
- QR-friendly join URL
- large touch targets

Do not attempt full offline karaoke operation.

Offline mode should primarily handle graceful recovery/reconnection.

---

# M20 — Deployment

## Goal

Deploy the actual application for school use.

Initial production architecture:

```text
                    Internet / School WiFi
                             |
                             v
                    Reverse Proxy
                             |
                +------------+------------+
                |                         |
                v                         v
             Frontend                  Backend
                                        |
                                        v
                                   PostgreSQL
```

Dockerize:

- frontend
- backend
- PostgreSQL

Use environment variables/secrets for:

- database credentials
- authentication secrets
- YouTube API credentials if required
- Web Push credentials
- production URLs

Add:

- HTTPS
- database backups
- health checks
- basic logging
- restart policy

Do NOT add Kubernetes unless there is a real operational requirement.

---

# M21 — Real Friday Karaoke Pilot

## Goal

Use the application during an actual Friday karaoke night.

Before the event:

- create production session
- test QR
- test host playback machine
- test speakers
- test projector/TV
- test internet
- test at least 3 songs
- test skip
- test bad YouTube URL
- test host edit
- test participant cancellation
- test automatic transition
- test round transition

During the event:

Record real problems.

Do not immediately redesign the system.

Create a list:

```text
BUG
UX PROBLEM
MISSING FEATURE
PERFORMANCE PROBLEM
USER CONFUSION
HOST WORKFLOW PROBLEM
```

---

# M22 — Post-Pilot Fixes + V1

## Goal

Fix what actually hurt during the real event.

Prioritize:

1. Data-loss bugs
2. Queue correctness
3. Playback problems
4. Host workflow problems
5. Participant workflow problems
6. Notifications
7. Visual polish
8. Nice-to-have features

Do not add features simply because they sound cool.

Every new feature should answer:

> Did this solve a real problem observed during karaoke night?

---

# 4. Core Domain Model

Target relationship:

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

A participant can exist only within a session for v1.

A session has multiple rounds.

A round contains queue entries.

A queue entry references one YouTube video.

---

# 5. Important Business Rules

1. Only authenticated hosts can create/manage sessions.
2. Anyone with the session QR/link can join.
3. Participants do not need accounts.
4. Host has final authority over the queue.
5. Participants can cancel their own waiting entries.
6. Host can remove any entry.
7. Host can edit a submitted YouTube URL.
8. Invalid YouTube URLs cannot be queued.
9. Long videos produce a warning, not automatic rejection.
10. Queue order is determined by authoritative backend state.
11. Host playback is authoritative for actual song playback.
12. Automatic advancement can always be overridden by the host.
13. A session contains multiple rounds.
14. At round completion, participants are asked whether they want the next round.
15. Default next-round choice is YES.
16. A participant who explicitly chooses NO does not enter the next round.
17. Realtime events are not authoritative state.
18. Reconnecting clients must resynchronize with backend state.
19. Host actions must be authorized server-side.
20. The application must remain usable if realtime connections temporarily fail.

---

# 6. Non-Goals for V1

Do NOT implement:

- Spotify integration
- song streaming service
- custom karaoke music hosting
- AI recommendations
- AI singing analysis
- voting
- leaderboards
- payments/tipping
- public venue management
- multi-venue management
- microservices
- Kubernetes
- Kafka
- RabbitMQ
- event sourcing
- complex analytics
- social profiles
- public discovery of karaoke sessions

These can be considered after the real school deployment proves the core product.

---

# 7. Definition of Done for Every Milestone

A milestone is NOT complete merely because code exists.

Every milestone must have:

- implementation
- tests appropriate to the milestone
- documentation updated
- local run instructions updated if necessary
- acceptance criteria verified
- no known broken existing functionality

At completion:

1. Update `PROJECT_BRAIN.md`.
2. Update `DEV_BRAIN.md`.
3. Update `DECISIONS.md` if a new architectural decision was made.
4. Commit the work with a meaningful commit message.
5. Record the next milestone/task.

---

# 8. Agent Instructions

This repository is intended to be developed with coding agents such as OpenCode.

The agent must behave as an implementation engineer, not as a product manager.

For each assigned milestone:

1. Read the project brain.
2. Read the current development brain.
3. Inspect existing code before changing it.
4. Identify the smallest implementation needed.
5. Implement it.
6. Write tests.
7. Run the relevant tests.
8. Fix failures.
9. Update documentation.
10. Summarize changes.
11. Do not implement future milestones unless explicitly requested.

If requirements are ambiguous:

- prefer the smallest reasonable interpretation
- preserve existing architecture
- document important assumptions
- do not introduce infrastructure merely because it is familiar

If a requested change would significantly alter architecture:

- explain the tradeoff
- update `DECISIONS.md`
- wait for approval if the change is destructive or difficult to reverse

The agent must not replace a working simple design with a more complex design
without a concrete requirement.

### Mandatory typing rule

Do not weaken typing to make implementation easier. If an endpoint, service, event,
queue command, or configuration value has a structured shape, define a typed model
for it. Prefer Pydantic models at application/API boundaries and explicit Python
types throughout the domain and service layers.

For example:

```python
class QueueEntryResponse(BaseModel):
    id: UUID
    participant_name: str
    song_title: str
    duration_seconds: int
    status: QueueEntryStatus
```

not:

```python
def get_queue() -> dict:
    ...
```

---

# 9. Development Order

Implement strictly in this order unless a dependency requires otherwise:

```text
M0
 ↓
M1
 ↓
M2
 ↓
M3
 ↓
M4
 ↓
M5
 ↓
M6
 ↓
M7
 ↓
M8
 ↓
M9
 ↓
M9.1
 ↓
M10
 ↓
M10.1
 ↓
M11
 ↓
M12
 ↓
M13
 ↓
M14
 ↓
M15
 ↓
M16
 ↓
M17
 ↓
M18
 ↓
M19
 ↓
M20
 ↓
M21
 ↓
M22
```

The first usable vertical slice should ideally exist as early as possible:

```text
M3 -> M4 -> M5 -> M6 -> M7 -> M8 -> M9
```

After that, add realtime/playback/automation.

---

# 10. Immediate Next Task

Start with **M0**.

Do not implement karaoke functionality yet.

First establish:

- repository structure
- backend
- frontend
- documentation
- `PROJECT_BRAIN.md`
- `DEV_BRAIN.md`
- `ARCHITECTURE.md`
- `DOMAIN_MODEL.md`
- `API_CONTRACT.md`
- `DECISIONS.md`

Then stop and report the state of the repository.

The project should be understandable by a new coding agent after reading the
project brain without needing the original conversation.
