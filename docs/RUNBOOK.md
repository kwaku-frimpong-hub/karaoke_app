# RUNBOOK.md — Friday Karaoke local development

How to set up, run, and test the project locally.

---

## Prerequisites

- Python 3.12+ (project targets 3.12+; developed with 3.14)
- [uv](https://docs.astral.sh/uv/) (dependency management)
- Node.js 20+ and npm
- Docker with Docker Compose (provides the local PostgreSQL)
- PostgreSQL via Docker (from M2 onward; no longer needed as a host install)

## Repository layout

```text
backend/    FastAPI application (uv-managed Python project)
frontend/   React + TypeScript SPA (Vite)
compose.yaml  local development PostgreSQL service
docs/       project documentation (start with docs/PROJECT_BRAIN.md)
plan.md     milestone definitions and acceptance criteria
```

## Database (from M2)

```bash
# Start the local PostgreSQL (Postgres 17, credentials karaoke/karaoke, db karaoke)
docker compose up -d db
docker compose ps db          # wait for health "healthy"

# Apply migrations from the backend directory
cd backend
uv run alembic upgrade head
```

- The backend connects via `KARAOKE_DATABASE_URL` (default
  `postgresql+asyncpg://karaoke:karaoke@localhost:5432/karaoke`).
- Optional: copy `backend/.env.example` to `backend/.env` and adjust. All values
  have defaults in `app/core/config.py`.

## Backend

```bash
cd backend

# Install dependencies (creates/uses .venv)
uv sync

# Run the API (development, with auto-reload)
uv run uvicorn app.main:app --reload

# The API is served at http://localhost:8000
# Liveness:   curl http://localhost:8000/health
# Readiness:  curl http://localhost:8000/health/ready
# Identity:   curl http://localhost:8000/
```

### Backend tests

```bash
cd backend
uv run pytest
```

Tests are self-contained: they run against an in-memory SQLite database and do
not require Docker/PostgreSQL.

### Backend static type check

```bash
cd backend
uv run pyright
```

## Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run the dev server (default port 5173)
npm run dev

# Production build
npm run build

# Type check
npm run typecheck

# Lint
npm run lint
```

The Vite dev server proxies `/api` to `http://localhost:8000`, so run the backend
first (`uv run uvicorn app.main:app --reload` from `backend/`) and open
`http://localhost:5173/join/<join-code>`. The join code comes from creating a
session via the host API (see the verification checklist below).

## Verification checklist (M7–M9)

```bash
# From the repo root
docker compose up -d db

# Backend
cd backend && uv sync && uv run alembic upgrade head
uv run pytest && uv run pyright
uv run uvicorn app.main:app --reload

# Setup: host -> session -> two participants (real PostgreSQL)
curl -X POST http://localhost:8000/api/v1/auth/host/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"host@school.edu","password":"correct-horse-battery"}'   # 201
curl -X POST http://localhost:8000/api/v1/auth/host/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"host@school.edu","password":"correct-horse-battery"}'
TOKEN=<host token>
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
SESSION_ID=<session id>
JOIN_CODE=<join code>
curl -X POST http://localhost:8000/api/v1/join/$JOIN_CODE/participants \
  -H 'Content-Type: application/json' -d '{"nickname":"Alice"}'
PTOKEN_A=<participant token>
curl -X POST http://localhost:8000/api/v1/join/$JOIN_CODE/participants \
  -H 'Content-Type: application/json' -d '{"nickname":"Bob"}'
PTOKEN_B=<participant token>

# Queue smoke test (needs KARAOKE_YOUTUBE_API_KEY in backend/.env)
curl -X POST http://localhost:8000/api/v1/sessions/$SESSION_ID/entries \
  -H "Authorization: Bearer $PTOKEN_A" -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://youtu.be/dQw4w9WgXcQ"}'                    # 201, position 1
curl -X POST http://localhost:8000/api/v1/sessions/$SESSION_ID/entries \
  -H "Authorization: Bearer $PTOKEN_B" -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://youtu.be/9bZkp7q19f0"}'                    # 201, position 2
curl http://localhost:8000/api/v1/sessions/$SESSION_ID/entries           # public snapshot, positions 1..2
ENTRY_ID=<entry id from the snapshot>
curl -X DELETE http://localhost:8000/api/v1/entries/$ENTRY_ID \
  -H "Authorization: Bearer $PTOKEN_A"                                   # 204 (cancel own WAITING)
curl -X PATCH http://localhost:8000/api/v1/entries/$ENTRY_ID/video \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://youtu.be/9bZkp7q19f0"}'                    # 200, position kept (host)
curl -X DELETE http://localhost:8000/api/v1/entries/$ENTRY_ID \
  -H "Authorization: Bearer $TOKEN"                                      # 204 (host remove)

# Frontend (M9: host dashboard)
cd ../frontend && npm install && npm run build && npm run typecheck && npm run lint
# Manual: with the backend running, open http://localhost:5173/host
#   -> sign in / create an account
#   -> create a session (or reopen an existing one from the list)
#   -> the dashboard shows the QR + join code + full queue; start/end the
#      session and remove/edit entries. Scan the QR with a phone to join.
```

This satisfies the M7 acceptance criteria: multiple participants submit and the
public snapshot returns the current round's queue with computed positions
(round-scoped and in stable participant order since M10.1). The per-participant
song cap (5), duplicate-song notice, participant cancel of own WAITING entries
(any round), and host remove/edit are enforced server-side. The M8 participant
screens (join/submit/queue) render exactly these backend responses; the M9 host
dashboard (auth, home, dashboard) renders the session and queue state and drives
the host actions (start/remove/edit/end) through the same backend.
Skip/finish/pause/resume are wired to the M11 playback endpoints
(`/api/v1/sessions/{id}/play/…`). Health, host auth, sessions, join, and preview
endpoints from M2-M6 are unchanged.

## UI polish verification (M9.1)

The frontend UI quality bar is the `frontend-ui` skill
(`.opencode/skills/frontend-ui/SKILL.md`); agents load it for frontend work.
Sanity checks:

```bash
cd frontend
npm run typecheck && npm run lint && npm run build
# Manual: open http://localhost:5173/host (login), create a session (home),
# open the dashboard -> labeled inputs, focus rings, QR + join code, now/next
# cards, and the queue with per-entry Edit/Remove. Participant screens:
# http://localhost:5173/join/<code> -> nickname -> submit -> queue.
```

## Realtime verification (M10)

The participant queue screen and host dashboard subscribe to
`/api/v1/sessions/{id}/ws` (bearer token in a `token` query parameter) and fall
back to polling while disconnected. Quick check:

```bash
# With the backend running (uv run uvicorn app.main:app), from backend/:
uv run python - <<'EOF'
import json, uuid, httpx
from websockets.sync.client import connect
BASE = "http://localhost:8000"; WS = "ws://localhost:8000"
email = f"rt-{uuid.uuid4().hex[:6]}@school.edu"
h = httpx.Client()
h.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = h.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
session = h.post(f"{BASE}/api/v1/sessions", json={}, headers=hh).json()
sid = session["id"]
alice = h.post(f"{BASE}/api/v1/join/{session['join_code']}/participants", json={"nickname": "Alice"}).json()["token"]
with connect(f"{WS}/api/v1/sessions/{sid}/ws?token={alice}") as ws:  # participant stream
    h.post(f"{BASE}/api/v1/join/{session['join_code']}/participants", json={"nickname": "Bob"})
    print("event:", json.loads(ws.recv(timeout=5))["type"])            # ParticipantJoined
with connect(f"{WS}/api/v1/sessions/{sid}/ws?token={host}") as ws:      # host stream
    h.post(f"{BASE}/api/v1/sessions/{sid}/start", headers=hh)
    event = json.loads(ws.recv(timeout=5))
    print("event:", event["type"], event["status"])                        # SessionUpdated ACTIVE
    h.post(f"{BASE}/api/v1/sessions/{sid}/end", headers=hh)
    event = json.loads(ws.recv(timeout=5))
    print("event:", event["type"], event["status"])                        # SessionUpdated ENDED
EOF
```

- Tokenless / cross-session / non-owner connections are rejected (close 1008
  in-process; HTTP 403 on the upgrade over a real socket).
- `QueueUpdated` events (submit/cancel/remove/edit) carry the full authoritative
  snapshot; they are covered by `backend/tests/test_realtime.py` (12 tests).
- WebSockets are delivery only (D5): after a reconnect the client re-fetches
  authoritative state, and both screens fall back to 5 s polling while the
  socket is down (B13).

## Queue rounds verification (M10.1)

The queue is round-robin: one song per participant per round, in stable
participant order, with rounds auto-advancing (no enrollment). With a YouTube
key set in `backend/.env`, from `backend/`:

```bash
uv run python - <<'EOF'
import uuid, httpx
BASE = "http://localhost:8000"
email = f"rnd-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
session = c.post(f"{BASE}/api/v1/sessions", json={}, headers=hh).json()
sid, code = session["id"], session["join_code"]
def join(n): return c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": n}).json()["token"]
def submit(t, v): return c.post(f"{BASE}/api/v1/sessions/{sid}/entries",
    json={"youtube_url": f"https://youtu.be/{v}"}, headers={"Authorization": f"Bearer {t}"}).json()
alice, bob = join("Alice"), join("Bob")
a1, a2, b1 = submit(alice, "dQw4w9WgXcQ"), submit(alice, "9bZkp7q19f0"), submit(bob, "dQw4w9WgXcQ")
print("alice song2 position (expect None):", a2["entry"]["position"])
snap = c.get(f"{BASE}/api/v1/sessions/{sid}/entries").json()
print("round 1 queue (expect Alice, Bob):", [e["participant_name"] for e in snap["queue"]])
mine = c.get(f"{BASE}/api/v1/sessions/{sid}/entries/mine", headers={"Authorization": f"Bearer {alice}"}).json()
print("alice songs (A pos 1, B None):", [(e["video_id"][:6], e["position"]) for e in mine])
for e in snap["queue"]: c.delete(f"{BASE}/api/v1/entries/{e['id']}", headers=hh)
snap2 = c.get(f"{BASE}/api/v1/sessions/{sid}/entries").json()
print("round after exhaustion (expect 2, [Alice]):", snap2["round_number"],
      [e["participant_name"] for e in snap2["queue"]])
EOF
```

- The `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT` cap (default 5) is enforced
  (6th song → 409 "you can have at most 5 songs in the queue").
- Round-robin assignment/ordering/auto-advance are covered by
  `backend/tests/test_queue.py` (9 new round tests).

## Playback verification (M11)

The host drives playback through `/api/v1/sessions/{id}/play/start|skip|finish|
pause|resume`; the snapshot reports the derived `playback_state` and each
entry's `SINGING`/`NEXT`/`WAITING` status. With a YouTube key in `backend/.env`,
from `backend/`:

```bash
uv run python - <<'EOF'
import uuid, httpx
BASE = "http://localhost:8000"
email = f"play-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
s = c.post(f"{BASE}/api/v1/sessions", json={}, headers=hh).json()
sid, code = s["id"], s["join_code"]
def join(n): return c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": n}).json()["token"]
def submit(t, v): return c.post(f"{BASE}/api/v1/sessions/{sid}/entries",
    json={"youtube_url": f"https://youtu.be/{v}"}, headers={"Authorization": f"Bearer {t}"}).status_code
def play(a): return c.post(f"{BASE}/api/v1/sessions/{sid}/play/{a}", headers=hh).json()
alice, bob = join("Alice"), join("Bob")
submit(alice, "dQw4w9WgXcQ"); submit(bob, "9bZkp7q19f0")
started = play("start")
print("playback_state (expect PLAYING):", started["playback_state"])
print("statuses (expect SINGING, WAITING):", [e["status"] for e in started["queue"]])
print("after finish (expect IDLE, NEXT):", [(e["status"]) for e in play("finish")["queue"]])
c.post(f"{BASE}/api/v1/sessions/{sid}/start", headers=hh)
print("pause (expect PAUSED):", play("pause")["status"])
print("resume (expect ACTIVE):", play("resume")["status"])
EOF
```

- The playback endpoints are host-only: a participant token returns 401, another
  host's token returns 404, and an ended session returns 409.
- Playback state is derived (D46): the snapshot's `playback_state` flips to
  `PLAYING` as soon as an entry is `SINGING`. Round boundaries auto-advance when
  a round's last entry is finished (M10.1).
- Realtime: `SingerStarted`/`SingerFinished`/`SingerSkipped` + `QueueUpdated`
  events are delivered over `/api/v1/sessions/{id}/ws`; covered by
  `backend/tests/test_playback.py` (15 tests).

## Host player verification (M12)

The host dashboard embeds the YouTube IFrame player (host browser is the
playback device, D4). Manual check with the backend running and a browser open
at `http://localhost:5173/host/sessions/<id>`:

1. Log in as the host and open a session (or create one).
2. Have a participant submit a song (needs `KARAOKE_YOUTUBE_API_KEY` in
   `backend/.env`), then click **Start next song**.
3. The player (Playback card) loads the `SINGING` entry's video and attempts to
   play it through the host machine's speakers. If the browser blocks autoplay,
   click the embedded player's native play button (E24).
4. When the video ends, the dashboard auto-calls `finish` (M11): the entry
   becomes `COMPLETED`, the next one becomes `NEXT`, and "Start next song"
   appears again. **Skip** and **Finish** stop the current video and advance.
5. A broken/embedding-restricted video shows an error in the Playback card
   (E5/E24); the host can **Skip** it or **Edit** its URL.

Automation note: transitions are automatic since M13 (cooldown → countdown →
auto-start). The player needs a real browser — it cannot be verified by the
agent test suite (which covers the build and the backend contract).

## Automatic transitions verification (M13)

Songs advance automatically: natural end → `play/end` → COOLDOWN → COUNTDOWN →
auto-start, with per-session `cooldown_seconds`/`countdown_seconds` (defaults
10/20). The host dashboard counts down and calls `play/advance` at zero. From
`backend/` (with a YouTube key in `backend/.env`):

```bash
uv run python - <<'EOF'
import uuid, time, httpx
BASE = "http://localhost:8000"
email = f"trans-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
s = c.post(f"{BASE}/api/v1/sessions", json={"cooldown_seconds": 1, "countdown_seconds": 1}, headers=hh).json()
sid, code = s["id"], s["join_code"]
alice = c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": "Alice"}).json()["token"]
c.post(f"{BASE}/api/v1/sessions/{sid}/entries", json={"youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
       headers={"Authorization": f"Bearer {alice}"})
bob = c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": "Bob"}).json()["token"]
c.post(f"{BASE}/api/v1/sessions/{sid}/entries", json={"youtube_url": "https://youtu.be/9bZkp7q19f0"},
       headers={"Authorization": f"Bearer {bob}"})
def play(a):
    r = c.post(f"{BASE}/api/v1/sessions/{sid}/play/{a}", headers=hh)
    return r.json() if r.status_code == 200 else r.json()
print("start:", play("start")["playback_state"])
print("end:", play("end")["playback_state"], "(expect COOLDOWN, ~1s remaining)")
print("advance before deadline (expect 409):", play("advance")["detail"])
time.sleep(1.2)
print("advance ->", play("advance")["playback_state"], "(expect COUNTDOWN)")
time.sleep(1.2)
started = play("advance")
print("advance ->", started["playback_state"], "(expect PLAYING)", [e["status"] for e in started["queue"]])
EOF
```

- The snapshot exposes `transition_until` and `transition_remaining_seconds`;
  the countdown auto-advances and a reopened tab with an overdue deadline
  self-recovers (no background timers, D47).
- Host `skip`/`finish` skip the cooldown and go straight to the countdown (D20);
  `start` cancels a pending transition; `pause` cancels it too (E22).
- Covered by `backend/tests/test_playback.py` (8 transition tests) and the live
  smoke above.

## Host moderation verification (M14)

The host's full authority surface is live (PRODUCT_SPEC §5.5). The moderation
behavior new to M14 — removing the current singer advances playback — is quick
to check:

```bash
# (session started, a song SINGING, more songs queued)
curl -X DELETE http://localhost:8000/api/v1/entries/<singing_entry_id> \
  -H "Authorization: Bearer <host_token>"          # 204
curl http://localhost:8000/api/v1/sessions/<id>/entries
# -> playback_state "COUNTDOWN", the next entry promoted to "NEXT"
```

- Remove / Edit / Skip / Finish / Pause / Resume / End all work from the
  dashboard; removing the current singer auto-advances (E6), and removing an
  already-terminal entry is a no-op (E21).
- Covered by `backend/tests/test_playback.py` (4 moderation tests).

## Leave session (participant)

A participant who has to leave deletes themselves and all their songs; their
nickname is freed and their token dies; if they were the current singer playback
advances (E6). Quick check from `backend/`:

```bash
# (participant token + session id)
curl -X POST http://localhost:8000/api/v1/sessions/<session_id>/leave \
  -H "Authorization: Bearer <participant_token>"      # 204
curl http://localhost:8000/api/v1/sessions/<session_id>/entries
# -> the participant and their songs are gone
```

- Covered by `backend/tests/test_leave.py` (8 tests).

## Next-singer notifications verification (M15)

In-app "you're next" notifications are delivered over the realtime channel. Quick
check from `backend/` (needs a YouTube key in `backend/.env`):

```bash
uv run python - <<'EOF'
import json, time, uuid, httpx
from websockets.sync.client import connect
BASE = "http://localhost:8000"; WS = "ws://localhost:8000"
email = f"ntf-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
s = c.post(f"{BASE}/api/v1/sessions", json={"cooldown_seconds": 1, "countdown_seconds": 1}, headers=hh).json()
sid, code = s["id"], s["join_code"]
alice = c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": "Alice"}).json()["token"]
bob = c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": "Bob"}).json()["token"]
for t in (alice, bob):
    c.post(f"{BASE}/api/v1/sessions/{sid}/entries", json={"youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
           headers={"Authorization": f"Bearer {t}"})
with connect(f"{WS}/api/v1/sessions/{sid}/ws?token={bob}") as ws:
    c.post(f"{BASE}/api/v1/sessions/{sid}/play/start", headers=hh)
    c.post(f"{BASE}/api/v1/sessions/{sid}/play/end", headers=hh)   # -> COOLDOWN
    deadline = time.time() + 6
    while time.time() < deadline:
        try:
            ev = json.loads(ws.recv(timeout=2))
        except Exception:
            break
        if ev["type"] == "NextSingerNotified":
            print("notify:", ev["phase"], ev["participant_name"], ev["title"][:20])
EOF
```

- Bob's device receives `NextSingerNotified` phase `next` when his entry becomes
  the next singer, and phase `countdown` when the countdown starts; the
  participant queue screen shows a "🎤 You're next!" banner filtered to the
  participant (auto-dismissed after 8s).
- Covered by `backend/tests/test_playback.py` (4 notification tests).

## Round cleanup + summaries verification (M16)

Absent-participant cleanup and round summaries. Quick check from `backend/`:

```bash
uv run python - <<'EOF'
import uuid, httpx
BASE = "http://localhost:8000"
email = f"sum-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
s = c.post(f"{BASE}/api/v1/sessions", json={}, headers=hh).json()
sid, code = s["id"], s["join_code"]
alice = c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": "Alice"}).json()["token"]
for _ in range(2):
    c.post(f"{BASE}/api/v1/sessions/{sid}/entries", json={"youtube_url": "https://youtu.be/dQw4w9WgXcQ"},
           headers={"Authorization": f"Bearer {alice}"})
snap = c.get(f"{BASE}/api/v1/sessions/{sid}/entries").json()
print("participants:", snap["participants"], "| rounds_completed:", snap["rounds_completed"])
summary = c.get(f"{BASE}/api/v1/sessions/{sid}/summary", headers=hh)
print("summary:", summary.status_code, summary.json()["participants"])
print("participant summary (expect 401):",
      c.get(f"{BASE}/api/v1/sessions/{sid}/summary", headers={"Authorization": f"Bearer {alice}"}).status_code)
EOF
```

- Absent-participant cleanup: a participant who hasn't connected to the realtime
  channel for `KARAOKE_ABSENT_PARTICIPANT_CLEANUP_SECONDS` (default 30 min) has
  their remaining `WAITING` songs cancelled when the snapshot is rendered (only
  for started sessions; an absent `NEXT`/`SINGING` singer stays the host's skip
  call). Covered by `backend/tests/test_rounds.py`.
- The snapshot reports `rounds_completed` and per-participant `remaining_songs`;
  the host-only `/sessions/{id}/summary` reports submitted/sung/remaining.

## Security / abuse protection verification (M17)

Rate limits protect the public QR surface (join 10/min/IP, preview 20/min/IP,
submit 20/min/IP → 429); the YouTube metadata cache protects the Data API quota.
Quick check from `backend/`:

```bash
uv run python - <<'EOF'
import uuid, httpx
BASE = "http://localhost:8000"
email = f"sec-{uuid.uuid4().hex[:8]}@school.edu"
c = httpx.Client(timeout=30)
c.post(f"{BASE}/api/v1/auth/host/register", json={"email": email, "password": "correct-horse-battery"})
host = c.post(f"{BASE}/api/v1/auth/host/login", json={"email": email, "password": "correct-horse-battery"}).json()["token"]
hh = {"Authorization": f"Bearer {host}"}
s = c.post(f"{BASE}/api/v1/sessions", json={}, headers=hh).json()
code = s["join_code"]
statuses = [c.post(f"{BASE}/api/v1/join/{code}/participants", json={"nickname": f"U{i}"}).status_code for i in range(11)]
print("join statuses:", statuses)   # 10 x 201 then 429 (rate limited)
EOF
```

- The limiter is in-process (D9/D49); `KARAOKE_RATE_LIMITS_ENABLED=false` disables
  it (the test suite sets this). Repeated previews/submissions of the same video
  are served from the 1 h metadata cache (quota saver).
- Covered by `backend/tests/test_security.py` (rate-limit tests) and
  `backend/tests/test_youtube.py` (2 cache tests).

## Concurrency / failure verification (M18)

The concurrency + failure-scenario matrix is covered by
`backend/tests/test_concurrency.py` (10 tests): deterministic ordering under
rapid submissions, find-or-create race handling (video + round), "only one
valid transition" when the host intervenes during automation, the E21
cancel-vs-remove race in both directions, and host/participant reconnect
recovery. Run the whole suite with:

```bash
cd backend && uv run pytest
```

- The test engine uses in-memory SQLite (StaticPool) so true simultaneous
  requests are exercised as rapid sequential requests; real multi-connection
  concurrency is verified against PostgreSQL at deployment (M20).
- `pyright` stays the static gate: `uv run pyright`.

## Cloud Run deployment (test)

A live test deployment runs on Google Cloud Run (single image serving the SPA +
backend on one origin; see `Dockerfile`). Deployment commands:

```bash
# Build + push (from repo root; the container serves frontend/dist + /api + WS)
docker build -t us-central1-docker.pkg.dev/portfolio-kwaku/karaoke/karaoke-app:latest .
docker push us-central1-docker.pkg.dev/portfolio-kwaku/karaoke/karaoke-app:latest

# Deploy (the database is external — a Neon free-tier Postgres in the pilot;
# Cloud SQL is the M20 production option)
gcloud run deploy karaoke-app \
  --image=us-central1-docker.pkg.dev/portfolio-kwaku/karaoke/karaoke-app:latest \
  --region=us-central1 --allow-unauthenticated --min-instances=0 --memory=512Mi --cpu=1 \
  --set-env-vars="KARAOKE_DATABASE_URL=<postgresql+asyncpg://...?ssl=require>,KARAOKE_RATE_LIMITS_ENABLED=true,KARAOKE_YOUTUBE_API_KEY=<secret>"
gcloud run services update karaoke-app --region=us-central1 \
  --update-env-vars="KARAOKE_PUBLIC_BASE_URL=$(gcloud run services describe karaoke-app --region=us-central1 --format='value(status.url)')"
```

Notes:

- The backend serves the built SPA via `KARAOKE_STATIC_DIR` (set in the image);
  the root `/` stays the liveness endpoint and SPA deep links fall back to
  `index.html` (`tests/test_spa.py`).
- **WebSockets need HTTP/1.1** (Cloud Run's default) — do not enable HTTP/2.
  With `--min-instances=0` a scale-to-zero cold start can drop a socket; the
  frontend falls back to polling (B13). Raise `--min-instances=1` for reliable
  realtime (~$7/mo).
- The Neon/YouTube credentials are passed as env vars at deploy time and are
  never committed; move them to Secret Manager for production (M20).

## CI/CD pipeline

Pushing to the `dev` branch auto-deploys to Cloud Run via
`.github/workflows/deploy-dev.yml`: auth → Docker login → build → push to Artifact
Registry → `gcloud run deploy`. No manual steps needed.

Secrets/vars (GitHub Actions, never committed):
- Secret `GCP_SA_KEY` — JSON key for `github-actions-deployer@portfolio-kwaku...`
  (used via `google-github-actions/auth@v2` `credentials_json`).
- Secret `KARAOKE_DATABASE_URL`, `KARAOKE_YOUTUBE_API_KEY` — passed as env vars at deploy.
- Variables `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ARTIFACT_REGISTRY`.

IAM on the deployer SA:
- `roles/run.admin`, `roles/artifactregistry.writer` (on the project).
- `roles/iam.serviceAccountUser` on the Cloud Run **runtime** SA
  (`NNNN-compute@developer.gserviceaccount.com`) so `gcloud run deploy` can actAs it.

> Note: we first tried keyless Workload Identity Federation (pool `github`,
> provider `friday-karaoke`), but its impersonated-credentials path kept denying
> `iam.serviceAccounts.getAccessToken` despite correct-looking bindings, so we
> pivoted to the `GCP_SA_KEY` service-account-key secret (same secret-not-in-repo
> protection). The WIF pool/provider + bindings still exist but are unused; revisit
> if we want keyless later.

## Branch / commit workflow

- Development happens on `dev`. Never commit directly to `master`.
- The `coder` agent implements milestones; `reviewer` reviews; `committer` stages
  and commits on `dev`.
- `master` only receives reviewed merges via the `/merge-to-master` command.
