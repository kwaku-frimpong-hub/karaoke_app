# Friday Karaoke

Private karaoke queue application for school Friday karaoke nights.

Hosts create a session, students scan a QR code, add songs via YouTube URLs, and
the queue runs with the host's browser as the playback device.

## Repository layout

```text
backend/    FastAPI backend (uv-managed Python project)
frontend/   React + TypeScript SPA (Vite)
docs/       project documentation
plan.md     milestone definitions and acceptance criteria
```

## Documentation

Start with `docs/PROJECT_BRAIN.md` — the authoritative project context for
developers and coding agents. Also see `docs/ARCHITECTURE.md`, `docs/DOMAIN_MODEL.md`,
`docs/API_CONTRACT.md`, `docs/DECISIONS.md`, and `docs/RUNBOOK.md`.

## Quick start

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000 (health: /health)
uv run pytest
uv run pyright
```

### Frontend

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173
npm run build
npm run typecheck
```

Full local development commands: `docs/RUNBOOK.md`.

## Live deployment (test)

- **App (frontend + backend + API + WebSockets, one origin):**
  **https://karaoke-app-ywmqmgfyoa-uc.a.run.app**
- The frontend is served by the same Cloud Run container as the backend — the
  URL above IS the frontend (the SPA at `/join/:code`, `/host`, etc.) and the
  API (`/api/v1/...`) and WebSockets (`/api/v1/sessions/{id}/ws`).
- Host login: `https://karaoke-app-ywmqmgfyoa-uc.a.run.app/host`
- Backend liveness: `https://karaoke-app-ywmqmgfyoa-uc.a.run.app/health/ready`
- Database: Neon free-tier Postgres; deployment commands in `docs/RUNBOOK.md`
  (§ "Cloud Run deployment (test)").

## CI/CD

Pushing to the `dev` branch automatically builds the image and deploys it to
Cloud Run. GitHub Actions authenticates using the `github-actions-deployer`
service-account key, stored only as the encrypted `GCP_SA_KEY` Actions secret
(never in the repo/history). See `.github/workflows/deploy-dev.yml`. A future
`master` branch can get its own deploy workflow to a separate server.

## Status

All product milestones through **M18** are complete (join → round-robin queue →
automatic playback → host moderation → notifications → round summaries → abuse
protection), with a **240+ test** suite and a live Cloud Run test deployment.
Next: **M19 — PWA + mobile UX**, then **M20 — deployment**. See
`docs/DEV_BRAIN.md` for the current milestone and next task.

## Branch workflow

Development happens on the `dev` branch. `master` only receives reviewed, merged
PRs (via the `/merge-to-master` command, which runs the `reviewer` agent first).
