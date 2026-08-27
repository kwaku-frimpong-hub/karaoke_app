"""Health and service-identity endpoints.

- ``GET /``            service identity (liveness)
- ``GET /health``      liveness
- ``GET /health/ready`` readiness: reports whether the database is reachable

The ``get_session`` dependency (see ``app.core.database``) is the FastAPI
dependency-injection seam used by every endpoint that needs the database.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.database import check_database_connection, get_session
from app.schemas.health import (
    SERVICE_NAME,
    ComponentStatus,
    HealthStatus,
    ReadinessResponse,
    ServiceInfo,
)

router = APIRouter(tags=["health"])


def _service_info(status_value: HealthStatus) -> ServiceInfo:
    return ServiceInfo(service=SERVICE_NAME, status=status_value, version=__version__)


@router.get("/", response_model=ServiceInfo)
async def root() -> ServiceInfo:
    """Service identity endpoint, used to verify the API is running."""
    return _service_info("ok")


@router.get("/health", response_model=ServiceInfo)
async def health() -> ServiceInfo:
    """Liveness check used by local tooling and, later, Docker health checks."""
    return _service_info("ok")


@router.get("/health/ready", response_model=ReadinessResponse)
async def health_ready(session: AsyncSession = Depends(get_session)) -> ReadinessResponse:
    """Readiness check: returns 200 only if the database is reachable."""
    try:
        await check_database_connection(session)
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return ReadinessResponse(
        service=SERVICE_NAME,
        status="ok",
        version=__version__,
        components=ComponentStatus(database="ok"),
    )
