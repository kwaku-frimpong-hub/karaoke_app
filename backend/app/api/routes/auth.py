"""Host authentication endpoints (M3).

Base path confirmed in M3 (decision D26): business endpoints live under
``/api/v1``; the liveness/readiness endpoints remain at the root.

- ``POST /api/v1/auth/host/register``  create a host account (public)
- ``POST /api/v1/auth/host/login``     exchange credentials for a bearer token (public)
- ``POST /api/v1/auth/host/logout``    revoke the presented bearer token (host)
- ``GET  /api/v1/auth/host/me``        current host profile (host)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import bearer_scheme, get_current_host
from app.core.database import get_session
from app.models.host import Host
from app.schemas.auth import (
    AuthResponse,
    HostLoginRequest,
    HostRegisterRequest,
    HostResponse,
)
from app.services.host_auth import (
    HostAlreadyExistsError,
    InvalidCredentialsError,
    host_auth_service,
)

router = APIRouter(prefix="/api/v1/auth/host", tags=["auth"])


def _host_to_response(host: Host) -> HostResponse:
    """Explicit mapping from the ORM model to the API schema."""
    return HostResponse(id=host.id, email=host.email, created_at=host.created_at)


@router.post("/register", response_model=HostResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: HostRegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HostResponse:
    """Create a host account from an email and password."""
    try:
        host = await host_auth_service.register(session, payload.email, payload.password)
    except HostAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a host with this email already exists",
        ) from exc
    return _host_to_response(host)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: HostLoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthResponse:
    """Authenticate a host and return a bearer token."""
    try:
        host, raw_token = await host_auth_service.login(session, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        ) from exc
    return AuthResponse(token=raw_token, host=_host_to_response(host))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    _current_host: Annotated[Host, Depends(get_current_host)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Revoke the presented bearer token (idempotent)."""
    # ``get_current_host`` guarantees the header is present and valid.
    assert credentials is not None
    await host_auth_service.logout(session, credentials.credentials)


@router.get("/me", response_model=HostResponse)
async def me(current_host: Annotated[Host, Depends(get_current_host)]) -> HostResponse:
    """Return the profile of the authenticated host."""
    return _host_to_response(current_host)
