# Friday Karaoke — single-image deployment.
#
# One container serves the built React SPA and the FastAPI backend on a single
# origin: the SPA calls same-origin /api + WebSockets, so no CORS or separate
# proxy is needed (Cloud Run terminates HTTPS).
#
# Build:  docker build -t karaoke-app .
# Run:    docker run --rm -p 8000:8000 \
#           -e KARAOKE_DATABASE_URL=... \
#           -e KARAOKE_YOUTUBE_API_KEY=... \
#           karaoke-app

# --- Stage 1: build the React SPA ---------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend runtime (serves the SPA too) ----------------------------
FROM python:3.12-slim
ENV UV_SYSTEM_PYTHON=1 \
    PYTHONUNBUFFERED=1 \
    KARAOKE_STATIC_DIR=/app/frontend_dist
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend_dist
EXPOSE 8000
# Uvicorn serves HTTP + the /api WebSocket channel; static dir is set above.
# Cloud Run injects PORT=8080; locally (no PORT) it defaults to 8000.
CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
