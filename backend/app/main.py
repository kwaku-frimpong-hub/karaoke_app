"""Friday Karaoke backend application entry point.

M2 status: backend skeleton. Configuration uses Pydantic Settings
(``app.core.config``), logging is structured JSON (``app.core.logging``),
and the database layer is async SQLAlchemy (``app.core.database``).
Business functionality (auth, sessions, queue, playback) arrives in later
milestones.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import (
    auth,
    entries,
    health,
    join,
    participants,
    playback,
    realtime,
    sessions,
)
from app.core.config import get_settings
from app.core.logging import setup_logging


def _mount_spa(application: FastAPI, static_dir: str) -> None:
    """Serve the built React SPA on the same origin (single-image deploy).

    The SPA calls same-origin ``/api`` paths and WebSockets, so serving its
    static build from the backend keeps one origin, one HTTPS endpoint, and no
    CORS. ``/assets`` is served verbatim; any other non-``/api`` GET falls back
    to ``index.html`` so React Router deep links (``/join/{code}``, ``/host``)
    work on refresh. ``/api`` paths that match no route stay 404.
    """
    dist = Path(static_dir)
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="spa-assets")

    @application.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


def create_app(static_dir: str | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    ``static_dir`` overrides the setting (used by the deployment and tests).
    """
    settings = get_settings()
    setup_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        description="Backend for the private school karaoke queue application.",
        version=__version__,
    )
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(sessions.router)
    application.include_router(join.router)
    application.include_router(participants.router)
    application.include_router(entries.router)
    application.include_router(entries.entry_router)
    application.include_router(realtime.router)
    application.include_router(playback.router)

    resolved_static = static_dir if static_dir is not None else settings.static_dir
    if resolved_static is not None:
        _mount_spa(application, resolved_static)
    return application


app = create_app()
