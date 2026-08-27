"""FastAPI dependencies shared by host- and participant-authenticated endpoints."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.core.ratelimit import (
    RATE_LIMIT_MESSAGE,
    RateLimitExceededError,
    RateLimiter,
)
from app.models.host import Host
from app.models.participant import Participant
from app.services.host_auth import host_auth_service
from app.services.participant import participant_service

bearer_scheme = HTTPBearer(auto_error=False)

#: The shared in-process rate limiter (M17); tests replace it to force 429s.
rate_limiter = RateLimiter()


def rate_limit(
    scope: str, limit: int, window_seconds: int
) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency enforcing a fixed-window per-IP rate limit (M17).

    Disabled entirely when ``KARAOKE_RATE_LIMITS_ENABLED`` is false (the test
    suite sets this). The key is ``<scope>:<client ip>``; exceeding the limit
    returns 429.
    """

    async def _check_rate_limit(request: Request) -> None:
        if not get_settings().rate_limits_enabled:
            return
        client_ip = request.client.host if request.client is not None else "unknown"
        try:
            rate_limiter.check(f"{scope}:{client_ip}", limit, window_seconds)
        except RateLimitExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=RATE_LIMIT_MESSAGE,
            ) from exc

    return _check_rate_limit


async def get_current_host(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Host:
    """Resolve the authenticated host from the ``Authorization`` header.

    Raises HTTP 401 when the header is missing or the token is unknown,
    expired, or malformed.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    host = await host_auth_service.get_host_by_token(session, credentials.credentials)
    if host is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return host


async def get_current_participant(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Participant:
    """Resolve the participant from their opaque token (M5 tokens, D31).

    Raises HTTP 401 when the header is missing or the token is unknown.
    Session binding is checked by the endpoints that need it (404 on mismatch).
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    participant = await participant_service.get_by_token(
        session, credentials.credentials
    )
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return participant


async def get_host_or_participant(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Host | Participant:
    """Resolve the actor as either a host or a participant (M7).

    Used by shared actions (e.g. ``DELETE /api/v1/entries/{id}``) where the
    same path means "cancel own entry" for a participant and "remove any
    entry" for a host. Raises HTTP 401 when the token matches neither.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    participant = await participant_service.get_by_token(
        session, credentials.credentials
    )
    if participant is not None:
        return participant
    host = await host_auth_service.get_host_by_token(session, credentials.credentials)
    if host is not None:
        return host
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
