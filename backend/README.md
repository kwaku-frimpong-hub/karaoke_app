# backend

FastAPI backend for the Friday Karaoke application.

See the repository root `README.md` and `docs/RUNBOOK.md` for setup and commands.

## Local development

```bash
# 1. Start the local PostgreSQL (from the repository root)
docker compose up -d db

# 2. Install dependencies and apply migrations
uv sync
uv run alembic upgrade head

# 3. Run the API
uv run uvicorn app.main:app --reload
```

Probes:

- `GET /` — service identity
- `GET /health` — liveness
- `GET /health/ready` — readiness (checks the database; 503 when unreachable)

Configuration is via Pydantic Settings (env prefix `KARAOKE_`); see
`app/core/config.py` and `.env.example`.

## Tests and type checks

```bash
uv run pytest     # self-contained (in-memory SQLite; no Docker required)
uv run pyright    # static type check
```

## Layout

```text
app/
    api/          # HTTP/WebSocket routers (health router)
    core/         # config (Pydantic Settings), logging, database
    domain/       # domain models/enums/state machines (M4+)
    services/     # use-cases / orchestration (M4+)
    repositories/ # persistence (M4+)
    models/       # SQLAlchemy ORM models (Base; domain tables M4+)
    schemas/      # Pydantic API schemas
    main.py       # FastAPI app factory
alembic/          # migrations
tests/            # pytest suite
```
