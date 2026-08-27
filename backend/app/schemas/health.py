"""Pydantic schemas for the health endpoints."""

from typing import Literal

from pydantic import BaseModel

SERVICE_NAME = "friday-karaoke-backend"

#: The only status these endpoints report today.
HealthStatus = Literal["ok"]


class ServiceInfo(BaseModel):
    """Response body for the liveness endpoints (``/`` and ``/health``)."""

    service: str
    status: HealthStatus
    version: str


class ComponentStatus(BaseModel):
    """Per-dependency readiness status (only the database today)."""

    database: HealthStatus


class ReadinessResponse(BaseModel):
    """Response body for ``/health/ready``."""

    service: str
    status: HealthStatus
    version: str
    components: ComponentStatus
